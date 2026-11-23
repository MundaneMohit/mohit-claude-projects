# Photo cleaner: setup and use

Copies an Android phone's photos and videos to the PC, sorts them (duplicates, near-duplicates, blurry,
screenshots, WhatsApp, big videos, people), and shows a local review page where the person decides what to
delete or compress. Deletes and compression on the phone happen only when the person clicks.

Written for Windows. Paths in `common.py` point to `.exe` files under `bin\`; on Mac or Linux, change `ADB`
and `EXIFTOOL` in `common.py` to the installed tools.

## Safety rules (for Claude)

- Never delete or replace anything on the phone yourself. Only the person clicks delete or compress in the page.
- To test a feature, use throwaway copies in `/sdcard/Download/_cleaner_test`, never real photos.
- `data\` holds the person's photos and database. Never upload it, never commit it.

## 1. Tools (one time)

| Tool | Where | Put it at |
|---|---|---|
| Python 3.10+ | python.org or `winget install Python.Python.3.12` | on PATH |
| Python packages | `pip install -r requirements.txt` | |
| adb (Android platform-tools) | developer.android.com/tools/releases/platform-tools (Windows zip) | `bin\platform-tools\adb.exe` |
| exiftool | exiftool.org (Windows 64-bit zip) | `bin\exiftool\exiftool-<version>_64\exiftool.exe`, then set the same folder name in `common.py` (`EXIFTOOL`) |
| ffmpeg + ffprobe | `winget install Gyan.FFmpeg` | on PATH |
| VLC (optional) | videolan.org | default install; used to play videos |

## 2. Models (one time, about 620 MB)

Create `models\` beside the scripts and download:

| File in `models\` | Source |
|---|---|
| `clip_vision.onnx` | Hugging Face `Xenova/clip-vit-base-patch32`, file `onnx/vision_model.onnx` |
| `clip_text.onnx` | same repo, file `onnx/text_model.onnx` |
| `clip_tokenizer.json` | same repo, file `tokenizer.json` |
| `yunet.onnx` | GitHub `opencv/opencv_zoo`, `models/face_detection_yunet/face_detection_yunet_2023mar.onnx` |
| `sface.onnx` | GitHub `opencv/opencv_zoo`, `models/face_recognition_sface/face_recognition_sface_2021dec.onnx` |

Rename each file to the name in the left column. Use the full (fp32) ONNX files, not the quantized ones.

## 3. Phone (one time)

1. Settings → About phone → Software information → tap **Build number** 7 times (developer mode).
2. Settings → Developer options → turn on **USB debugging**.
3. Samsung only: Settings → Security and privacy → turn **Auto Blocker** OFF (it blocks USB debugging).
4. Plug the phone in, accept the "Allow USB debugging" prompt on the phone.
5. Check: `bin\platform-tools\adb.exe devices` shows the phone as `device`.

## 4. Run (each time, in this folder)

| Step | Command | What it does |
|---|---|---|
| 1 | `python sync.py` | Lists the phone's photos and videos (DCIM, Pictures, Download, Movies, WhatsApp media), copies them to `data\mirror\`, then scans (sizes, dates, hashes, blur, duplicates), analyses (content classes, faces) and learns. Read-only on the phone. The first run can take hours for a full phone. |
| 2 | `python server.py` | Opens the review page at http://127.0.0.1:8765 (only this computer can reach it). |

Every step can be stopped and rerun; it continues where it stopped. Later, `sync.py` (or the page's
"Sync new files" button) picks up new photos. The single steps are `pull.py --all`, `scan.py`, `analyze.py`
and `learn.py` if one needs rerunning.

## 5. Review

In the page the person marks what to keep, delete or compress.

- **Delete is a real delete on the phone**, not a move to trash. It only happens for files that are unchanged
  on the phone and have a full copy in `data\mirror\`; others are skipped with a reason. Deleted files can be
  put back from that copy with Restore, so do not remove `data\` while you might want something back.
- **Compress** re-encodes big videos to HEVC and copies all metadata (dates, location) from the original.
