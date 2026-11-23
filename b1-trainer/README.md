# Deutsch-Prüfungstrainer (B1)

Practise for a German B1 exam (Goethe-Zertifikat B1, telc Deutsch B1 / Zertifikat Deutsch) in your browser:
reading, Sprachbausteine, listening with the real audio, and writing and speaking with feedback from Claude.
Everything stays on your computer.

## Start

1. Run `serve.ps1` (PowerShell) and open http://localhost:8770.
2. A 32-item grammar drill is included, so you can start right away.

## Get real practice tests

- **Official free tests:** run `get-official-papers.ps1`. It downloads the Goethe-Institut B1 Modellsatz 1 and
  Übungssatz 2 (with listening audio) and the telc Deutsch B1 Übungstest 1. Then ask Claude Code:
  "Importiere die heruntergeladenen Prüfungen". Claude turns them into trainer papers.
- **Your own tests:** give Claude Code a **link**, a **PDF** or **photos/scans** of a practice test and say
  "Importiere diese Prüfung in den B1-Trainer". Claude reads the tasks and solutions, adds the audio if there
  is any, and the test appears on the start page.
- Already have a `paper.json`? Load it with the file picker on the start page.

How Claude imports a test, and the file format: [IMPORT.md](IMPORT.md).

## How it works

- Reading, Sprachbausteine and listening are checked automatically, with the explanation where the solutions
  have one. Your answers and best scores are saved in the browser.
- Writing and speaking: write your text (for speaking, what you said, for example dictated with Win + H), then
  "Für Claude zur Bewertung kopieren" and paste it into Claude for feedback in the exam's criteria.

Imported tests stay in `papers/` on your computer and are not uploaded: they are free to use for practice,
not to republish.
