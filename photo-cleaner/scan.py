"""Analyse the local copies in data/mirror and flag what is probably junk. Never touches the phone.

  python scan.py            # scan new files, then recompute duplicates and flags

Per file: sha256, look-alike hash, sharpness, size, EXIF camera/date, video codec/bitrate, a preview.
Flags: screenshot, whatsapp, saved (no camera EXIF), blurry, dupe_exact, dupe_near, big_video, gif.
"""
import hashlib, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import imagehash
from PIL import Image, ImageOps

from common import IMG, THUMBS, VID, db, load_inventory, local_path

Image.MAX_IMAGE_PIXELS = None
BLUR_LIMIT = 45.0            # sharpness below this = "blurry" (calibrated on the test batch)
NEAR_DIST = 5                # look-alike hash distance (of 64 bits)
BIG_VIDEO_BYTES = 25e6
BIG_VIDEO_KBPS_PER_MPIX = 4500   # above this bitrate per megapixel a re-encode saves a lot


def source_of(path):
    name = os.path.basename(path)
    if "/Screenshots/" in path or name.lower().startswith(("screenshot", "screen_recording", "screenrecord")):
        return "screenshot"
    if "com.whatsapp" in path or re.search(r"-WA\d+", name):
        return "whatsapp"
    if path.startswith("/sdcard/Download"):
        return "download"
    if path.startswith("/sdcard/DCIM/"):
        return "camera"
    return "other"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sharpness(im):
    """Variance of the Laplacian on a 1024px grey copy. Low = soft or out of focus."""
    g = im.convert("L")
    g.thumbnail((1024, 1024))
    a = np.asarray(g, dtype=np.float32)
    if a.shape[0] < 8 or a.shape[1] < 8:
        return None
    lap = a[1:-1, 1:-1] * 4 - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(lap.var())


def do_photo(lp, thumb, rec):
    with Image.open(lp) as im:
        rec["w"], rec["h"] = im.size
        ex = im.getexif()
        make = (str(ex.get(271, "")) + " " + str(ex.get(272, ""))).strip()
        rec["has_exif_camera"] = 1 if make else 0
        try:
            sub = ex.get_ifd(0x8769)
            rec["taken"] = str(sub.get(36867) or ex.get(306) or "") or None
        except Exception:
            pass
        im.draft("RGB", (1400, 1400))
        im = ImageOps.exif_transpose(im).convert("RGB")
        rec["blur"] = sharpness(im)
        t = im.copy()
        t.thumbnail((360, 360))
        t.save(thumb, quality=78)
        rec["phash"] = str(imagehash.phash(t))


def do_video(lp, thumb, rec):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,codec_name,bit_rate:stream_side_data=rotation:format=duration,bit_rate:format_tags=creation_time",
                        "-of", "json", lp], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    f = j.get("format", {})
    rec["w"], rec["h"] = s.get("width"), s.get("height")
    rec["vcodec"] = s.get("codec_name")
    rec["duration"] = float(f.get("duration") or 0)
    rec["bitrate"] = int(s.get("bit_rate") or f.get("bit_rate") or 0)
    rec["taken"] = (f.get("tags") or {}).get("creation_time")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1" if rec["duration"] > 2 else "0", "-i", lp,
                    "-frames:v", "1", "-vf", "scale=360:360:force_original_aspect_ratio=decrease", thumb],
                   capture_output=True)
    if os.path.exists(thumb):
        with Image.open(thumb) as t:
            rec["phash"] = str(imagehash.phash(t))


def process(row):
    fid, path = row
    lp = local_path(path)
    ext = os.path.splitext(path)[1].lower()
    rec = {"id": fid, "sha256": None, "phash": None, "blur": None, "w": None, "h": None, "taken": None,
           "duration": None, "vcodec": None, "bitrate": None, "has_exif_camera": None, "error": None}
    thumb = os.path.join(THUMBS, f"{fid}.jpg")
    try:
        rec["sha256"] = sha(lp)
        (do_video if ext in VID else do_photo)(lp, thumb, rec)
    except Exception as e:
        rec["error"] = str(e)[:200]
    return rec


def scan_new(con):
    inv = load_inventory()
    have = {r["phone_path"]: (r["bytes"], r["mtime"], r["sha256"]) for r in con.execute("SELECT * FROM files")}
    todo = []
    for path, (b, mt) in inv.items():
        ext = os.path.splitext(path)[1].lower()
        lp = local_path(path)
        if ext not in IMG | VID or not os.path.isfile(lp) or os.path.getsize(lp) != b:
            continue      # not copied yet, or only partly copied (the copy was interrupted)
        if path in have and have[path][:2] == (b, mt) and have[path][2]:
            continue
        con.execute("""INSERT INTO files(phone_path,name,folder,ext,kind,bytes,mtime,source) VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(phone_path) DO UPDATE SET bytes=excluded.bytes, mtime=excluded.mtime""",
                    (path, os.path.basename(path), os.path.dirname(path).replace("/sdcard/", ""), ext,
                     "video" if ext in VID else "photo", b, mt, source_of(path)))
        todo.append(path)
    con.commit()
    ids = {r["phone_path"]: r["id"] for r in con.execute("SELECT id, phone_path FROM files")}
    work = [(ids[p], p) for p in todo]
    print(f"Scanning {len(work)} new files...", flush=True)
    with ThreadPoolExecutor(8) as ex:
        for n, rec in enumerate(ex.map(process, work), 1):
            con.execute("""UPDATE files SET sha256=:sha256, phash=:phash, blur=:blur, w=:w, h=:h, taken=:taken,
                           duration=:duration, vcodec=:vcodec, bitrate=:bitrate, has_exif_camera=:has_exif_camera,
                           error=:error WHERE id=:id""", rec)
            if n % 100 == 0 or n == len(work):
                con.commit()
                print(f"PROGRESS {n} {len(work)}", flush=True)
    con.commit()


def find_dupes(con):
    rows = [dict(r) for r in con.execute("SELECT * FROM files WHERE state!='deleted' AND sha256 IS NOT NULL")]
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_sha = {}
    for r in rows:
        by_sha.setdefault(r["sha256"], []).append(r["id"])
    for ids in by_sha.values():
        for x in ids[1:]:
            parent[find(x)] = find(ids[0])

    # look-alikes: photos only, compared with vectorised XOR + popcount
    ph = [r for r in rows if r["kind"] == "photo" and r["phash"]]
    if ph:
        h = np.array([int(r["phash"], 16) for r in ph], dtype=np.uint64)
        shot = np.array([r["source"] == "screenshot" or r["ext"] == ".png" for r in ph])
        for i in range(len(ph) - 1):
            d = np.bitwise_count(h[i + 1:] ^ h[i])
            # screenshots of the same app look alike to a hash, so demand a near-identical hash there
            lim = np.where(shot[i + 1:] | shot[i], 1, NEAR_DIST)
            for j in np.nonzero(d <= lim)[0]:
                parent[find(ph[i + 1 + int(j)]["id"])] = find(ph[i]["id"])

    groups = {}
    for r in rows:
        groups.setdefault(find(r["id"]), []).append(r)
    con.execute("UPDATE files SET dupe_group=NULL, dupe_keep=0")
    gid = 0
    exact = near = 0
    for g in groups.values():
        if len(g) < 2:
            continue
        gid += 1
        # keeper: camera original first, then most pixels, then sharpest, then biggest file
        g.sort(key=lambda r: (r["source"] != "camera", -((r["w"] or 0) * (r["h"] or 0)), -(r["blur"] or 0), -r["bytes"]))
        keep_sha = g[0]["sha256"]
        for k, r in enumerate(g):
            con.execute("UPDATE files SET dupe_group=?, dupe_keep=? WHERE id=?", (gid, 1 if k == 0 else 0, r["id"]))
            r["_dupe"] = None if k == 0 else ("dupe_exact" if r["sha256"] == keep_sha else "dupe_near")
            exact += r["_dupe"] == "dupe_exact"
            near += r["_dupe"] == "dupe_near"
    con.commit()
    print(f"{gid} duplicate groups: {exact} exact copies, {near} look-alikes")
    return {r["id"]: r.get("_dupe") for r in rows}


SENT_DIST = 4    # a sent copy must look like its original within this many hash bits (of 64)


def is_sent(path):
    return "/WhatsApp" in path and "/Sent/" in path


def sent_dupes(con):
    """Photos you sent on WhatsApp that are only a copy of a photo you still have: same picture, and the
    original has at least as many pixels (WhatsApp shrinks what it sends). Deleting the sent copy loses nothing."""
    rows = [dict(r) for r in con.execute("SELECT id, phone_path, phash, w, h, dupe_group, sha256, state FROM files WHERE kind='photo' AND dupe_group IS NOT NULL AND phash IS NOT NULL")]
    groups = {}
    for r in rows:
        groups.setdefault(r["dupe_group"], []).append(r)
    out = set()
    for g in groups.values():
        orig = [r for r in g if not is_sent(r["phone_path"]) and r["state"] != "deleted"]
        for r in g:
            if not is_sent(r["phone_path"]) or not orig:
                continue
            px = (r["w"] or 0) * (r["h"] or 0)
            for o in orig:
                same = o["sha256"] == r["sha256"] or bin(int(o["phash"], 16) ^ int(r["phash"], 16)).count("1") <= SENT_DIST
                if same and (o["w"] or 0) * (o["h"] or 0) >= px:
                    out.add(r["id"])
                    break
    return out


def set_flags(con, dupe):
    sent = sent_dupes(con)
    print(f"{len(sent)} sent copies of photos you still have")
    for r in con.execute("SELECT * FROM files").fetchall():
        f = []
        if r["id"] in sent:
            f.append("sent_dupe")
        if r["source"] == "screenshot":
            f.append("screenshot")
        if r["source"] == "whatsapp":
            f.append("whatsapp")
        if r["ext"] == ".gif" or "Animated Gifs" in r["phone_path"]:
            f.append("gif")
        if r["kind"] == "photo" and r["source"] == "camera" and r["has_exif_camera"] == 0:
            f.append("saved")
        if r["kind"] == "photo" and r["blur"] is not None and r["blur"] < BLUR_LIMIT and r["source"] != "screenshot":
            f.append("blurry")
        if dupe.get(r["id"]):
            f.append(dupe[r["id"]])
        if r["kind"] == "video" and r["bytes"] >= BIG_VIDEO_BYTES and r["w"] and r["bitrate"]:
            mpix = max(r["w"] * r["h"] / 1e6, 0.3)
            if r["bitrate"] / 1000 / mpix > BIG_VIDEO_KBPS_PER_MPIX:
                f.append("big_video")
        if "compressed" in (r["flags"] or "").split(","):      # set by compress.py, not derived from the file: keep it
            f = [x for x in f if x != "big_video"] + ["compressed"]
        con.execute("UPDATE files SET flags=? WHERE id=?", (",".join(f), r["id"]))
    con.commit()


if __name__ == "__main__":
    con = db()
    scan_new(con)
    set_flags(con, find_dupes(con))
    print("--- summary")
    tot = con.execute("SELECT COUNT(*), SUM(bytes) FROM files").fetchone()
    print(f"  {'all files':14} {tot[0]:6}  {tot[1] / 1e9:7.2f} GB")
    for fl in ("dupe_exact", "dupe_near", "screenshot", "whatsapp", "saved", "blurry", "gif", "big_video"):
        c = con.execute("SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM files WHERE ','||flags||',' LIKE ?", (f"%,{fl},%",)).fetchone()
        print(f"  {fl:14} {c[0]:6}  {c[1] / 1e9:7.2f} GB")
    err = con.execute("SELECT COUNT(*) FROM files WHERE error IS NOT NULL").fetchone()[0]
    print(f"  unreadable: {err}")
