# Mohit's projects

Small tools built with Claude Code. Pick one:

| # | Project | What it does | Needs |
|---|---|---|---|
| 1 | [Photo cleaner](photo-cleaner/) | Copies your Android phone's photos and videos to your PC, finds duplicates, blurry shots, screenshots and big videos, and lets you review and delete or compress them in a local web page. | Windows PC, Android phone + USB cable, Python, about 1 GB of disk for tools |
| 2 | [Router speedup](router-speedup/) | A guided check of your home Wi-Fi: measure speed and ping, find a better Wi-Fi channel, check the line quality, then measure again. | Claude Code with a browser tool, access to your router's admin page |
| 3 | [Itinerary maker](itinerary-maker/) | Turns your booking confirmations into one friendly trip page: to-do list, day-by-day cards, links and spend. | Claude (Code or claude.ai) and your booking documents |
| 4 | [Deutsch-Prüfungstrainer (B1)](b1-trainer/) | Practise for Goethe or telc German B1 in the browser: reading, cloze, listening with audio, writing and speaking feedback via Claude. Downloads the free official practice tests; import your own from a link, PDF or photo. | Windows (PowerShell), a browser; Claude Code to import tests |
| 5 | [TV home screen (cleanyourtv fork)](https://github.com/MundaneMohit/cleanyourtv/tree/mohit-tv-updates) | A clean Android TV launcher. My branch adds weather under the clock, show tiles, outline status icons and the Inter font. Separate public repo, based on [Gathin23/cleanyourtv](https://github.com/Gathin23/cleanyourtv). | Android TV, adb; see that repo's README |

## How to use

Easiest: open Claude Code in any empty folder and say

> Clone https://github.com/MundaneMohit/mohit-claude-projects and help me set up the photo cleaner.

(or "...and run the router speedup check"). Claude reads `CLAUDE.md` and the project's guide and walks you through it.

Doing it by hand: open the project folder and follow its `SETUP.md` or `GUIDE.md`.

Nothing here sends your photos or network data anywhere. Everything runs on your own computer.
