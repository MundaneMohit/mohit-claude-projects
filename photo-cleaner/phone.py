"""The only code that changes anything on the phone: delete and restore, both verified.

Delete: a file is removed only if (1) the phone copy still has the size and date we scanned and
(2) a byte-identical-size backup exists on this computer. The backup stays in data/mirror, so a
delete can be undone with restore(), which also puts the original modified date back.
"""
import os
from common import adb, db, local_path


def q(path):
    """Quote a path for the phone's shell."""
    return "'" + path.replace("'", "'\\''") + "'"


def connected():
    """True when the phone is plugged in, unlocked for USB debugging and answering."""
    try:
        return adb("get-state", timeout=10).stdout.strip() == "device"
    except Exception:
        return False


NOT_CONNECTED = ("The phone is not connected. Plug it in, unlock it, and check that USB debugging is still on "
                 "(Samsung Auto Blocker switches it off). Nothing was changed.")


def stat_many(paths):
    """phone path -> (bytes, mtime), or missing from the dict when the file is not there."""
    out = {}
    for i in range(0, len(paths), 40):
        chunk = paths[i:i + 40]
        r = adb("shell", "stat -c '%s|%Y|%n' " + " ".join(q(p) for p in chunk) + " 2>/dev/null")
        for line in r.stdout.splitlines():
            p = line.rstrip("\r").split("|", 2)
            if len(p) == 3 and p[0].isdigit():
                out[p[2]] = (int(p[0]), int(p[1]))
    return out


def delete(ids, progress=lambda done, total: None):
    con = db()
    rows = [con.execute("SELECT * FROM files WHERE id=?", (i,)).fetchone() for i in ids]
    rows = [r for r in rows if r and r["state"] != "deleted"]
    res = {"deleted": 0, "bytes": 0, "skipped": []}
    for i in range(0, len(rows), 40):
        chunk = rows[i:i + 40]
        on_phone = stat_many([r["phone_path"] for r in chunk])
        safe = []
        for r in chunk:
            lp = local_path(r["phone_path"])
            if on_phone.get(r["phone_path"]) != (r["bytes"], r["mtime"]):
                res["skipped"].append([r["name"], "changed or missing on the phone"])
            elif not os.path.isfile(lp) or os.path.getsize(lp) != r["bytes"]:
                res["skipped"].append([r["name"], "no backup on this computer"])
            else:
                safe.append(r)
        if safe:
            adb("shell", "rm -- " + " ".join(q(r["phone_path"]) for r in safe))
            still = stat_many([r["phone_path"] for r in safe])
            for r in safe:
                if r["phone_path"] in still:
                    res["skipped"].append([r["name"], "the phone refused the delete"])
                    continue
                con.execute("UPDATE files SET state='deleted' WHERE id=?", (r["id"],))
                con.execute("INSERT INTO actions(file_id, action, detail) VALUES(?,?,?)", (r["id"], "delete", r["phone_path"]))
                res["deleted"] += 1
                res["bytes"] += r["bytes"]
            con.commit()
        progress(min(i + 40, len(rows)), len(rows))
    return res


def restore(ids, progress=lambda done, total: None):
    """Put deleted files back from the backup, with the original modified date."""
    con = db()
    res = {"restored": 0, "skipped": []}
    for n, i in enumerate(ids, 1):
        r = con.execute("SELECT * FROM files WHERE id=? AND state='deleted'", (i,)).fetchone()
        if not r:
            continue
        lp = local_path(r["phone_path"])
        if not os.path.isfile(lp):
            res["skipped"].append([r["name"], "backup is gone"])
            continue
        adb("push", lp, r["phone_path"], timeout=3600)
        adb("shell", f"touch -m -d @{r['mtime']} {q(r['phone_path'])}")
        if stat_many([r["phone_path"]]).get(r["phone_path"]) == (r["bytes"], r["mtime"]):
            con.execute("UPDATE files SET state='on_phone' WHERE id=?", (i,))
            con.execute("INSERT INTO actions(file_id, action, detail) VALUES(?,?,?)", (i, "restore", r["phone_path"]))
            con.commit()
            res["restored"] += 1
        else:
            res["skipped"].append([r["name"], "size or date did not match after copying back"])
        progress(n, len(ids))
    return res
