# `remove-building` — failure modes and recovery

Read this only when a phase in `SKILL.md` fails or a scenario falls outside the happy path.

## The user wants to undo the delete

If the Phase 3 backup was taken, restore from it:

```powershell
./make.ps1 down-local
Copy-Item "App V1 Dynamic/backend/alewife-data/alewife-backup-pre-remove.db" `
          "App V1 Dynamic/backend/alewife-data/alewife.db" -Force
git checkout -- "App V1 Dynamic/backend/app/seed/buildings_seed.json" `
                "App V1 Dynamic/backend/app/seed/scrape_targets.json"
./make.ps1 up-local
```

If no backup exists, recovery means manually re-adding the building via the `add-building` skill. Snapshot history is gone.

## `DELETE` left orphan rows

Phase 8 check (3) returned nonzero counts. Causes and fixes:

- **Different building with the same `building_id` exists** → there shouldn't be, `id` is a primary key. Run:

  ```powershell
  docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
    sqlite3 /srv/data/alewife.db "SELECT id, slug FROM building;"
  ```

  and cross-reference IDs with the orphan rows to find what happened.
- **Another process inserted rows mid-delete** → unlikely under local Docker, but possible if the scheduler ran. Re-run the cascade DELETE; orphans should clear.

Fix any stragglers with:

```powershell
docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
  sqlite3 /srv/data/alewife.db "
DELETE FROM price_snapshot  WHERE building_id NOT IN (SELECT id FROM building);
DELETE FROM rating_snapshot WHERE building_id NOT IN (SELECT id FROM building);
DELETE FROM travel_time     WHERE building_id NOT IN (SELECT id FROM building);
"
```

## Slug exists in DB but not in `buildings_seed.json`

The building was probably added directly via API or a one-off SQL INSERT at some point. The DELETE still works by slug. After Phase 4:

- Phase 5 becomes a no-op — just note "not present in seed" in the final report.
- Phase 7 (`make seed`) must still be run so the loader's internal caches reconcile.

## Slug exists in `buildings_seed.json` but not in the DB

The database was rebuilt without re-seeding, or the seed object was added but `make seed` never ran. The DELETE in Phase 4 will affect 0 rows; Phase 5/6 (JSON edits) are the only meaningful step. Proceed normally; the final report will read `building_count: <old> → <old>`.

## Ambiguous name matches

Phase 1 found more than one candidate. Ask the user with all context needed to pick:

```
Found multiple buildings matching "<query>":
  1. the-commons-arlington        — 100 Commonwealth Ave, Arlington
  2. the-commons-cambridge        — 200 Mass Ave, Cambridge

Which one should be removed? Reply with the slug.
```

Do not assume. If the user replies with a slug that isn't in the candidate list, restart Phase 1.

## `./make.ps1 seed` prints `inserted=1` after a remove

You accidentally re-added a building. Most common cause: the seed JSON object wasn't actually removed — the JSON parsed but the object is still there. Run:

```powershell
git diff -- "App V1 Dynamic/backend/app/seed/buildings_seed.json"
```

Confirm the block for the target slug is actually gone, then redo Phase 5.

## `sqlite3` command not found inside the container

The Playwright base image ships `sqlite3` by default. If it's somehow missing, fall back to Python:

```powershell
docker compose -f "App V1 Dynamic/docker-compose.local.yml" exec api `
  python -c "
import sqlite3
c = sqlite3.connect('/srv/data/alewife.db')
c.execute(\"DELETE FROM price_snapshot WHERE building_id = (SELECT id FROM building WHERE slug='<slug>')\")
c.execute(\"DELETE FROM rating_snapshot WHERE building_id = (SELECT id FROM building WHERE slug='<slug>')\")
c.execute(\"DELETE FROM travel_time WHERE building_id = (SELECT id FROM building WHERE slug='<slug>')\")
c.execute(\"DELETE FROM building WHERE slug='<slug>'\")
c.commit()
print('ok')
"
```

## User says "the dashboard still shows the building"

In order of likelihood:

1. Browser cache — hard-reload (`Ctrl+F5`).
2. The `/api/buildings` response is cached (5-min TTL). Either wait, or call `POST /api/refresh` with the bearer token, or `./make.ps1 down-local && ./make.ps1 up-local`.
3. The DELETE didn't commit — re-run the Phase 8 DB checks to confirm.

## Rolling back a half-done remove

If Phase 4 ran but Phase 5/6 didn't (e.g. JSON edit blew up), the system is temporarily inconsistent but safe to leave:

- The DB no longer has the building → `/api/buildings` won't return it.
- Next `./make.ps1 seed` would re-insert it from the unchanged JSON.

To finish cleanly, just complete Phases 5–8. To truly roll back, restore the DB from the Phase 3 backup.
