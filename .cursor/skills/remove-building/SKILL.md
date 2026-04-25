---
name: remove-building
description: Remove a building from the Alewife dashboard catalog, cleanly deleting the row and every dependent travel_time, price_snapshot, and rating_snapshot record in SQLite, plus its entries in buildings_seed.json and scrape_targets.json. Use when the user asks to delete, remove, drop, or retire a building by slug, name, or Google Maps link, or says it should "come off the map".
---

# Remove a building from the Alewife catalog

End-to-end workflow for deleting an apartment building from the local Alewife dashboard. Covers target resolution, destructive SQLite cleanup with cascade order, JSON edits, and post-removal verification.

This is a **destructive** workflow. Never skip the confirmation gate in Phase 2.

## Scope of deletion

A single building touches five tables. All five must be cleaned:

| Table | Action |
| --- | --- |
| `building` | Delete the row matching `slug` |
| `travel_time` | Delete all rows where `building_id` = target |
| `price_snapshot` | Delete all rows where `building_id` = target |
| `rating_snapshot` | Delete all rows where `building_id` = target |
| `refresh_run` | No change — audit table, not per-building |
| `isochrone` | No change — keyed by anchor, not building |

Plus two JSON files:

| File | Action |
| --- | --- |
| `App V1 Dynamic/backend/app/seed/buildings_seed.json` | Remove the object with matching slug |
| `App V1 Dynamic/backend/app/seed/scrape_targets.json` | Remove the slug key under `buildings` if present |

If you only edit the JSON files without touching the DB, `make seed` is upsert-only — **it will not delete the row** and the building will still appear in `/api/buildings`. The SQLite step is mandatory.

## Workflow checklist

Copy this into the chat and tick as you go:

```
- [ ] Phase 1: Resolve target slug + preview impact
- [ ] Phase 2: User confirmation gate (explicit "yes" required)
- [ ] Phase 3: (Recommended) back up alewife.db
- [ ] Phase 4: Cascade delete in SQLite
- [ ] Phase 5: Remove entry from buildings_seed.json
- [ ] Phase 6: Remove entry from scrape_targets.json
- [ ] Phase 7: Re-run `./make.ps1 seed` (should log updated=0 inserted=0)
- [ ] Phase 8: Validate /api/buildings and /api/health
```

---

## Phase 1 — Resolve target + preview impact

1. If the user gave a **slug**, confirm it exists:

   ```powershell
   (Invoke-WebRequest http://localhost:8000/api/buildings).Content | ConvertFrom-Json |
     Where-Object slug -eq "<slug>"
   ```

2. If they gave a **name** or **Maps URL**, find the slug:
   - Search `App V1 Dynamic/backend/app/seed/buildings_seed.json` for a close name match.
   - If ambiguous (multiple matches), list candidates and ask the user to pick one.
   - Never guess.

3. Preview the impact before touching anything. Run:

   ```powershell
   docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
     sqlite3 /srv/data/alewife.db `
     "SELECT 'building' AS t, COUNT(*) FROM building WHERE slug='<slug>' UNION ALL
      SELECT 'travel_time', COUNT(*) FROM travel_time WHERE building_id=(SELECT id FROM building WHERE slug='<slug>') UNION ALL
      SELECT 'price_snapshot', COUNT(*) FROM price_snapshot WHERE building_id=(SELECT id FROM building WHERE slug='<slug>') UNION ALL
      SELECT 'rating_snapshot', COUNT(*) FROM rating_snapshot WHERE building_id=(SELECT id FROM building WHERE slug='<slug>');"
   ```

   Report the output back to the user in the confirmation message.

## Phase 2 — Confirmation gate

Echo a summary and **wait for explicit confirmation**:

```
About to permanently delete:
  slug:            <slug>
  name:            <name>
  travel_time rows:     <count>
  price_snapshot rows:  <count>
  rating_snapshot rows: <count>

This will also remove the entry from buildings_seed.json and scrape_targets.json.
Reply "yes, delete" to proceed. Anything else aborts.
```

If the user replies with anything other than a clear affirmative (e.g. "yes", "yes, delete", "confirm"), abort. Do not continue on "maybe", "I think so", or silence.

## Phase 3 — Back up the database (recommended)

Inside the container is simplest:

```powershell
docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
  sqlite3 /srv/data/alewife.db ".backup /srv/data/alewife-backup-pre-remove.db"
```

The backup lands next to the live DB on the bind mount (`App V1 Dynamic/backend/alewife-data/`). Tell the user the filename so they can delete it later if they want.

Skip only if the user explicitly says "no backup".

## Phase 4 — Cascade delete

Order matters because of foreign keys. Run these in one transaction:

```powershell
docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
  sqlite3 /srv/data/alewife.db "
BEGIN;
DELETE FROM price_snapshot  WHERE building_id = (SELECT id FROM building WHERE slug='<slug>');
DELETE FROM rating_snapshot WHERE building_id = (SELECT id FROM building WHERE slug='<slug>');
DELETE FROM travel_time     WHERE building_id = (SELECT id FROM building WHERE slug='<slug>');
DELETE FROM building        WHERE slug='<slug>';
COMMIT;
"
```

Verify the building is gone:

```powershell
docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
  sqlite3 /srv/data/alewife.db "SELECT COUNT(*) FROM building WHERE slug='<slug>';"
```

Expect `0`. If it's anything else, stop and consult [reference.md](reference.md).

## Phase 5 — Remove from `buildings_seed.json`

Read `App V1 Dynamic/backend/app/seed/buildings_seed.json`. Remove the object with the matching slug.

**Formatting rules (do not violate):**

- If the removed object was the last element, strip the trailing comma from the previous object.
- If it was the first or middle element, strip its trailing comma with it.
- 2-space indentation; match the existing file style.
- Preserve trailing newline at EOF.
- Validate:

  ```powershell
  Get-Content "App V1 Dynamic/backend/app/seed/buildings_seed.json" | ConvertFrom-Json | Out-Null
  ```

  If that errors, restore from git and retry.

## Phase 6 — Remove from `scrape_targets.json`

Open `App V1 Dynamic/backend/app/seed/scrape_targets.json`. If the `buildings` object contains the slug, remove that key-value pair (and fix the neighboring commas).

If the slug wasn't present there (common when the building was added without scrape URLs), skip this phase and note it in the final report.

Validate JSON afterwards the same way as Phase 5.

## Phase 7 — Re-run the seeder

```powershell
./make.ps1 seed
```

Expected output:

```
Seed load complete: inserted=0 updated=<N>
```

`inserted=0` confirms you didn't accidentally re-add the building via a stale JSON object. If `inserted` is nonzero, a different building was added back somehow — `git diff` the seed file and investigate.

## Phase 8 — Validate

All three checks must pass before declaring done:

1. Slug is absent from `/api/buildings`:

   ```powershell
   (Invoke-WebRequest http://localhost:8000/api/buildings).Content | ConvertFrom-Json |
     Where-Object slug -eq "<slug>"
   ```

   Expect no output.

2. `building_count` in `/api/health` dropped by one:

   ```powershell
   (Invoke-WebRequest http://localhost:8000/api/health).Content | ConvertFrom-Json |
     Select-Object building_count
   ```

3. No orphan snapshots remain:

   ```powershell
   docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
     sqlite3 /srv/data/alewife.db "
   SELECT 'tt' AS t, COUNT(*) FROM travel_time WHERE building_id NOT IN (SELECT id FROM building) UNION ALL
   SELECT 'ps', COUNT(*) FROM price_snapshot  WHERE building_id NOT IN (SELECT id FROM building) UNION ALL
   SELECT 'rs', COUNT(*) FROM rating_snapshot WHERE building_id NOT IN (SELECT id FROM building);"
   ```

   Expect `0` for all three rows.

If (1) still lists the slug, the `/api/buildings` cache may be holding the old response. Either wait 5 min for the TTL, call `POST /api/refresh` (which invalidates the cache), or bounce the container with `./make.ps1 down-local && ./make.ps1 up-local`.

## Reporting back to the user

When all eight phases pass:

```
Removed <name> (<slug>).
  building_count:       <old> → <new>
  travel_time deleted:  <count>
  price_snapshot deleted: <count>
  rating_snapshot deleted: <count>
  buildings_seed.json:  entry removed
  scrape_targets.json:  <entry removed | not present>
  backup:               <path or "skipped">

Hard-reload http://localhost:8000/ to confirm the pin is gone.
```

## Failure modes and recovery

See [reference.md](reference.md) for:

- Restoring from the backup if the user regrets the delete.
- What to do if the cascade delete leaves orphan rows.
- Handling the case where the slug exists in the DB but not in the JSON (or vice versa).
- Resolving ambiguous name matches.
