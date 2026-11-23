"""Copy files from the phone to data/mirror, keeping the modified date. Read-only on the phone.

  python pull.py data/pull_list.txt      # one phone path per line
  python pull.py --all                   # everything in the inventory that is a photo or video

Already-copied files (same size and date) are skipped, so it can be stopped and restarted.
"""
import os, sys, time
from collections import defaultdict
from common import ADB, IMG, VID, adb, load_inventory, local_path

inv = load_inventory()
if sys.argv[1] == "--all":
    wanted = [p for p in inv if os.path.splitext(p)[1].lower() in IMG | VID]
else:
    wanted = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]


def ok(p):
    lp = local_path(p)
    if not os.path.isfile(lp) or p not in inv:
        return False
    st = os.stat(lp)
    return st.st_size == inv[p][0] and abs(int(st.st_mtime) - inv[p][1]) <= 2


todo = [p for p in wanted if not ok(p)]
total_b = sum(inv.get(p, (0, 0))[0] for p in todo)
print(f"{len(wanted)} wanted, {len(wanted) - len(todo)} already here, {len(todo)} to copy ({total_b / 1e9:.2f} GB)", flush=True)

by_dir = defaultdict(list)
for p in todo:
    by_dir[os.path.dirname(p)].append(p)

done_b, t0, failed = 0, time.time(), []
for d, paths in by_dir.items():
    dest = os.path.dirname(local_path(paths[0]))
    os.makedirs(dest, exist_ok=True)
    for i in range(0, len(paths), 40):
        chunk = paths[i:i + 40]
        r = adb("pull", "-a", *chunk, dest, timeout=3600)
        for p in chunk:
            if ok(p):
                done_b += inv[p][0]
            else:
                failed.append(p)
        el = time.time() - t0
        print(f"PROGRESS {done_b / 1e9:.2f}/{total_b / 1e9:.2f} GB  {done_b / 1e6 / max(el, 1):.0f} MB/s", flush=True)

print(f"Done in {time.time() - t0:.0f}s. Failed or mismatched: {len(failed)}")
for p in failed[:20]:
    print("  FAILED", p)
