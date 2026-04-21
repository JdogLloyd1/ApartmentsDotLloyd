# Local Validation Checklist

A focused QA checklist for the maintainer to walk through after every meaningful change to the backend, scrapers, or frontend. This complements (does not replace) the automated suite and `make smoke-e2e`.

Use [RUN_LOCALLY.md](./RUN_LOCALLY.md) to get to the starting line; come back here to confirm the build is actually working.

---

## Table of Contents

- [Before you start](#before-you-start)
- [Phase 1 — Clean boot](#phase-1--clean-boot)
- [Phase 2 — API surface](#phase-2--api-surface)
- [Phase 3 — Data refresh](#phase-3--data-refresh)
- [Phase 4 — Dashboard UI](#phase-4--dashboard-ui)
- [Phase 5 — Authenticated refresh](#phase-5--authenticated-refresh)
- [Phase 6 — Resource + resilience](#phase-6--resource--resilience)
- [Sign-off](#sign-off)

---

## Before you start

- [ ] Working tree is clean (`git status` is empty or only has intentional changes).
- [ ] `App V1 Dynamic/backend/.env` exists with real values for `ORS_API_KEY` and `REFRESH_BEARER_TOKEN`.
- [ ] Port `8000` is free on the host.
- [ ] Docker Desktop is running.

---

## Phase 1 — Clean boot

Start from a fresh DB to catch regressions in the seed loader and first-run behavior.

- [ ] `make down-local` (noop if nothing was running).
- [ ] Delete any prior DB: `rm -f "App V1 Dynamic/backend/alewife-data/"*.db*`.
- [ ] `make up-local` completes without errors. First build ≤ 10 min on a clean machine; subsequent ≤ 2 min.
- [ ] `make logs-local` shows `Application startup complete.` within 15 s of the container starting.
- [ ] `curl -sf http://localhost:8000/api/health` returns `{"status": "ok", ...}` with `building_count: 0`.

---

## Phase 2 — API surface

Verify every public route answers before any data has been refreshed.

- [ ] `make seed` prints `inserted=19 updated=0` on the first run and `inserted=0 updated=0` on a second invocation.
- [ ] `curl http://localhost:8000/api/health` now reports `building_count >= 19`.
- [ ] `curl http://localhost:8000/api/buildings | python -m json.tool | head -20` shows real seed data (no ORS/scraper fields yet).
- [ ] `curl http://localhost:8000/api/isochrones` returns `{"walk": [], "drive": []}` (empty until refresh).
- [ ] `curl -I http://localhost:8000/api/buildings` includes a positive `X-Data-Freshness` header.
- [ ] `curl -i -X POST http://localhost:8000/api/refresh` (no auth) returns `401` with a JSON error body.

---

## Phase 3 — Data refresh

Run the real pipeline. This consumes ORS quota.

- [ ] `make refresh-all` completes without exceptions. Expected runtime: 4–7 minutes.
- [ ] Final output lists `travel_times`, `isochrones`, `prices`, and `ratings` counts; at least **6** isochrones reported total.
- [ ] `curl http://localhost:8000/api/isochrones` now returns three walk buckets (`5, 10, 15`) and three drive buckets (`2, 5, 10`).
- [ ] At least 50 % of scraped buildings have a non-null `pricesFetchedAt` in `/api/buildings`.
- [ ] `ratings` step completed with zero `error` entries (a few `no-data` entries are acceptable).

---

## Phase 4 — Dashboard UI

Use a real browser. Chrome/Safari/Firefox are all fine.

- [ ] Hard refresh `http://localhost:8000/` (`Shift+Cmd+R` / `Shift+Ctrl+R`).
- [ ] Header reads **Alewife Apartment Intelligence**.
- [ ] Leaflet map renders with:
  - [ ] Red Line stops as red circle markers.
  - [ ] Purple walk isochrones centered on the Alewife T stop.
  - [ ] Green drive isochrones around the Route 2 ramp.
  - [ ] A pin for every seeded building.
- [ ] Right-rail list shows all 19 buildings, each with a rent band and walk/drive time badges.
- [ ] **Freshness** chip reads `just now` or `< 1 m ago` immediately after the refresh.
- [ ] Clicking a building centers the map and highlights the row.
- [ ] Browser console has **no** red errors (warnings are OK).

---

## Phase 5 — Authenticated refresh

Exercise the manual refresh path used by the Runbook.

- [ ] In the browser console:
  ```js
  window.ALEWIFE_REFRESH_TOKEN = "<REFRESH_BEARER_TOKEN from .env>";
  location.reload();
  ```
- [ ] The **Refresh now** button appears in the header.
- [ ] Clicking it flips the chip to `Refreshing...` and back to `just now` within ~6 minutes.
- [ ] `curl -i -X POST -H "Authorization: Bearer badtoken" http://localhost:8000/api/refresh` returns `401`.
- [ ] `curl -i -X POST -H "Authorization: Bearer <real token>" http://localhost:8000/api/refresh` returns `202` with a `run_id`.
- [ ] `curl http://localhost:8000/api/refresh/<run_id>` reports `status: succeeded` after the run completes.

---

## Phase 6 — Resource + resilience

Final gates before declaring local validation complete.

- [ ] `make smoke-e2e` passes all 7 tests.
- [ ] During `make refresh-all`, Docker Desktop reports container RSS under **1.5 GB**. Check in Docker Desktop → Containers → `alewife-api-local` → Stats.
- [ ] `make down-local` followed by `make up-local` reconnects to the existing SQLite DB and `/api/buildings` still returns the previously refreshed data.
- [ ] `make test` (unit suite, not e2e) passes with zero failures.
- [ ] `make lint` passes (`ruff check` and `ruff format --check`).

---

## Sign-off

When every box above is ticked:

- [ ] Tag the repo or note the commit SHA in your release notes.
- [ ] If anything failed, file a ticket before moving to Sprint 8 (production deploy). **Do not deploy a build that failed local validation.**

---

← [Back to top](#local-validation-checklist)
