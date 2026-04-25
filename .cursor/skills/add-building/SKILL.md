---
name: add-building
description: Add a new building to the Alewife dashboard catalog given a Google Maps URL and/or an apartments.com listing URL. Use when the user pastes one of those URLs (or a maps.app.goo.gl short URL) and asks to register, add, onboard, or "put this on the map". Extracts lat/lng, proposes a slug, appends entries to buildings_seed.json and scrape_targets.json, runs the seed + refresh-all pipeline, then verifies the building is live in /api/buildings.
---

# Add a building to the Alewife catalog

End-to-end workflow for onboarding a new apartment building into the local Alewife dashboard from a Google Maps link and/or an apartments.com URL. Covers URL parsing, JSON edits, re-seeding, routing + scraping, and verification.

## Inputs the user typically gives

- A **Google Maps URL** — one of:
  - Short: `https://maps.app.goo.gl/<id>`
  - Long: `https://www.google.com/maps/place/<name>/@42.4154,-71.1565,17z/...`
  - Bare coords: `https://maps.google.com/?q=42.4154,-71.1565`
- An **apartments.com listing URL** — `https://www.apartments.com/<slug>/<id>/`
  - When provided, this URL also seeds the `overview` + `amenities` fields (see Phase 3.1).
- Optional: building name, neighborhood, Google `place_id`, seed rent values

## Files the workflow touches

Read `App V1 Dynamic/RUN_LOCALLY.md` → "Maintaining the catalog" for the human-facing version and the full field reference. The skill operationalizes that same flow.

| File | Edit required? |
| --- | --- |
| `App V1 Dynamic/backend/app/seed/buildings_seed.json` | Yes — append one new object |
| `App V1 Dynamic/backend/app/seed/scrape_targets.json` | Yes if the user supplied an apartments.com URL or `place_id` |
| SQLite DB (`backend/alewife-data/alewife.db`) | No — `make seed` handles the upsert |

Never hand-edit the DB during an add; the seed loader is idempotent and handles it.

## Workflow checklist

Copy this into the chat before you start and tick as you go:

```
- [ ] Phase 1: Preflight (container running, no slug conflict)
- [ ] Phase 2: Extract coordinates + address from the Google Maps URL
- [ ] Phase 3: Draft overview + amenities, propose slug, confirm all fields
- [ ] Phase 4: Append entry to buildings_seed.json
- [ ] Phase 5: Append entry to scrape_targets.json (if scrape URLs provided)
- [ ] Phase 6: Run `./make.ps1 seed` and verify inserted=1
- [ ] Phase 7: Run `./make.ps1 refresh-all` and verify preflight counts
- [ ] Phase 8: Validate via /api/buildings and tell the user the dashboard URL
```

---

## Phase 1 — Preflight

1. Confirm the container is up:

   ```powershell
   docker compose -f "App V1 Dynamic/docker-compose.local.yml" ps
   ```

   If it isn't, tell the user to run `./make.ps1 up-local` before proceeding. Do not auto-start it.

2. Confirm no slug conflict. Read `App V1 Dynamic/backend/app/seed/buildings_seed.json` and grep for the slug you're about to propose; if it already exists, this is an edit, not an add — stop and offer to switch to edit mode.

## Phase 2 — Extract coordinates

### Long Google Maps URL

Parse the `@lat,lng,zoom` segment with this regex: `@(-?\d+\.\d+),(-?\d+\.\d+)`.
Keep at least 5 decimal places. Use `!3d<lat>!4d<lng>` as a secondary source if `@` isn't present.

### Short Google Maps URL (`maps.app.goo.gl/...`)

Expand the redirect before parsing. PowerShell one-liner:

```powershell
try {
  Invoke-WebRequest -Uri "<short-url>" -MaximumRedirection 0 -ErrorAction Stop
} catch {
  $_.Exception.Response.Headers.Location.AbsoluteUri
}
```

Python fallback (if PowerShell Invoke-WebRequest behaves oddly):

```python
import httpx
r = httpx.head("<short-url>", follow_redirects=False)
print(r.headers.get("location"))
```

Then parse the resulting long URL as above.

### Bare coords URL

`?q=<lat>,<lng>` — parse directly.

### No coords in the URL

Tell the user exactly what failed and ask them to paste `lat, lng` directly. Never guess coordinates.

## Phase 3 — Synthesize content, propose slug, confirm

This phase has three sub-steps: draft `overview` + `amenities` from the apartments.com listing (3.1), pick the slug (3.2), then echo everything back to the user for approval (3.3).

### 3.1 — Draft `overview` and `amenities` from the apartments.com listing

Skip this sub-step entirely and leave `overview=""` / `amenities=[]` if:

- No `apartments.com` URL was provided, **or**
- The WebFetch in step 1 below fails or returns a bot wall.

**1. Fetch the listing as markdown:**

Use the `WebFetch` tool on the `apartments.com` URL. Read the returned markdown.

If the content looks like an access-denied / verification page (keywords: `Access Denied`, `Please verify`, `Checking your browser`, `robot`, total length < 500 chars), stop drafting and skip to 3.2 — tell the user in Phase 3.3 that auto-drafting failed and ask them to paste the description manually.

**2. Extract raw signals:**

From the markdown, pull:

- **Description text** — the prose under headings like `About`, `Description`, or `Property Description`. Usually 200-600 chars of marketing copy.
- **Amenities list** — items under headings like `Community Amenities`, `Apartment Features`, `Amenities`. Expect 10-30 bullets.

**3. Synthesize the `overview` (1-2 sentences, ≤ 220 chars):**

Rewrite the description in the house voice. Reference existing seed entries in `App V1 Dynamic/backend/app/seed/buildings_seed.json` for tone: short, declarative, trade-off-aware where possible. Examples already in the catalog:

- *"Modern building, strong management, excellent bike trail access. Some thin-ceiling noise complaints. Good value vs. peers."*
- *"LEED Gold certified. Fire alarm issues resolved Jan 2026. Amenities showing age vs. newer buildings."*

Rules:

- No marketing adjectives ("luxurious", "stunning", "vibrant", "exceptional"). Strip them.
- Lead with the one or two things that differentiate this building.
- If the listing only gave you generic copy, state facts only ("Mid-rise at 123 Example Ave. Gym, pool, in-unit laundry.") — do **not** invent trade-offs you can't source.

**4. Normalize the `amenities` (5-8 items):**

Collapse the raw list to 5-8 short noun phrases matching the house vocabulary. Preferred labels (reuse when applicable):

| Raw apartments.com label | Use |
| --- | --- |
| Washer/Dryer In-Unit, W/D In Home | `W/D in unit` |
| Washer/Dryer Hookups | `W/D hookups` |
| Swimming Pool, Pool | `Pool` |
| Rooftop Pool | `Rooftop Pool` |
| Fitness Center, Gym | `Gym` |
| Concierge, 24-Hour Concierge | `Concierge` |
| Courtyard | `Courtyard` |
| Parking Garage, Covered Parking | `Garage` |
| Heated Garage | `Heated Garage` |
| Bike Storage, Bicycle Storage | `Bike Access` |
| Rooftop Deck, Sundeck | `Rooftop Deck` |
| Media Room, Theater Room | `Theater` |
| Outdoor Grills, BBQ Area | `BBQ` |
| Pet Friendly | `Pet Friendly` |
| Dog Park, Bark Park | `Bark Park` |
| Pet Spa, Pet Washing Station | `Pet Spa` |
| Co-working Space, Business Center | `Co-working` |

For amenities outside this vocabulary, prefer the shortest natural phrasing already used by a neighboring building in the seed (grep the file for precedent). Genuinely unique amenities (e.g. `Bowling Alley`, `Minuteman Bikeway`, `LEED Gold`, `Shuttle to T`) get their own label.

Selection heuristic — keep these 8 buckets, in priority order:

1. Laundry (`W/D in unit` / `W/D hookups`)
2. Pool (any kind)
3. Gym
4. Parking
5. One differentiator (theater, bowling, rooftop deck, etc.)
6. Pet amenity if present
7. Outdoor (courtyard, BBQ, deck)
8. Certifications / programs / unique geography (LEED, Bilt, Minuteman Bikeway)

Drop the long tail (e.g. "High Ceilings", "Stainless Appliances", "Dishwasher") — they're generic to every mid-rise and don't inform a decision.

**5. Confidence gate:**

Mark the draft **high-confidence** when both:

- Raw description had ≥ 100 chars of usable prose, **and**
- Normalized amenity list ended up with ≥ 3 items.

Otherwise mark it **low-confidence** and show the user the draft in 3.3 with an explicit "Does this read OK, or do you want to rewrite it?" question.

### 3.2 — Pick the slug

Slug rules (enforce all):

- Lowercase, hyphenated, no spaces or underscores.
- Globally unique within `buildings_seed.json`.
- Ideally includes the neighborhood if the building name is generic (e.g. `the-commons-arlington`, not `the-commons`).

### 3.3 — Confirm with the user

Before editing any file, echo back everything at once:

```
Proposing:
  slug:     <proposed-slug>
  name:     <parsed name>
  nbhd:     <neighborhood guess>
  address:  <street address>
  lat:      42.xxxxx
  lng:      -71.xxxxx
  apartments_com_url: <url or null>
  google_place_id:    <id or null>

Draft content (auto-generated from apartments.com, <high|low>-confidence):
  overview:   "<drafted sentence(s)>"
  amenities:  ["W/D in unit", "Pool", "Gym", ...]

<if high-confidence:>
  OK to proceed? Reply "yes", or paste a replacement overview / amenity list to override.
<if low-confidence:>
  The auto-draft is thin. Prefer to provide your own overview? Paste it below, or reply "use draft" to proceed with what's shown.
<if skipped entirely:>
  overview and amenities will be left empty — edit buildings_seed.json afterwards to fill them in.
  OK to proceed? Reply "yes" or correct anything above.
```

Wait for explicit confirmation before continuing. If the user provides replacement text or amenity items, use those verbatim in Phase 4.

## Phase 4 — Append to `buildings_seed.json`

The file is a top-level JSON array. Append a new object before the closing `]`. The minimum viable entry with the drafts from Phase 3.1:

```json
{
  "slug": "<slug>",
  "name": "<name>",
  "nbhd": "<nbhd>",
  "address": "<address>",
  "lat": <lat>,
  "lng": <lng>,
  "overview": "<drafted or user-supplied sentence(s) — empty string if skipped>",
  "amenities": ["W/D in unit", "Pool", "Gym"]
}
```

Include any optional fields the user volunteered: `rating`, `rc`, `studio`, `oneBR`, `twoBR`, `studioSrc`, `oneBRSrc`, `twoBRSrc`, `walk`, `drive`, `website`, `wlabel`.

**Formatting rules (do not violate):**

- Add a comma to the previous object's closing `}`.
- 2-space indentation; match the file's existing style.
- Preserve trailing newline at EOF.
- After editing, parse the file to confirm it's valid JSON. Never ship broken JSON:

  ```powershell
  Get-Content "App V1 Dynamic/backend/app/seed/buildings_seed.json" | ConvertFrom-Json | Out-Null
  ```

  If that command errors, restore the file from git and try again.

## Phase 5 — Append to `scrape_targets.json`

If the user gave an `apartments.com` URL or a Google `place_id`, add an entry under `"buildings"`:

```json
"<slug>": {
  "apartments_com_url": "<url or null>",
  "google_place_id": "<place_id or null>"
}
```

Put `null` (not an empty string) in any field the user didn't supply. The scrapers skip `null` entries; empty strings cause parse errors.

Validate JSON afterwards the same way as in Phase 4.

## Phase 6 — Re-seed

```powershell
./make.ps1 seed
```

Expected output:

```
Seed load complete: inserted=1 updated=0
```

If `inserted=0 updated=0`, the new slug is either already present (edit, not add) or the JSON didn't serialize what you intended — re-open the file and check the new object.

## Phase 7 — Refresh ORS + scrapers

```powershell
./make.ps1 refresh-all
```

Check the preflight line at the top:

```
buildings: total=<N+1> with_apartments_com_url=<...> with_google_place_id=<...>
```

- `total` must be exactly one higher than before the add.
- `with_apartments_com_url` should increment if you populated that field.
- `with_google_place_id` should increment if you populated that field.

If the scrapers print `attempted=0` but you populated URLs, the sidecar didn't merge — re-run `./make.ps1 seed` and try again.

## Phase 8 — Validate

Run these three checks in order. All three must pass before telling the user "done":

1. Building count went up:

   ```powershell
   (Invoke-WebRequest http://localhost:8000/api/health).Content | ConvertFrom-Json | Select-Object building_count
   ```

2. New slug is in `/api/buildings`:

   ```powershell
   (Invoke-WebRequest http://localhost:8000/api/buildings).Content | ConvertFrom-Json |
     Where-Object slug -eq "<slug>"
   ```

3. Travel times were computed (the routing step picked up the new building):

   ```powershell
   (Invoke-WebRequest http://localhost:8000/api/buildings).Content | ConvertFrom-Json |
     Where-Object slug -eq "<slug>" |
     Select-Object name, walk, drive
   ```

   `walk` and `drive` should be populated (not the seed defaults).

If any check fails, consult [reference.md](reference.md) for recovery playbooks. Do not leave the catalog half-updated.

## Reporting back to the user

When all eight phases pass, respond with:

```
Added <name> (<slug>).
  buildings count: <old> → <new>
  overview:        <auto-drafted from apartments.com | user-supplied | left empty>
  amenities:       <auto-drafted (N items) | user-supplied | left empty>
  prices scraped:  <yes/no — attempted count from refresh output>
  ratings scraped: <yes/no — attempted count from refresh output>

Hard-reload http://localhost:8000/ to see the new pin at (<lat>, <lng>).
<if overview was auto-drafted:>
Tip: the overview is a first-draft from marketing copy. If you read reviews
and want to sharpen the trade-offs, edit buildings_seed.json and re-run
./make.ps1 seed.
```

If any scraper came back `failed`, include the failing slug and the log snippet.

## Failure modes and recovery

See [reference.md](reference.md) for:

- Slug conflicts and how to resolve.
- What to do if `Invoke-WebRequest -MaximumRedirection 0` doesn't surface the Location header.
- WebFetch hit a bot wall / returned thin content during Phase 3.1 synthesis.
- Draft overview read as marketing copy — how to rewrite cleanly.
- Rolling back a half-written JSON edit via `git checkout`.
- Using `git diff` to review your catalog edits before the re-seed.
