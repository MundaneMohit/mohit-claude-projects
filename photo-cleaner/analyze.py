"""Understand what is in each photo. Runs fully on this computer; nothing is uploaded.

  python analyze.py          # new photos only, then regroup faces

1. Content type (meme, text image, screenshot, document, people, food, scenery, object) from a CLIP
   image embedding compared with short text descriptions. The embedding is stored for swipe learning.
2. Faces: find them (YuNet), fingerprint them (SFace), group fingerprints into people.
3. A person marked "keep" protects every photo they appear in from the review lists.
"""
import os, sys

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps
from tokenizers import Tokenizer

from common import BASE, DATA, THUMBS, apply_protection, db, local_path

M = os.path.join(BASE, "models")
FACES = os.path.join(DATA, "faces")
os.makedirs(FACES, exist_ok=True)
Image.MAX_IMAGE_PIXELS = None

CLASSES = {
    "meme": ["a meme with a caption", "a funny internet meme", "a cartoon or comic with text"],
    "text": ["an image of a quote or a message written on a plain background", "a forwarded greeting card image saying good morning",
             "a poster or flyer with a lot of text", "an invitation card"],
    "screenshot": ["a screenshot of a phone app", "a screenshot of a chat conversation", "a screenshot of a website"],
    "document": ["a photo of a paper document", "a photo of a receipt or invoice", "a photo of an ID card or passport", "a scanned form"],
    "people": ["a photo of a person", "a selfie", "a group photo of family or friends", "a photo of a child"],
    "food": ["a photo of food or a meal", "a photo of a drink"],
    "scenery": ["a photo of a landscape or nature", "a photo of a city street or building", "a photo of a room interior"],
    "object": ["a photo of a product", "a photo of an everyday object", "a photo of a car or vehicle"],
}
# The face detector misses babies, side-on and far-away people. This second check asks the content model
# "is there a person in this picture?" and is what keeps such photos out of the "no people" list.
HAS_PEOPLE = ["a photo of a baby", "a photo of a baby lying down", "a photo of a child", "a photo of a person", "a close-up photo of a face",
              "a selfie", "a group photo of people", "a photo of a man", "a photo of a woman", "a photo of a family", "a person seen from the side"]
NO_PEOPLE = ["a photo of food", "a photo of a meal on a plate", "a photo of an object", "a photo of a product", "a photo of a building",
             "a photo of a landscape", "a photo of a street", "a photo of a room with furniture", "a photo of clothes", "a photo of jewellery",
             "a photo of a car", "a photo of an animal", "a photo of a toy", "a photo of hands", "a photo of feet", "a photo of a screen",
             "a photo of a document"]
PEOPLE_P = 0.3     # checked by eye on 2,900 photos: below 0.3 no people at all, 0.3-0.5 mostly small or distant people
FACE_SCORE, FACE_MIN_PX = 0.85, 40
SAME_PERSON, MERGE_PEOPLE = 0.45, 0.75   # on 38,966 faces: 0.60 chained families into one blob; real splits of one person sit at 0.80+


class Clip:
    MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
    STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

    def __init__(self):
        self.vis = ort.InferenceSession(os.path.join(M, "clip_vision.onnx"), providers=["CPUExecutionProvider"])
        txt = ort.InferenceSession(os.path.join(M, "clip_text.onnx"), providers=["CPUExecutionProvider"])
        tok = Tokenizer.from_file(os.path.join(M, "clip_tokenizer.json"))
        rows = []
        for prompts in CLASSES.values():
            vs = []
            for p in prompts:
                ids = np.array([tok.encode(p).ids], dtype=np.int64)
                v = txt.run(None, {"input_ids": ids})[0][0]
                vs.append(v / np.linalg.norm(v))
            v = np.mean(vs, axis=0)
            rows.append(v / np.linalg.norm(v))
        self.text = np.stack(rows)
        self.names = list(CLASSES)

    def prep(self, im):
        im = im.convert("RGB")
        s = 224 / min(im.size)
        im = im.resize((max(224, round(im.width * s)), max(224, round(im.height * s))), Image.BICUBIC)
        l, t = (im.width - 224) // 2, (im.height - 224) // 2
        a = np.asarray(im.crop((l, t, l + 224, t + 224)), dtype=np.float32) / 255
        return ((a - self.MEAN) / self.STD).transpose(2, 0, 1)

    def embed(self, images):
        v = self.vis.run(None, {"pixel_values": np.stack([self.prep(i) for i in images])})[0]
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def classify(self, v):
        logits = 100 * v @ self.text.T
        p = np.exp(logits - logits.max(axis=1, keepdims=True))
        p /= p.sum(axis=1, keepdims=True)
        return [(self.names[int(i)], float(row[i])) for row, i in zip(p, p.argmax(axis=1))]


class Faces:
    def __init__(self):
        self.det = cv2.FaceDetectorYN.create(os.path.join(M, "yunet.onnx"), "", (320, 320), FACE_SCORE, 0.3, 50)
        self.rec = cv2.FaceRecognizerSF.create(os.path.join(M, "sface.onnx"), "")

    def find(self, path):
        with Image.open(path) as im:
            im.draft("RGB", (1600, 1600))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1280, 1280))
            bgr = np.asarray(im)[:, :, ::-1].copy()
        H, W = bgr.shape[:2]
        self.det.setInputSize((W, H))
        _, found = self.det.detect(bgr)
        out = []
        for f in (found if found is not None else [])[:12]:
            x, y, w, h = f[:4]
            if min(w, h) < FACE_MIN_PX:
                continue
            crop = self.rec.alignCrop(bgr, f)
            v = self.rec.feature(crop)[0]
            out.append({"box": (x / W, y / H, w / W, h / H), "score": float(f[-1]), "vec": v / np.linalg.norm(v), "crop": crop})
        return out


def analyse_new(con):
    todo = con.execute("""SELECT id, phone_path FROM files WHERE kind='photo' AND error IS NULL AND state!='deleted'
                          AND id NOT IN (SELECT file_id FROM embeds)""").fetchall()
    if not todo:
        return
    print(f"Analysing {len(todo)} photos...", flush=True)
    clip, faces = Clip(), Faces()
    for i in range(0, len(todo), 16):
        chunk = todo[i:i + 16]
        thumbs = [Image.open(os.path.join(THUMBS, f"{r['id']}.jpg")) for r in chunk]
        vecs = clip.embed(thumbs)
        for r, v, (cls, conf) in zip(chunk, vecs, clip.classify(vecs)):
            try:
                found = faces.find(local_path(r["phone_path"]))
            except Exception:
                found = []
            for f in found:
                cur = con.execute("INSERT INTO faces(file_id,x,y,w,h,score,vec) VALUES(?,?,?,?,?,?,?)",
                                  (r["id"], *map(float, f["box"]), f["score"], f["vec"].astype(np.float32).tobytes()))
                cv2.imwrite(os.path.join(FACES, f"{cur.lastrowid}.jpg"), f["crop"])
            con.execute("INSERT OR REPLACE INTO embeds(file_id, vec) VALUES(?,?)", (r["id"], v.astype(np.float16).tobytes()))
            con.execute("UPDATE files SET cls=?, cls_conf=?, nfaces=? WHERE id=?", (cls, conf, len(found), r["id"]))
        con.commit()
        print(f"PROGRESS {min(i + 16, len(todo))} {len(todo)}", flush=True)


def cluster_faces(V, quality, t_join=SAME_PERSON, t_merge=MERGE_PEOPLE):
    """Group face fingerprints into people.
    Each face joins the existing person whose AVERAGE face it matches best, or starts a new person.
    Comparing with the average (not with any single face) stops look-alike chains from gluing
    different people together, which is what happened with plain linking at a few thousand faces."""
    order = np.argsort(-quality)                     # clearest faces first: they make the best starting points
    n = 0
    sums = np.zeros((len(V), V.shape[1]), np.float32)
    C = np.zeros_like(sums)
    lab = np.full(len(V), -1)
    for i in order:
        v = V[i]
        if n:
            sim = C[:n] @ v
            k = int(sim.argmax())
            if sim[k] >= t_join:
                sums[k] += v
                C[k] = sums[k] / np.linalg.norm(sums[k])
                lab[i] = k
                continue
        sums[n] = v
        C[n] = v
        lab[i] = n
        n += 1
    parent = list(range(n))                          # then merge people whose average faces are very close

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    S = C[:n] @ C[:n].T
    for a, b in zip(*np.nonzero(S >= t_merge)):
        if a < b:
            parent[find(int(b))] = find(int(a))
    return np.array([find(int(l)) for l in lab])


BIG_PERSON, MERGE_BIG, ATTACH_SMALL = 10, 0.65, 0.62


def merge_people(V, lab):
    """Second pass. People with 10+ faces merge when their AVERAGE faces match (>= 0.65, average re-computed
    after each merge). Small groups then join the nearest big person if they match >= 0.62.
    Checked by eye: 0.60 or lower glued unrelated people into one blob."""
    lab = lab.copy()
    ks, n = np.unique(lab, return_counts=True)
    members = {int(k): np.nonzero(lab == k)[0] for k, c in zip(ks, n) if c >= BIG_PERSON}
    if len(members) < 2:
        return lab
    def cent(idx):
        s = V[idx].sum(0)
        return s / np.linalg.norm(s)
    C = {k: cent(m) for k, m in members.items()}
    while len(members) > 1:
        keys = list(members)
        M = np.stack([C[k] for k in keys])
        S = M @ M.T
        np.fill_diagonal(S, -1)
        i, j = np.unravel_index(S.argmax(), S.shape)
        if S[i, j] < MERGE_BIG:
            break
        x, y = keys[i], keys[j]
        members[x] = np.concatenate([members[x], members.pop(y)])
        C[x] = cent(members[x])
        C.pop(y)
    out = lab.copy()
    for k, m in members.items():
        out[m] = k
    keys = list(members)
    M = np.stack([C[k] for k in keys])
    for k, c in zip(ks, n):
        if c < BIG_PERSON:
            m = np.nonzero(lab == k)[0]
            sim = M @ cent(m)
            j = int(sim.argmax())
            if sim[j] >= ATTACH_SMALL:
                out[m] = keys[j]
    return out


def group_people(con):
    rows = con.execute("SELECT id, vec, w, score FROM faces ORDER BY id").fetchall()
    if not rows:
        return
    V = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
    lab = merge_people(V, cluster_faces(V, np.array([r["w"] * r["score"] for r in rows])))
    groups = {}
    for r, l in zip(rows, lab):
        groups.setdefault(int(l), []).append(r["id"])
    # faces.keep is only ever set by you pressing Keep. It is never spread to other faces here, so a
    # wrong merge can not silently mark strangers as kept. A person counts as kept if any face is.
    con.execute("UPDATE faces SET person=NULL")
    for pid, members in enumerate(sorted(groups.values(), key=len, reverse=True), 1):
        con.executemany("UPDATE faces SET person=? WHERE id=?", [(pid, m) for m in members])
    con.commit()
    apply_protection(con)
    sizes = sorted((len(m) for m in groups.values()), reverse=True)
    print(f"{len(rows)} faces -> {len(groups)} people; biggest groups: {sizes[:10]}; seen once: {sum(1 for s in sizes if s == 1)}")


def people_scores(con, only_missing=True):
    """people_p = how sure the content model is that a person is in the photo (0..1), from the stored picture fingerprints."""
    rows = con.execute("SELECT f.id, e.vec FROM files f JOIN embeds e ON e.file_id=f.id" + (" WHERE f.people_p IS NULL" if only_missing else "")).fetchall()
    if not rows:
        return
    txt = ort.InferenceSession(os.path.join(M, "clip_text.onnx"), providers=["CPUExecutionProvider"])
    tok = Tokenizer.from_file(os.path.join(M, "clip_tokenizer.json"))
    T = []
    for p in HAS_PEOPLE + NO_PEOPLE:
        v = txt.run(None, {"input_ids": np.array([tok.encode(p).ids], dtype=np.int64)})[0][0]
        T.append(v / np.linalg.norm(v))
    T = np.stack(T)
    for i in range(0, len(rows), 5000):
        chunk = rows[i:i + 5000]
        E = np.stack([np.frombuffer(r["vec"], dtype=np.float16).astype(np.float32) for r in chunk])
        L = 100 * E @ T.T
        P = np.exp(L - L.max(1, keepdims=True))
        P /= P.sum(1, keepdims=True)
        ps = P[:, :len(HAS_PEOPLE)].sum(1)
        con.executemany("UPDATE files SET people_p=? WHERE id=?", [(float(p), r["id"]) for p, r in zip(ps, chunk)])
    con.commit()
    print(f"people check: scored {len(rows)} photos")


if __name__ == "__main__":
    con = db()
    analyse_new(con)
    people_scores(con)
    group_people(con)
    print("--- content types (source: count)")
    for r in con.execute("SELECT cls, source, COUNT(*) c FROM files WHERE kind='photo' GROUP BY cls, source ORDER BY cls, c DESC"):
        print(f"  {r['cls'] or '-':11} {r['source']:10} {r['c']}")
    print("--- photos with faces:", con.execute("SELECT COUNT(*) FROM files WHERE nfaces>0").fetchone()[0])
