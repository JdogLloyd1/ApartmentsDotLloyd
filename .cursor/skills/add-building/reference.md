# `add-building` — failure modes and recovery

Read this only when a phase in `SKILL.md` fails. Each section is self-contained.

## Slug already exists

The slug you proposed is already in `buildings_seed.json`. Two options:

1. **User wants to update the existing building** → switch to an edit workflow:
   - Locate the object with that slug.
   - Modify fields in place.
   - Run `./make.ps1 seed` — the loader upserts by slug, so `inserted=0 updated=1` is the success signal.
   - Skip the rest of add-building; no new scrape target is needed unless URLs changed.
2. **User actually has a second building with the same name** → append a disambiguator:
   - `the-commons` vs `the-commons-arlington`
   - `equity-north` vs `equity-north-at-alewife`
   - Propose the new slug and restart Phase 3 of `SKILL.md`.

## `Invoke-WebRequest -MaximumRedirection 0` doesn't show the Location header

The short URL may have already been resolved by a CDN cache, or PowerShell's auto-redirect swallowed it. Fallbacks in preference order:

1. `curl -I "<url>"` (git-bash or WSL) — the `location:` header prints directly.
2. Python `httpx`:

   ```python
   import httpx
   with httpx.Client(follow_redirects=True) as c:
       r = c.get("<url>")
   print(r.url)  # final URL
   ```

3. As a last resort, ask the user to open the short URL in a browser and paste the resulting long URL — never fabricate coordinates.

## I broke `buildings_seed.json`

Always recoverable via git:

```powershell
git diff -- "App V1 Dynamic/backend/app/seed/buildings_seed.json"
git checkout -- "App V1 Dynamic/backend/app/seed/buildings_seed.json"
```

Then redo Phase 4 carefully. The most common breakage is a missing comma after the previous object's closing `}`.

## I broke `scrape_targets.json`

Same playbook as above, scoped to the sidecar file:

```powershell
git checkout -- "App V1 Dynamic/backend/app/seed/scrape_targets.json"
```

## Phase 3.1 synthesis — WebFetch hit a bot wall

Symptoms: the markdown returned by WebFetch is < 500 chars, contains `Access Denied` / `Please verify` / `Checking your browser`, or has no recognizable amenities section.

Response:

1. Do **not** retry with a different URL-munging trick. apartments.com's bot wall is sticky per IP.
2. Leave `overview=""` and `amenities=[]` in the draft.
3. Tell the user: *"Auto-draft failed — the listing page returned a verification wall. You can paste a 1-2 sentence overview and 5-8 amenities now, or proceed with empties and edit `buildings_seed.json` later."*
4. If they paste replacements, use those verbatim. Do **not** rewrite them.
5. Continue the workflow from Phase 3.2 normally.

The recurring price/rating scrape uses Playwright and handles the bot wall for production refreshes — you do not need to replicate that logic for a one-time synthesis.

## Phase 3.1 synthesis — description parsed but reads like marketing copy

Symptoms: the drafted `overview` contains any of these — strip or rewrite:

- `luxurious`, `stunning`, `vibrant`, `exceptional`, `elevated`, `curated`, `thoughtfully designed`
- `Welcome to...`, `Discover...`, `Experience...`, `Nestled in...`
- Generic phrases with no differentiator: `modern amenities`, `premium finishes`, `urban living`

Rewrite rules:

- Lead with a concrete fact: building type (mid-rise, high-rise), distance to a landmark, or the single most unusual amenity.
- Keep trade-off phrasing when the source hints at one ("close to transit but smaller units", "newer building with fewer reviews").
- If the source is pure marketing with zero substance, write a factual two-liner and nothing more: *"Mid-rise at 123 Example Ave. Gym, pool, in-unit laundry."* Do not invent trade-offs.

Never ship a draft containing the marketing adjectives above. If you can't strip them without losing all content, downgrade to low-confidence and ask the user in Phase 3.3.

## Phase 3.1 synthesis — amenities list is too short

Symptoms: after normalization you have < 3 items.

Causes and fixes:

- The WebFetch truncated the amenities section. Re-read the markdown below the point where you extracted it — amenities often appear twice (Community Amenities + Apartment Features). Merge both.
- The listing is sparse (small building, limited features). In that case, 2-3 items is genuinely accurate; ship it as low-confidence and let the user expand.
- The listing is actually a multi-building portfolio page, not a single listing. The `apartments_com_url` is wrong — tell the user and ask for the correct leaf URL.

## Phase 3.1 synthesis — amenity labels drift from the house vocabulary

Symptoms: you wrote `Washer and Dryer In-Unit` instead of `W/D in unit`, or `Fitness Center` instead of `Gym`.

Fix: grep `App V1 Dynamic/backend/app/seed/buildings_seed.json` for the raw phrase and match whatever the majority of existing buildings use. If nothing matches, consult the vocabulary table in Phase 3.1 of `SKILL.md`. When in doubt, prefer the shorter label.

## `make seed` prints `inserted=0 updated=0`

Either:

- The slug already existed (this is actually an update; the loader returns `updated=1`, not `inserted=1`). Re-read the output — if it says `updated=1`, you're fine.
- The JSON parsed but your new object didn't actually land in the file. Run `git diff` to confirm.

## `make refresh-all` preflight shows `with_apartments_com_url=0`

The sidecar entry didn't merge into the DB. Causes:

- The slug in `scrape_targets.json` doesn't match the slug in `buildings_seed.json` exactly (watch for trailing spaces, underscores vs hyphens).
- `./make.ps1 seed` was not re-run after editing the sidecar. Re-seed, then re-run `refresh-all`.

## `make refresh-all` says `prices: attempted=1 succeeded=0 failed=1`

The scraper reached apartments.com but the listing URL is dead, region-blocked, or renders differently. Check:

- The URL opens in an incognito window. Copy the canonical URL from the address bar after any redirects.
- The listing still exists — apartments.com occasionally delists buildings.
- Try the listing's parent directory; the scraper follows the canonical link inside the page.

Ask the user if they want to leave the scrape target `null` for now so the seed fallback value is used.

## Dashboard doesn't show the new pin

Three possible causes:

1. Browser cache. Hard-reload (`Ctrl+F5`).
2. The `/api/buildings` response is cached for 5 min. Either wait, call `POST /api/refresh`, or bounce the container.
3. The lat/lng landed outside the map's initial bounds. Open DevTools and check the network response for the new slug.

## Rolling back the whole add

If the user decides mid-workflow they don't want the building:

```powershell
git checkout -- "App V1 Dynamic/backend/app/seed/buildings_seed.json" "App V1 Dynamic/backend/app/seed/scrape_targets.json"
./make.ps1 seed
```

The seed loader is upsert-only; to physically drop the row, switch to the `remove-building` skill.
