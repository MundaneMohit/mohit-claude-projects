"""Local review page.  python server.py  ->  http://127.0.0.1:8765  (only reachable from this computer)."""
import json, mimetypes, os, re, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import compress
import learn
import phone
from common import BASE, DATA, THUMBS, apply_protection, db, local_path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8765))
F = "','||flags||','"
GIF = f"({F} LIKE '%,gif,%')"
MEME = ("(kind='photo' AND cls IN ('meme','text') AND source NOT IN ('screenshot','camera') AND COALESCE(nfaces,0)=0 "
        "AND COALESCE(has_exif_camera,0)=0)")
SENT = "phone_path LIKE '%/Sent/%'"                 # WhatsApp Images/Sent, Video/Sent: things you sent, not received
SENTDUPE = f"({F} LIKE '%,sent_dupe,%')"            # sent copy of a photo that is still on the phone
PPL = "(COALESCE(nfaces,0)>0 OR COALESCE(people_p,0)>=0.3)"     # a face was found, or the content model sees a person (babies, side-on, far away)
DOC = "(source='whatsapp' AND kind='photo' AND COALESCE(nfaces,0)=0 AND cls IN ('document','screenshot'))"

# Lists to review, one per reason to delete. A file shows in a list until you keep it or mark it.
REVIEW = {  # key -> (title, hint, SQL condition)
    # a group counts only while at least two of its copies are still on the phone and not marked,
    # and at least one of them is undecided. Mark all but one and the group is finished.
    "dupes": ("Duplicates & look-alikes", "Identical copies are pre-selected. Look-alikes (bursts, re-sends) are shown for you to pick.",
              """dupe_group IN (SELECT dupe_group FROM files WHERE dupe_group IS NOT NULL AND state='on_phone'
                               GROUP BY dupe_group HAVING COUNT(*)>=2 AND SUM(COALESCE(keep,0)=0)>=1)"""),
    # the group is shown whole (original + sent copy) so you can compare; only the sent copy is pre-selected
    "sent_dupes": ("WhatsApp sent: duplicates", "Photos you sent on WhatsApp that you still have as the original (same size or bigger). The sent copy is pre-selected; the original stays.",
                   """dupe_group IN (SELECT s.dupe_group FROM files s WHERE s.dupe_group IS NOT NULL AND s.state='on_phone' AND COALESCE(s.keep,0)=0
                         AND (','||s.flags||',') LIKE '%,sent_dupe,%'
                         AND EXISTS (SELECT 1 FROM files o WHERE o.dupe_group=s.dupe_group AND o.id!=s.id AND o.state='on_phone' AND o.phone_path NOT LIKE '%/Sent/%'))"""),
    "wa_people": ("WhatsApp: unknown people", "Received WhatsApp photos with people you have not marked as keep. Keep people under People to shrink this list. Photos where no clear face was found (babies, backs, far away) stay here.",
                  f"source='whatsapp' AND NOT {SENT} AND kind='photo' AND protected=0 AND {PPL} AND NOT {GIF} AND NOT {MEME} AND NOT {DOC}"),
    "wa_nofaces": ("WhatsApp: no people", "Received WhatsApp photos with nobody in them: food, places, objects, things people sent you. Babies, side-on and far-away people are checked for too.",
                   f"source='whatsapp' AND NOT {SENT} AND kind='photo' AND NOT {PPL} AND NOT {GIF} AND NOT {MEME} AND NOT {DOC}"),
    "memes": ("Memes, forwards & GIFs", "Quotes, greeting cards, memes, stickers and GIFs with no real faces in them.", f"({MEME} OR {GIF})"),
    "screens": ("Screenshots & documents", "Screenshots, plus receipts and forms sent on WhatsApp. Check before deleting.",
                f"(source='screenshot' OR {DOC})"),
    "blurry": ("Blurry", "Soft or out of focus, softest first. Night shots and portraits can land here by mistake.", f"{F} LIKE '%,blurry,%'"),
    # never from the camera roll, and never the surviving copy of a duplicate group you already thinned out
    "suggested": ("Suggested deletes", "Photos from WhatsApp, downloads and other apps that look like what you delete. Camera photos are never suggested.",
                  """p_delete>=0.85 AND source!='camera'
                     AND (dupe_group IS NULL OR dupe_group NOT IN (SELECT dupe_group FROM files WHERE dupe_group IS NOT NULL AND state!='on_phone'))"""),
}
# Everything else: tools and results, shown below the review lists.
OTHER = {
    "all": ("Everything", "Every file still on the phone, newest first.", "state!='deleted'"),
    "videos": ("All videos", "Every video, largest first. Select some and press Compress, or mark them for deletion.",
               f"kind='video' AND NOT {GIF} AND {F} NOT LIKE '%,compressed,%' AND state!='deleted'"),
    "kept": ("Kept", "Photos you chose to keep. They stay out of every review list.", "keep=1 AND state!='deleted'"),
    "compressed": ("Compressed videos", "Videos already shrunk on the phone. The originals are on this computer and can be put back.",
                   f"{F} LIKE '%,compressed,%' AND state!='deleted'"),
    "marked": ("Marked for deletion", "Nothing here is deleted until you press the red button.", "state='marked'"),
    "deleted": ("Deleted (can restore)", "Removed from the phone. A backup is still on this computer.", "state='deleted'"),
}
VIEWS = {**REVIEW, **OTHER}
ORDER = {"sent_dupes": "dupe_group, dupe_keep DESC, bytes DESC", "suggested": "p_delete DESC", "dupes": "dupe_group, dupe_keep DESC, bytes DESC", "blurry": "blur ASC", "videos": "bytes DESC",
         "compressed": "bytes DESC"}
job = {"running": False, "what": "", "done": 0, "total": 0, "result": None}


def where(view):
    cond = VIEWS[view][2]
    if view in ("dupes", "sent_dupes"):      # show every copy still on the phone, including ones you kept, for comparison
        return f"({cond}) AND state='on_phone'" + ("" if view == "sent_dupes" else f" AND NOT {SENTDUPE}")
    if view in REVIEW:       # decided files leave the review lists: kept, marked and deleted
        return f"({cond}) AND state='on_phone' AND COALESCE(keep,0)=0 AND NOT {SENTDUPE}"
    return cond


def summary():
    con = db()

    def row(k):
        title, hint, _ = VIEWS[k]
        extra = " AND dupe_keep=0 AND COALESCE(keep,0)=0" if k == "dupes" else f" AND {SENTDUPE} AND COALESCE(keep,0)=0" if k == "sent_dupes" else ""
        c = con.execute(f"SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM files WHERE {where(k)}{extra}").fetchone()
        return {"key": k, "title": title, "hint": hint, "count": c[0], "bytes": c[1],
                "group": "review" if k in REVIEW else "browse" if k in ("all", "videos", "compressed") else "result"}

    out = sorted((row(k) for k in REVIEW), key=lambda v: -v["bytes"])       # biggest space first
    p = con.execute("""SELECT COUNT(DISTINCT f.person), COUNT(DISTINCT CASE WHEN f.keep=1 THEN f.person END)
                       FROM faces f JOIN files fl ON fl.id=f.file_id WHERE fl.state!='deleted'""").fetchone()
    ppl = ({"key": "people", "title": "People", "group": "browse", "count": p[0], "bytes": 0, "kept": p[1],
                "hint": "Tap the people you want to keep. Their WhatsApp photos leave the WhatsApp list. Camera photos are not affected."})
    rest = [row(k) for k in OTHER]
    return out + [v for v in rest if v["group"] == "browse"] + [ppl] + [v for v in rest if v["group"] == "result"]


SORTS = {"size": "bytes DESC", "new": "mtime DESC", "old": "mtime ASC", "score": "p_delete IS NULL, p_delete DESC, mtime DESC",
         # when you marked it / when it was deleted, newest first; marks made before logging started have no time and go last
         "when": "(SELECT MAX(a.ts) FROM actions a WHERE a.file_id=files.id AND a.action IN ('mark','delete')) IS NULL, "
                 "(SELECT MAX(a.ts) FROM actions a WHERE a.file_id=files.id AND a.action IN ('mark','delete')) DESC, mtime DESC",
         "whenold": "(SELECT MAX(a.ts) FROM actions a WHERE a.file_id=files.id AND a.action IN ('mark','delete')) IS NULL, "
                    "(SELECT MAX(a.ts) FROM actions a WHERE a.file_id=files.id AND a.action IN ('mark','delete')) ASC, mtime DESC"}


def files(view, offset, limit, person=None, sort="", unmarked=False):
    con = db()
    cond = f"state!='deleted' AND id IN (SELECT file_id FROM faces WHERE person={int(person)})" if person else where(view)
    if unmarked:       # hide files already marked for deletion (only lists that show them: Everything, All videos, a person...)
        cond = f"({cond}) AND state!='marked'"
    order = ORDER.get(view, "mtime DESC")
    if sort in SORTS and not (view in ("dupes", "sent_dupes") and not person):      # duplicates stay grouped
        order = SORTS[sort]
    elif view in ("dupes", "sent_dupes") and sort == "size" and not person:         # biggest groups first, still grouped
        order = "(SELECT SUM(g.bytes) FROM files g WHERE g.dupe_group=files.dupe_group) DESC, dupe_group, dupe_keep DESC, bytes DESC"
    rows = con.execute(f"""SELECT id,name,folder,kind,bytes,mtime,w,h,duration,vcodec,bitrate,blur,flags,state,dupe_group,dupe_keep,source,cls,p_delete,keep
                           FROM files WHERE {cond}
                           ORDER BY {order}
                           LIMIT ? OFFSET ?""",
                       (limit, offset)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        c = os.path.join(DATA, "compressed", f"{d['id']}.mp4")
        d["comp"] = os.path.getsize(c) if d["kind"] == "video" and os.path.isfile(c) else 0
        d["orig"] = 0
        if d["kind"] == "video" and ",compressed," in f",{d['flags']},":     # size before compression, from the swap log
            for x in con.execute("SELECT detail FROM actions WHERE file_id=? AND action='replace' ORDER BY id DESC LIMIT 1", (d["id"],)):
                try:
                    d["orig"] = int(x["detail"].split(" -> ")[0])
                except Exception:
                    pass
        out.append(d)
    return out


def open_in_player(fid, which):
    """Open the real file(s) in a desktop video player (VLC when installed), untouched and unconverted."""
    r = db().execute("SELECT phone_path, name FROM files WHERE id=? AND kind='video'", (fid,)).fetchone()
    if not r:
        return {"error": "not a video"}
    targets = []
    if which in ("orig", "both"):
        targets.append((local_path(r["phone_path"]), "ORIGINAL - " + r["name"]))
    comp = os.path.join(DATA, "compressed", f"{fid}.mp4")
    if which in ("comp", "both") and os.path.isfile(comp):
        targets.append((comp, "COMPRESSED - " + r["name"]))
    vlc = next((p for p in ("C:/Program Files/VideoLAN/VLC/vlc.exe", "C:/Program Files (x86)/VideoLAN/VLC/vlc.exe",
                            "/Applications/VLC.app/Contents/MacOS/VLC", "/usr/bin/vlc") if os.path.isfile(p)), None)
    for k, (path, title) in enumerate(targets):
        if not os.path.isfile(path):
            return {"error": "file is not on this computer"}
        if vlc:
            subprocess.Popen([vlc, "--no-one-instance", "--no-qt-video-autoresize", f"--meta-title={title}",
                              "--video-title-show", "--video-title-timeout=600000", f"--video-x={40 + k * 700}", "--video-y=80",
                              "--width=660", "--height=760", path])
        else:
            os.startfile(path)
    return {"ok": True, "opened": len(targets), "player": "VLC" if vlc else "default player"}


PLAY = os.path.join(DATA, "playable")
play_lock = threading.Lock()


def playable(fid, comp):
    """A browser-friendly H.264 copy for viewing only (phones record HEVC, which many browsers cannot show).
    Made on first request and cached. The original file is never changed."""
    src = os.path.join(DATA, "compressed", f"{fid}.mp4") if comp else None
    if not comp:
        r = db().execute("SELECT phone_path FROM files WHERE id=?", (fid,)).fetchone()
        src = local_path(r["phone_path"]) if r else None
    if not src or not os.path.isfile(src):
        return None
    os.makedirs(PLAY, exist_ok=True)
    out = os.path.join(PLAY, f"{fid}{'_c' if comp else ''}.mp4")
    with play_lock:
        if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(src) - 1e9 and os.path.getsize(out) > 0:
            return out
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer",
                            "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip()
        vf = "scale='min(1920,iw)':-2,format=yuv420p"
        if p in ("arib-std-b67", "smpte2084"):   # HDR clip: map to normal colours so it does not look washed out
            vf = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable,"
                  "zscale=t=bt709:m=bt709:r=tv,scale='min(1920,iw)':-2,format=yuv420p")
        tmp = out + ".part.mp4"
        e = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a?", "-vf", vf,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "aac", "-movflags", "+faststart", tmp],
                           capture_output=True, text=True)
        if e.returncode != 0 or not os.path.isfile(tmp):
            return None
        os.replace(tmp, out)
        return out


def space_saved():
    """Space freed on the phone so far: files deleted (and not restored) plus what compression saved."""
    con = db()
    deleted = con.execute("SELECT COALESCE(SUM(bytes),0), COUNT(*) FROM files WHERE state='deleted'").fetchone()
    comp = 0
    for r in con.execute("SELECT action, detail FROM actions WHERE action IN ('replace','uncompress')"):
        try:
            a, b = (int(x) for x in r["detail"].split(" -> "))
            comp += a - b          # uncompress rows are small -> big, so they subtract
        except Exception:
            pass
    # still waiting in a review list; a file in two lists is counted once
    parts = []
    for k in REVIEW:
        extra = " AND dupe_keep=0 AND COALESCE(keep,0)=0" if k == "dupes" else f" AND {SENTDUPE} AND COALESCE(keep,0)=0" if k == "sent_dupes" else ""
        parts.append(f"({where(k)}{extra})")
    rev = con.execute(f"SELECT COALESCE(SUM(bytes),0), COUNT(*) FROM files WHERE {' OR '.join(parts)}").fetchone()
    return {"bytes": deleted[0] + max(comp, 0), "deleted_bytes": deleted[0], "deleted_files": deleted[1], "compress_bytes": max(comp, 0),
            "review_bytes": rev[0], "review_files": rev[1],
            "storage": phone_storage()}


_stor = {"t": 0, "v": None}


def phone_storage():
    """Total and used bytes of the phone's storage. Asked at most once a minute; the last answer is
    kept in data/phone_storage.json so it still shows while the phone is unplugged."""
    import time
    keep = os.path.join(DATA, "phone_storage.json")
    if time.time() - _stor["t"] > 60:
        _stor["t"] = time.time()
        try:
            out = phone.adb("shell", "df -k /sdcard", timeout=10).stdout.strip().splitlines()[-1].split()
            _stor["v"] = {"total": int(out[1]) * 1024, "used": int(out[2]) * 1024, "live": True}
            json.dump(_stor["v"], open(keep, "w"))
        except Exception:
            try:
                _stor["v"] = dict(json.load(open(keep)), live=False)
            except Exception:
                _stor["v"] = None
    return _stor["v"]


def deleted_days():
    """Days on which files were deleted and are still deleted, newest first: the restore points."""
    rows = db().execute("""SELECT date(a.ts,'localtime') day, COUNT(DISTINCT f.id) n, SUM(f.bytes) bytes
                           FROM actions a JOIN files f ON f.id=a.file_id
                           WHERE a.action='delete' AND f.state='deleted'
                             AND a.id=(SELECT MAX(id) FROM actions b WHERE b.file_id=a.file_id AND b.action='delete')
                           GROUP BY day ORDER BY day DESC""").fetchall()
    return [dict(r) for r in rows]


_prog = {"t": 0, "v": None, "want": None}


def progress():
    """Where the big background run is: copy from phone -> scan -> faces and content."""
    import time
    from common import INVENTORY, IMG, MIRROR, VID, load_inventory
    if time.time() - _prog["t"] < 4 and _prog["v"]:
        return _prog["v"]
    log = os.path.join(DATA, "full_run.log")
    stage = ""
    if os.path.isfile(log):
        marks = [l.split()[1] for l in open(log, encoding="utf-8", errors="replace") if l.startswith("===")]
        stage = marks[-1] if marks else ""
    if os.path.isfile(os.path.join(DATA, "copy_running")):     # a copy from the phone is in progress
        stage = "COPY"
    v = {"stage": stage, "done": 0, "total": 0, "label": ""}
    con = db()
    if stage != "COPY":
        _prog["want"] = None
    if stage == "LIST":
        v.update(done=0, total=1, label="Checking the phone for new files. Keep the phone plugged in.")
    elif stage == "COPY":
        if _prog["want"] is None:
            inv = load_inventory()
            _prog["want"] = sum(b for p, (b, _) in inv.items() if os.path.splitext(p)[1].lower() in IMG | VID)
        got = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(MIRROR) for f in fs)
        v.update(done=got, total=_prog["want"], label=f"Copying from phone: {got / 1e9:.1f} of {_prog['want'] / 1e9:.0f} GB. Keep the phone plugged in.")
    elif stage == "SCAN":
        n = sum(len(fs) for _, _, fs in os.walk(MIRROR))
        d = con.execute("SELECT COUNT(*) FROM files WHERE sha256 IS NOT NULL OR error IS NOT NULL").fetchone()[0]
        v.update(done=d, total=n, label=f"Scanning for duplicates and blur: {d:,} of {n:,} files. Phone can be unplugged.")
    elif stage == "ANALYSE":
        n = con.execute("SELECT COUNT(*) FROM files WHERE kind='photo' AND error IS NULL").fetchone()[0]
        d = con.execute("SELECT COUNT(*) FROM embeds").fetchone()[0]
        v.update(done=d, total=n, label=f"Finding faces and content types: {d:,} of {n:,} photos. Phone can be unplugged.")
    _prog.update(t=time.time(), v=v)
    return v


def people():
    con = db()
    # deleted photos no longer count: a person whose photos are all deleted drops out of the list
    rows = con.execute("""SELECT f.person, COUNT(*) faces, COUNT(DISTINCT f.file_id) photos, MAX(f.keep) keep,
                          (SELECT COUNT(DISTINCT g.file_id) FROM faces g JOIN files x ON x.id=g.file_id WHERE g.person=f.person AND x.source='whatsapp' AND x.state!='deleted') wa,
                          (SELECT g.id FROM faces g JOIN files x ON x.id=g.file_id WHERE g.person=f.person AND x.state!='deleted' ORDER BY g.w*g.score DESC LIMIT 1) face
                          FROM faces f JOIN files fl ON fl.id=f.file_id WHERE f.person IS NOT NULL AND fl.state!='deleted'
                          GROUP BY f.person ORDER BY photos DESC""").fetchall()
    samples = {}
    for r in con.execute("""SELECT f.person, f.file_id, MAX(f.w*f.score) q FROM faces f JOIN files fl ON fl.id=f.file_id
                            WHERE f.person IS NOT NULL AND fl.state!='deleted' GROUP BY f.person, f.file_id ORDER BY f.person, q DESC"""):
        s = samples.setdefault(r["person"], [])
        if len(s) < 6:
            s.append(r["file_id"])
    return [dict(r, samples=samples.get(r["person"], [])) for r in rows]


sync_proc = None


def sync_running():
    return sync_proc is not None and sync_proc.poll() is None


def start_sync():
    """List the phone again, copy new files, scan and analyse them. Runs as its own process (sync.py)."""
    global sync_proc
    if sync_running() or job["running"]:
        return False
    lock = os.path.join(DATA, "sync_running")
    if os.path.isfile(lock):
        os.remove(lock)                      # left over from a run that was cut off
    sync_proc = subprocess.Popen([sys.executable, "sync.py"], cwd=os.path.dirname(os.path.abspath(__file__)),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _prog["t"] = 0
    return True


def watch_phone():
    """Start a sync by itself each time the phone goes from unplugged to plugged in."""
    import time
    was = False
    while True:
        try:
            now = phone.connected()
            if now and not was:
                start_sync()
            was = now
        except Exception:
            pass
        time.sleep(20)


def run_job(what, fn, ids):
    def go():
        try:
            job["result"] = fn(ids, lambda d, t: job.update(done=d, total=t))
            try:
                learn.train()          # new deletes are new lessons
            except Exception:
                pass
        except Exception as e:
            job["result"] = {"error": str(e)}
        job["running"] = False
    job.update(running=True, what=what, done=0, total=len(ids), result=None)
    threading.Thread(target=go, daemon=True).start()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache=True):
        if not os.path.isfile(path):
            return self.send(404, {"error": "not found"})
        size = os.path.getsize(path)
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            else:
                start = max(size - int(m.group(2)), 0)
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if cache:
            self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/":
            return self.send(200, open(os.path.join(BASE, "ui.html"), "rb").read(), "text/html; charset=utf-8")
        if u.path == "/api/summary":
            return self.send(200, {"views": summary(), "job": job, "phone": phone.connected(), "saved": space_saved()})
        if u.path == "/api/files":
            v = qs.get("view", ["all"])[0]
            if v not in VIEWS:
                return self.send(400, {"error": "bad view"})
            return self.send(200, files(v, int(qs.get("offset", [0])[0]), min(int(qs.get("limit", [300])[0]), 1000),
                                        qs.get("person", [None])[0], qs.get("sort", [""])[0], qs.get("unmarked", ["0"])[0] == "1"))
        m = re.match(r"/play/(\d+)$", u.path)
        if m:
            p = playable(int(m.group(1)), qs.get("comp", ["0"])[0] == "1")
            return self.send_file(p, cache=False) if p else self.send(404, {"error": "cannot make a preview"})
        if u.path == "/api/deleted_days":
            return self.send(200, deleted_days())
        if u.path == "/api/people":
            return self.send(200, people())
        if u.path == "/api/why":
            return self.send(200, learn.why(int(qs.get("id", [0])[0])))
        if u.path == "/api/progress":
            return self.send(200, progress())
        if u.path == "/api/job":
            return self.send(200, {**job, "detail": dict(compress.current)})
        m = re.match(r"/(thumb|full|comp|face)/(\d+)$", u.path)
        if m:
            if m.group(1) == "face":
                return self.send_file(os.path.join(DATA, "faces", m.group(2) + ".jpg"))
            if m.group(1) == "comp":
                return self.send_file(os.path.join(DATA, "compressed", m.group(2) + ".mp4"), cache=False)
            if m.group(1) == "thumb":
                return self.send_file(os.path.join(THUMBS, m.group(2) + ".jpg"))
            r = db().execute("SELECT phone_path FROM files WHERE id=?", (int(m.group(2)),)).fetchone()
            return self.send_file(local_path(r["phone_path"])) if r else self.send(404, {})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # only this page may ask for changes: blocks other websites from posting to the local server
        origin = self.headers.get("Origin", "")
        if origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send(403, {"error": "forbidden"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        ids = [int(i) for i in body.get("ids", [])]
        con = db()
        if self.path == "/api/mark":
            new, old = ("marked", "on_phone") if body.get("marked") else ("on_phone", "marked")
            con.executemany("UPDATE files SET state=? WHERE id=? AND state=?", [(new, i, old) for i in ids])
            con.executemany("INSERT INTO actions(file_id, action) SELECT id, ? FROM files WHERE id=? AND state=?",
                            [("mark" if new == "marked" else "unmark", i, new) for i in ids])   # logged, so a slip can be undone by time
            con.commit()
            return self.send(200, {"ok": True})
        if self.path == "/api/keep":
            con.executemany("UPDATE files SET keep=? WHERE id=?", [(1 if body.get("keep") else 0, i) for i in ids])
            con.commit()
            return self.send(200, {"ok": True, "learn": learn.train(con)})
        if self.path == "/api/decide":
            fid, d = int(body["id"]), body.get("decision")
            if d == "keep":
                con.execute("UPDATE files SET keep=1 WHERE id=?", (fid,))
            elif d == "delete":
                con.execute("UPDATE files SET state='marked' WHERE id=? AND state='on_phone'", (fid,))
                con.execute("INSERT INTO actions(file_id, action) SELECT id, 'mark' FROM files WHERE id=? AND state='marked'", (fid,))
            elif d == "undo":
                con.execute("UPDATE files SET keep=0 WHERE id=?", (fid,))
                con.execute("UPDATE files SET state='on_phone' WHERE id=? AND state='marked'", (fid,))
            con.commit()
            n = con.execute("SELECT SUM(state IN ('marked','deleted')), SUM(keep=1) FROM files").fetchone()
            info = {"delete": n[0] or 0, "keep": n[1] or 0, "trained": False}
            if (info["delete"] + info["keep"]) % 5 == 0:       # relearn every 5 decisions
                info = learn.train(con)
            return self.send(200, info)
        if self.path == "/api/openvideo":
            return self.send(200, open_in_player(int(body["id"]), body.get("which", "orig")))
        if self.path == "/api/reset":
            # start the review over: forget kept photos, kept people and what was learned. Never touches the phone,
            # and leaves "marked for deletion" and "deleted" exactly as they are.
            n = con.execute("SELECT (SELECT COUNT(*) FROM files WHERE keep=1), (SELECT COUNT(DISTINCT person) FROM faces WHERE keep=1)").fetchone()
            con.execute("UPDATE files SET keep=0, p_delete=NULL")
            con.execute("UPDATE faces SET keep=0")
            con.execute("INSERT INTO actions(action, detail) VALUES('reset', ?)", (f"{n[0]} kept photos, {n[1]} kept people",))
            apply_protection(con)
            return self.send(200, {"ok": True, "photos": n[0], "people": n[1]})
        if self.path == "/api/people/keep":
            con.executemany("UPDATE faces SET keep=? WHERE person=?",
                            [(1 if body.get("keep") else 0, int(p)) for p in body.get("persons", [body.get("person")]) if p is not None])
            con.execute("INSERT INTO actions(action, detail) VALUES(?,?)",
                        ("people_keep" if body.get("keep") else "people_unkeep", json.dumps(body.get("persons", [body.get("person")]))))
            apply_protection(con)
            return self.send(200, {"ok": True})
        if self.path == "/api/sync":
            if sync_running():
                return self.send(409, {"error": "A sync is already running."})
            if job["running"]:
                return self.send(409, {"error": "Another job is still running."})
            if not phone.connected():
                return self.send(409, {"error": phone.NOT_CONNECTED})
            start_sync()
            return self.send(200, {"ok": True})
        if self.path in ("/api/compress", "/api/uncompress"):
            if job["running"]:
                return self.send(409, {"error": "another job is running"})
            if not phone.connected():
                return self.send(409, {"error": phone.NOT_CONNECTED})
            ids = [r[0] for r in con.execute(f"SELECT id FROM files WHERE kind='video' AND state='on_phone' AND id IN ({','.join(map(str, ids)) or 0})")]
            if self.path == "/api/compress":
                s4 = bool(body.get("scale4k"))
                run_job("Compressing videos", lambda i, p: compress.job(i, p, scale4k=s4), ids)
            else:
                run_job("Putting originals back", compress.undo_job, ids)
            return self.send(200, {"ok": True, "total": len(ids)})
        if self.path in ("/api/delete", "/api/restore"):
            if job["running"]:
                return self.send(409, {"error": "another job is running"})
            if not phone.connected():
                return self.send(409, {"error": phone.NOT_CONNECTED})
            if self.path == "/api/delete":
                ids = [r[0] for r in con.execute("SELECT id FROM files WHERE state='marked'")]
                # guardrail: an unusually large delete needs the exact count typed back
                total = con.execute("SELECT COUNT(*) FROM files WHERE state!='deleted'").fetchone()[0]
                if (len(ids) > 500 or len(ids) > 0.2 * total) and str(body.get("typed", "")).strip() != str(len(ids)):
                    return self.send(409, {"error": f"This is a large delete ({len(ids)} files). Type {len(ids)} in the box to confirm.",
                                           "need_typed": len(ids)})
                run_job("Deleting from phone", phone.delete, ids)
            else:
                if body.get("day"):   # everything deleted on that day
                    ids = [r[0] for r in con.execute("""SELECT DISTINCT f.id FROM actions a JOIN files f ON f.id=a.file_id
                               WHERE a.action='delete' AND f.state='deleted' AND date(a.ts,'localtime')=?
                                 AND a.id=(SELECT MAX(id) FROM actions b WHERE b.file_id=a.file_id AND b.action='delete')""",
                                                    (body["day"],))]
                run_job("Restoring to phone", phone.restore, ids)
            return self.send(200, {"ok": True, "total": len(ids)})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"Photo cleaner: http://127.0.0.1:{PORT}", flush=True)
    if os.path.isfile(compress.QUEUE):          # a compression run was interrupted: carry on with what is left
        try:
            q = json.load(open(compress.QUEUE))
            left, s4 = (q["ids"], bool(q.get("scale4k"))) if isinstance(q, dict) else (q, False)
            left = [r[0] for r in db().execute(f"SELECT id FROM files WHERE kind='video' AND state='on_phone' AND ','||flags||',' NOT LIKE '%,compressed,%' AND id IN ({','.join(str(int(i)) for i in left) or 0})")]
            if left and phone.connected():
                run_job("Compressing videos", lambda i, p: compress.job(i, p, scale4k=s4), left)
        except Exception:
            pass
    threading.Thread(target=watch_phone, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
