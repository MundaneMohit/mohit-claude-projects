"""Shrink videos without losing their date, location or camera metadata.

  python compress.py <file id> [...]      # encode on this computer only, nothing changes on the phone

encode(): re-encodes to HEVC, copies every metadata tag from the original with exiftool, sets the
original modified date, and keeps the result only if it is clearly smaller and the same length.
replace_on_phone(): swaps the phone copy for the smaller one under the same name and date. The
original stays on this computer in data/originals.
"""
import json, os, shutil, subprocess, sys

import phone
from common import DATA, EXIFTOOL, adb, db, local_path

COMP = os.path.join(DATA, "compressed")
ORIG = os.path.join(DATA, "originals")
CRF = 24            # x265 quality: lower = better and bigger
PRESET = "superfast"  # measured: same similarity score as "medium" at CRF 26, ~10% bigger files, about 3x faster
current = {"name": "", "pct": 0}   # what is being encoded right now, for the progress display
ESSENTIAL = ("CreateDate", "MediaCreateDate", "GPSCoordinates")   # must match exactly; camera model etc. is best effort
MIN_SAVING = 0.25   # keep the result only if it is at least 25% smaller


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,pix_fmt",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def tags(path):
    r = subprocess.run([EXIFTOOL, "-j", "-n", "-CreateDate", "-MediaCreateDate", "-GPSCoordinates", "-Make", "-Model",
                        "-Rotation", "-AndroidVersion", path], capture_output=True, text=True)
    t = (json.loads(r.stdout or "[{}]") or [{}])[0]
    t.pop("SourceFile", None)
    t.pop("Rotation", None)   # the encode stores the picture upright, so this tag is expected to become 0
    return t


def encode(fid, keep_failed=False, scale4k=False):
    con = db()
    r = con.execute("SELECT * FROM files WHERE id=? AND kind='video'", (fid,)).fetchone()
    if not r:
        return {"error": "not a video"}
    src = local_path(r["phone_path"])
    out = os.path.join(COMP, f"{fid}.mp4")
    os.makedirs(COMP, exist_ok=True)
    # optional: bring anything bigger than 1080p down to 1080p (short side 1080), keeping the shape
    vf = (["-vf", "scale='if(gt(iw,ih),-2,1080)':'if(gt(iw,ih),1080,-2)'"]
          if scale4k and min(r["w"] or 0, r["h"] or 0) > 1080 else [])
    cmd = ["ffmpeg", "-v", "error", "-y", "-nostats", "-progress", "pipe:1", "-i", src, "-map", "0:v:0", "-map", "0:a?", *vf,
           "-c:v", "libx265", "-crf", str(CRF), "-preset", PRESET, "-x265-params", "log-level=error", "-tag:v", "hvc1",
           "-c:a", "copy", "-map_metadata", "0", "-movflags", "+faststart", out]
    current.update(name=r["name"], pct=0)
    e = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    for line in e.stdout:                      # ffmpeg reports how far into the video it is
        if line.startswith("out_time_us=") and r["duration"]:
            try:
                current["pct"] = min(99, int(100 * int(line.split("=")[1]) / 1e6 / r["duration"]))
            except ValueError:
                pass
    e.wait()
    current.update(name="", pct=0)
    if e.returncode != 0 or not os.path.isfile(out):
        if os.path.isfile(out):
            os.remove(out)
        return {"error": "the video could not be encoded"}
    # every tag ffmpeg dropped (location, Samsung/Android tags, creation dates) comes back from the original
    subprocess.run([EXIFTOOL, "-overwrite_original", "-q", "-tagsFromFile", src, "-all:all", out], capture_output=True)
    os.utime(out, (r["mtime"], r["mtime"]))
    a, b = probe(src), probe(out)
    da, dbb = float(a["format"]["duration"]), float(b["format"]["duration"])
    saving = 1 - os.path.getsize(out) / r["bytes"]
    res = {"id": fid, "name": r["name"], "before": r["bytes"], "after": os.path.getsize(out), "saving": round(saving, 3),
           "tags_before": tags(src), "tags_after": tags(out)}
    if abs(da - dbb) > 0.5:
        res["error"] = f"length changed ({da:.1f}s -> {dbb:.1f}s)"
    elif saving < MIN_SAVING:
        res["error"] = f"only {saving:.0%} smaller, not worth it"
    elif any(res["tags_before"].get(k) != res["tags_after"].get(k) for k in ESSENTIAL):
        res["error"] = "date or location did not survive"
    if "error" in res and not keep_failed:
        os.remove(out)
    else:
        con.execute("INSERT INTO actions(file_id, action, detail) VALUES(?,?,?)", (fid, "encode", json.dumps(res)))
        con.commit()
    return res


def replace_on_phone(fid):
    """Swap the phone copy for the compressed one. Same name, same modified date."""
    con = db()
    r = con.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    out = os.path.join(COMP, f"{fid}.mp4")
    path, tmp = r["phone_path"], r["phone_path"] + ".cleaner_tmp"
    if not os.path.isfile(out):
        return {"error": "encode it first"}
    if phone.stat_many([path]).get(path) != (r["bytes"], r["mtime"]):
        return {"error": "changed or missing on the phone"}
    src = local_path(path)
    if not os.path.isfile(src) or os.path.getsize(src) != r["bytes"]:
        return {"error": "no backup of the original on this computer"}
    new_bytes = os.path.getsize(out)
    adb("push", out, tmp, timeout=3600)
    if phone.stat_many([tmp]).get(tmp, (0, 0))[0] != new_bytes:
        adb("shell", "rm -f -- " + phone.q(tmp))
        return {"error": "copy to phone did not complete"}
    adb("shell", f"mv -f -- {phone.q(tmp)} {phone.q(path)} && touch -m -d @{r['mtime']} {phone.q(path)}")
    if phone.stat_many([path]).get(path) != (new_bytes, r["mtime"]):
        return {"error": "phone copy does not match after the swap; original is still on this computer"}
    keep = os.path.join(ORIG, os.path.relpath(src, os.path.join(DATA, "mirror")))
    os.makedirs(os.path.dirname(keep), exist_ok=True)
    shutil.move(src, keep)          # original kept as the undo copy
    shutil.move(out, src)           # mirror now matches the phone again
    v = next((s for s in probe(src).get("streams", []) if s.get("codec_type") == "video"), {})
    con.execute("UPDATE files SET bytes=?, w=COALESCE(?,w), h=COALESCE(?,h), flags=replace(flags,'big_video','compressed') WHERE id=?",
                (new_bytes, v.get("width"), v.get("height"), fid))
    if "compressed" not in (con.execute("SELECT flags FROM files WHERE id=?", (fid,)).fetchone()[0] or ""):
        con.execute("UPDATE files SET flags=trim(flags||',compressed', ',') WHERE id=?", (fid,))
    con.execute("INSERT INTO actions(file_id, action, detail) VALUES(?,?,?)", (fid, "replace", f"{r['bytes']} -> {new_bytes}"))
    con.commit()
    return {"id": fid, "before": r["bytes"], "after": new_bytes}


def restore_original(fid):
    """Undo a compression: put the original video back on the phone, same name and date."""
    con = db()
    r = con.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    path, src = r["phone_path"], local_path(r["phone_path"])
    keep = os.path.join(ORIG, os.path.relpath(src, os.path.join(DATA, "mirror")))
    if not os.path.isfile(keep):
        return {"error": "the original is no longer on this computer"}
    if phone.stat_many([path]).get(path) != (r["bytes"], r["mtime"]):
        return {"error": "changed or missing on the phone"}
    tmp, size = path + ".cleaner_tmp", os.path.getsize(keep)
    adb("push", keep, tmp, timeout=3600)
    if phone.stat_many([tmp]).get(tmp, (0, 0))[0] != size:
        adb("shell", "rm -f -- " + phone.q(tmp))
        return {"error": "copy to phone did not complete"}
    adb("shell", f"mv -f -- {phone.q(tmp)} {phone.q(path)} && touch -m -d @{r['mtime']} {phone.q(path)}")
    if phone.stat_many([path]).get(path) != (size, r["mtime"]):
        return {"error": "phone copy does not match after restoring"}
    os.remove(src)
    shutil.move(keep, src)
    con.execute("UPDATE files SET bytes=?, flags=replace(flags,'compressed','big_video') WHERE id=?", (size, fid))
    con.execute("INSERT INTO actions(file_id, action, detail) VALUES(?,?,?)", (fid, "uncompress", f"{r['bytes']} -> {size}"))
    con.commit()
    return {"id": fid, "before": r["bytes"], "after": size}


def undo_job(ids, progress=lambda d, t: None):
    res = {"done": 0, "bytes": 0, "skipped": []}
    for n, fid in enumerate(ids, 1):
        s = restore_original(fid)
        if "error" in s:
            res["skipped"].append([str(fid), s["error"]])
        else:
            res["done"] += 1
        progress(n, len(ids))
    return res


QUEUE = os.path.join(DATA, "compress_queue.json")


def job(ids, progress=lambda d, t: None, scale4k=False):
    """Encode then swap, one video at a time. Used by the review page.
    The videos still to do are written to a small file, so if the page is restarted mid-run
    the job picks up again by itself instead of silently stopping."""
    res = {"done": 0, "bytes": 0, "skipped": []}
    for n, fid in enumerate(ids, 1):
        with open(QUEUE, "w") as f:
            json.dump({"ids": ids[n - 1:], "scale4k": scale4k}, f)
        e = encode(fid, scale4k=scale4k)
        s = e if "error" in e else replace_on_phone(fid)
        if "error" in s:
            res["skipped"].append([e.get("name", str(fid)), s["error"]])
        else:
            res["done"] += 1
            res["bytes"] += s["before"] - s["after"]
        progress(n, len(ids))
    if os.path.isfile(QUEUE):
        os.remove(QUEUE)
    return res


if __name__ == "__main__":
    import time
    for fid in map(int, sys.argv[1:]):
        t = time.time()
        r = encode(fid)
        print(json.dumps(r, indent=1), f"\n  took {time.time() - t:.0f}s")
