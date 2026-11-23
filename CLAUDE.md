# Instructions for Claude

This repo holds small personal tools. The person running you is a friend of the author, not the author.

1. Ask which project they want, unless they said it already: **photo cleaner**, **router speedup** or
   **itinerary maker**.
2. Follow that folder's guide step by step:
   - Photo cleaner: `photo-cleaner/SETUP.md`
   - Router speedup: `router-speedup/GUIDE.md`
   - B1 trainer: `b1-trainer/README.md`; to add a test (URL, PDF, image, or the official downloads) follow
     `b1-trainer/IMPORT.md`. Never commit imported tests (copyright).
   - Itinerary maker: `itinerary-maker/GUIDE.md`, starting from `itinerary-maker/template.html`. Never commit
     a real trip page: it holds booking numbers.
3. Explain each step in plain words before you run it. The person may not be technical.
4. Ask before anything that deletes, changes settings or installs software. Never delete photos or change
   router settings without a clear "yes" from the person in this conversation.
5. Keep the person's data local. Do not upload photos, logs or router details anywhere, and do not commit
   them to this repo. `.gitignore` already keeps `data/`, `models/` and `bin/` out.
6. If a step fails, say what failed and what you tried. Do not work around a safety rule.
