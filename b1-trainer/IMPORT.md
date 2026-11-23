# Importing a practice test (for Claude)

The person gives you a practice test as a **URL**, a **PDF** or **images** (photos or scans), or asks you to
import the official papers that `get-official-papers.ps1` downloaded to `papers/_downloads/`.
Turn it into `papers/<id>/paper.json` in the format below, so the trainer page can show it.

## Steps

1. **Get the material.** URL: download it (PDF, ZIP or page). PDF: read it page by page. Images: read each one.
   Find the **solutions** (Lösungen) too, usually at the end of the PDF or in a separate file. Without
   solutions, ask the person whether to continue; then leave `answer` out and say the items cannot be checked.
2. **Pick an id**: lowercase, dashes, for example `goethe-b1-modellsatz-1`. Create `papers/<id>/`.
3. **Audio** (listening parts): put the file in the same folder (mp3, m4a or mp4 all play). If one file holds
   all listening parts, set `start`/`end` in seconds per task. Find the boundaries by listening cues in the
   transcript or with `ffmpeg -i file -af silencedetect=n=-35dB:d=2 -f null -` and check them.
4. **Write `paper.json`** (format below). Copy the task texts exactly; do not invent or shorten content.
   Keep the exam's own numbering (`n`).
5. **Check it**: every item has an `answer` that is one of its option keys; `[n]` markers in a gap text all have
   an item. Then run `build-index.ps1` and open the trainer (`serve.ps1`) to look at every section.
6. **Tell the person** what was imported, what is missing (for example no audio or no solutions), and that the
   file stays on their computer.

**Copyright:** official practice tests are free to download for personal practice, not to republish.
`papers/` is in `.gitignore` (except the grammar drill). Never commit an imported test.

## paper.json format

```json
{
  "id": "goethe-b1-modellsatz-1",
  "title": "Goethe-Zertifikat B1 – Modellsatz 1",
  "exam": "Goethe B1",
  "source": "Goethe-Institut, free practice material, goethe.de",
  "sections": [
    { "title": "Lesen", "minutes": 65, "tasks": [ ...tasks... ] }
  ]
}
```

Every task can have `title`, `instruction`, `text` (a reading passage) and `audio`
(`{"src": "hoeren.mp4", "start": 0, "end": 444}`, path relative to the paper folder).

| `type` | Use for | Fields |
|---|---|---|
| `choice` | multiple choice (a/b/c) | `items: [{ "n": 1, "q": "question", "text": "optional own passage", "options": {"a": "...", "b": "...", "c": "..."}, "answer": "b", "why": "optional explanation" }]` |
| `truefalse` | richtig / falsch | `items: [{ "n": 41, "statement": "...", "answer": true }]` |
| `match` | headings to texts, ads to people, statements to speakers | `options: {"a": "heading a", ...}`, `allowNone: true` if "0 / keine Anzeige" is allowed, `items: [{ "n": 1, "text": "the text or person", "answer": "c" }]` (use `"0"` for none) |
| `gap` | Sprachbausteine / cloze | `gapText: "Hallo Tom, ... [21] ... [22] ..."`, `items: [{ "n": 21, "options": {"a": "...", "b": "...", "c": "..."}, "answer": "a" }]`, or a shared word bank: `bank: {"a": "word", ...}` and items without `options` |
| `write` | Schreiben | `prompt`, `minWords`, optional `rubric` (how the exam grades it) |
| `speak` | Sprechen | `prompt`, optional `rubric` |

Writing and speaking cannot be marked automatically: the page has a button that copies the task, the
person's text and the rubric, ready to paste into Claude for feedback.
