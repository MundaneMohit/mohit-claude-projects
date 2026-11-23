# How to build a trip itinerary page (Egypt / Turkey style)

One self-contained HTML page per trip: hero scene, to-do panel, links, day-by-day cards, spend table. Published as a claude.ai artifact, private until shared.

## 1. Gather inputs

Upload or paste every booking document:

- Flight tickets (PNRs, times, baggage rules, fare conditions)
- Hotel receipts (dates, address, booking number, price)
- Anything else booked: transfers, tours, trains
- Passport nationality and residence status (for visa checks)

Prompt: "Make a new itinerary like `itinerary-maker/template.html` for [destination]" and attach the files.

## 2. Start from the template

- Read `template.html` (a made-up sample trip) or your own previous trip page, and reuse its layout and styles.
- Change only the content: title, hero scene (landmarks of the new destination), flags, days.
- Do not copy private links or booking numbers from the old trip.

## 3. Page structure

1. **Hero**: title, dates, route, nights, main booking number.
2. **To do before the trip**: visa, unbooked nights, missing transport, baggage, check-in.
3. **Bookings and links**: official sites, hotel map, airline or agent help.
4. **Day by day**: one card per date.
5. **Spend**: only amounts shown on documents.

## 4. Day card fields

| Field | Content |
|---|---|
| Date and route | `24 Dec Thu`, `Berlin → Istanbul` |
| Plan | One line |
| Meta | Flight numbers, local times, PNR, hotel address, booking number |
| Chips | Green = booked, orange = still to do |
| Note | One "Check:" line for the real risk of that day |

## 5. Rules that keep it honest

- **Only booked facts are stated as facts.** Ideas are labelled "Nothing booked. Ideas: ...".
- **Every gap is flagged.** Count nights against hotel bookings. Check each travel day has transport.
- **No invented prices.** If a document has no price, say so.
- **Times are local.** Mention time zone differences on multi-country flights.
- **Leave out** dates of birth and card numbers.
- **Be blunt in notes**: tight baggage limits, different airports on arrival and departure, New Year's Eve pricing, very early flights.

## 6. Checks worth running

- Visa rules for the passport, searched fresh (rules change).
- Transit rules for connections in a third country.
- Airport arrival time (3 hours for international) and how to get there at that hour.
- Arrival airport vs departure airport, especially in cities with two.
- Fare conditions (no rebooking on saver fares).

## 7. Publish and update

- Publish the HTML file as an artifact. The page is private until you share it.
- For changes, edit the same artifact (small text swaps), don't create a new one.
- The page contains booking numbers: share only with people on the trip.

## 8. Keep it current

When something gets booked, send the confirmation. Each unbooked chip becomes a booked chip, the to-do list shrinks, and the spend table gets a row.
