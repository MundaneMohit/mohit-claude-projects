"""Pick up what changed on the phone: list it again, copy new files, scan and analyse them.

  python sync.py

Read-only on the phone. Safe to run again at any time; every step skips what is already done.
The server starts this by itself when the phone is plugged in, and from the "Sync new files" button.
"""
import os, subprocess, sys, time

from common import ADB, BASE, DATA, IMG, INVENTORY, VID, db, load_inventory

ROOTS = ("/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Download", "/sdcard/Movies", "/sdcard/Android/media/com.whatsapp")
# app caches and sticker packs: not your photos, and WhatsApp needs its stickers
SKIP = ("/.thumbnails/", "Stickers/", "/.Shared/", "/.Links/", "/.Statuses/", "/.cleaner_tmp", "/.trashed-")
LOG = os.path.join(DATA, "full_run.log")
LOCK = os.path.join(DATA, "sync_running")
COPY = os.path.join(DATA, "copy_running")


def mark(stage):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"=== {stage} {time.strftime('%H:%M:%S')}\n")


def wanted(path):
    return os.path.splitext(path)[1].lower() in IMG | VID and not any(s in path for s in SKIP)


def list_phone():
    """size|mtime|path for every photo and video. xargs keeps each stat call short: one long
    `find -exec stat {} +` silently drops files in big folders ("Argument list too long")."""
    found = {}
    for root in ROOTS:
        cmd = f"find '{root}' -type f -print0 | xargs -0 -n 200 stat -c '%s|%Y|%n'"
        r = subprocess.run([ADB, "shell", cmd], capture_output=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"listing {root} failed: {r.stderr.decode(errors='replace')[:200]}")
        n = 0
        for line in r.stdout.decode("utf-8", errors="replace").splitlines():
            p = line.rstrip("\r").split("|", 2)
            if len(p) == 3 and p[0].isdigit() and wanted(p[2]):
                found[p[2]] = (int(p[0]), int(p[1]))
                n += 1
        # the count must match a plain `find | wc -l` of the same files, or the listing is not trusted
        c = subprocess.run([ADB, "shell", f"find '{root}' -type f | wc -l"], capture_output=True, text=True, timeout=900)
        total = int(c.stdout.strip() or 0)
        raw = len([l for l in r.stdout.splitlines() if l.strip()])
        if abs(raw - total) > 5:
            raise RuntimeError(f"listing {root} is incomplete: {raw} of {total} files")
        print(f"  {root}: {n} photos and videos", flush=True)
    return found


def main():
    if os.path.isfile(LOCK) and time.time() - os.path.getmtime(LOCK) < 6 * 3600:
        print("A sync is already running.")
        return
    open(LOCK, "w").write(str(os.getpid()))
    try:
        mark("LIST")
        old = load_inventory() if os.path.isfile(INVENTORY) else {}
        new = list_phone()
        if len(new) < 0.5 * len(old):
            raise RuntimeError(f"phone lists only {len(new)} files, before it was {len(old)}: not trusted, nothing changed")
        added = [p for p in new if p not in old]
        gone = [p for p in old if p not in new]
        print(f"On the phone: {len(new)} files. New: {len(added)} ({sum(new[p][0] for p in added) / 1e9:.2f} GB). No longer there: {len(gone)}.", flush=True)
        tmp = INVENTORY + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for p, (b, mt) in new.items():
                f.write(f"{b}|{mt}|{p}\n")
        if os.path.isfile(INVENTORY):
            os.replace(INVENTORY, os.path.join(DATA, "phone_inventory_prev.txt"))
        os.replace(tmp, INVENTORY)
        # files you removed on the phone yourself (not with this tool) leave the lists; the laptop copy stays
        con = db()
        on = {r["phone_path"]: r["id"] for r in con.execute("SELECT id, phone_path FROM files WHERE state IN ('on_phone','marked')")}
        vanished = [i for p, i in on.items() if p not in new]
        if vanished:
            con.executemany("UPDATE files SET state='deleted' WHERE id=?", [(i,) for i in vanished])
            con.executemany("INSERT INTO actions(file_id, action) VALUES(?, 'gone_from_phone')", [(i,) for i in vanished])
            con.commit()
            print(f"{len(vanished)} files were removed on the phone itself; moved to Deleted.", flush=True)
        con.close()

        steps = [("COPY", ["pull.py", "--all"]), ("SCAN", ["scan.py"]), ("ANALYSE", ["analyze.py"]), ("LEARN", ["learn.py"])]
        for stage, args in steps:
            mark(stage)
            if stage == "COPY":
                open(COPY, "w").close()
            try:
                with open(LOG, "a", encoding="utf-8") as f:
                    r = subprocess.run([sys.executable, *args], cwd=BASE, stdout=f, stderr=subprocess.STDOUT)
            finally:
                if os.path.isfile(COPY):
                    os.remove(COPY)
            if r.returncode != 0:
                raise RuntimeError(f"{args[0]} stopped with an error, see data/full_run.log")
        mark("DONE")
    except Exception as e:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"SYNC ERROR {e}\n")
        mark("FAILED")
        print("Sync failed:", e)
    finally:
        os.remove(LOCK)


if __name__ == "__main__":
    main()
