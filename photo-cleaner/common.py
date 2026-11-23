"""Shared paths and helpers for the phone photo cleaner."""
import os, sqlite3, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
MIRROR = os.path.join(DATA, "mirror")      # local copies, same folder layout as the phone
THUMBS = os.path.join(DATA, "thumbs")
DB = os.path.join(DATA, "cleaner.db")
INVENTORY = os.path.join(DATA, "phone_inventory.txt")
ADB = os.path.join(BASE, "bin", "platform-tools", "adb.exe")
EXIFTOOL = os.path.join(BASE, "bin", "exiftool", "exiftool-13.63_64", "exiftool.exe")

IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp", ".dng"}
VID = {".mp4", ".mov", ".mkv", ".3gp", ".webm", ".avi", ".m4v"}

for d in (DATA, MIRROR, THUMBS):
    os.makedirs(d, exist_ok=True)


def local_path(phone_path):
    """/sdcard/DCIM/Camera/x.jpg -> data/mirror/DCIM/Camera/x.jpg"""
    rel = phone_path.replace("/sdcard/", "", 1).replace("/", os.sep)
    return os.path.join(MIRROR, rel)


def adb(*args, timeout=600):
    return subprocess.run([ADB, *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def load_inventory():
    """phone path -> (bytes, mtime) from the read-only listing taken over adb."""
    inv = {}
    with open(INVENTORY, encoding="utf-8", errors="replace") as f:
        for line in f:
            p = line.rstrip("\r\n").split("|", 2)
            if len(p) == 3 and p[0].isdigit():
                inv[p[2]] = (int(p[0]), int(p[1]))
    return inv


def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS files(
      id INTEGER PRIMARY KEY, phone_path TEXT UNIQUE, name TEXT, folder TEXT, ext TEXT, kind TEXT,
      bytes INTEGER, mtime INTEGER, taken TEXT, w INTEGER, h INTEGER, duration REAL,
      vcodec TEXT, bitrate INTEGER, sha256 TEXT, phash TEXT, blur REAL, has_exif_camera INTEGER,
      source TEXT,            -- camera / whatsapp / screenshot / download / other
      flags TEXT DEFAULT '',  -- comma list: screenshot, whatsapp, blurry, dupe_exact, dupe_near, big_video, gif
      dupe_group INTEGER, dupe_keep INTEGER DEFAULT 0,
      error TEXT,
      state TEXT DEFAULT 'on_phone'   -- on_phone / trashed / deleted / replaced
    );
    CREATE INDEX IF NOT EXISTS i_sha ON files(sha256);
    CREATE INDEX IF NOT EXISTS i_grp ON files(dupe_group);
    CREATE TABLE IF NOT EXISTS actions(
      id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, file_id INTEGER, action TEXT, detail TEXT
    );
    CREATE TABLE IF NOT EXISTS embeds(file_id INTEGER PRIMARY KEY, vec BLOB);
    CREATE TABLE IF NOT EXISTS faces(id INTEGER PRIMARY KEY, file_id INTEGER, x REAL, y REAL, w REAL, h REAL,
                                     score REAL, vec BLOB, person INTEGER, keep INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS i_face_file ON faces(file_id);
    CREATE INDEX IF NOT EXISTS i_face_person ON faces(person);
    """)
    have = {r[1] for r in con.execute("PRAGMA table_info(files)")}
    for col in ("cls TEXT", "cls_conf REAL", "nfaces INTEGER", "protected INTEGER DEFAULT 0",
                "keep INTEGER DEFAULT 0", "p_delete REAL", "people_p REAL"):
        if col.split()[0] not in have:
            con.execute(f"ALTER TABLE files ADD COLUMN {col}")
    return con


def apply_protection(con):
    """WhatsApp photos that contain a person marked 'keep' leave the WhatsApp review lists.
    Camera-roll photos are never protected: you may still want to delete photos of people you keep."""
    con.execute("UPDATE files SET protected=0 WHERE protected!=0")
    con.execute("UPDATE files SET protected=1 WHERE source='whatsapp' AND id IN "
                "(SELECT file_id FROM faces WHERE person IN (SELECT person FROM faces WHERE keep=1))")
    con.commit()
