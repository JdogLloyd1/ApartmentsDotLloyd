---
name: alewife dynamic backend
overview: Convert the static Alewife apartment dashboard into a live data-driven app. A Python/FastAPI backend scrapes prices and Google ratings, computes walk/drive isochrones and per-building travel times via OpenRouteService, and exposes a JSON API consumed by the existing Leaflet dashboard. SQLite + TTL cache + APScheduler, deployable to a $6/mo DigitalOcean droplet.
todos:
  - id: sprint-0
    content: "Sprint 0 — Foundation & Tooling: scaffold backend, pyproject, ruff, mypy, pytest, Makefile, CI, /api/health smoke test"
    status: completed
  - id: sprint-1
    content: "Sprint 1 — Data Seed & Building Catalog: parse static JS apts array into buildings_seed.json, SQLModel Building table, idempotent loader"
    status: completed
  - id: sprint-2
    content: "Sprint 2 — Core API: GET /api/buildings, /api/buildings/{slug}, scoring module ported from HTML, TestClient integration tests"
    status: completed
  - id: sprint-3
    content: "Sprint 3 — API-Driven Frontend: move HTML to frontend/, extract JS/CSS, fetch /api/buildings, static file serving from FastAPI"
    status: completed
  - id: sprint-4
    content: "Sprint 4 — Routing Service: ORS client, travel_time + isochrone tables, refresh services, /api/isochrones, frontend uses L.geoJSON"
    status: completed
  - id: sprint-5
    content: "Sprint 5 — Scrapers: Playwright base, apartments.com + Google Maps scrapers, snapshot tables, offline fixture tests"
    status: completed
  - id: sprint-6
    content: "Sprint 6 — Refresh Orchestration: TTL cache, APScheduler cron, POST /api/refresh with auth, refresh_run table, freshness header + UI chip"
    status: completed
  - id: sprint-7
    content: "Sprint 7 — Local Full-Stack Validation (deployment gate): Dockerfile, docker-compose.local.yml, Makefile up-local, E2E smoke, standalone RUN_LOCALLY.md walkthrough, LOCAL_VALIDATION.md QA checklist"
    status: completed
  - id: sprint-8
    content: "Sprint 8 — Production Deployment: prod compose + Caddy, bootstrap script, GitHub Actions deploy, DO droplet smoke, Posit fallback documented"
    status: pending
  - id: sprint-9
    content: "Sprint 9 — Documentation: App V1 Dynamic/README.md (human, per developer_readme_format.mdc), App V1 Dynamic/CURSOR.md (AI, per cursor_readme_format.mdc), root README rewrite, backend/frontend READMEs, RUNBOOK, CONTRIBUTING, CHANGELOG, docstrings, link-checker, rule-conformance script"
    status: pending
isProject: false
---

Full plan is saved to [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md). Highlights:

**Stack:** FastAPI + Uvicorn, SQLModel over SQLite (WAL), Playwright for scraping, OpenRouteService free tier (500 isochrone req/day) for routing, APScheduler for daily refresh, cachetools TTL cache, Docker + Caddy on DigitalOcean.

**Architecture**

```mermaid
flowchart LR
  Browser["Dashboard HTML/JS"] -->|"/api/buildings"| API["FastAPI"]
  API --> Cache["TTLCache"] --> DB[("SQLite")]
  Scheduler["APScheduler"] --> Scrapers["Playwright"] --> DB
  Scheduler --> Routing["OpenRouteService"] --> DB
  API -->|"/api/isochrones"| Browser
```

**Key files to create** (under `App V1 Dynamic/backend/app/`):
- `main.py`, `config.py`, `db.py`, `models.py`, `scoring.py`
- `api/{buildings,isochrones,refresh,health}.py`
- `scrapers/{apartments_com,google_places}.py`
- `routing/{ors_client,isochrone_service}.py`
- `scheduler.py`, `seed/buildings_seed.json`

**Key files to modify:**
- [Static Dashboard References/alewife_dashboard_v2.html](Static%20Dashboard%20References/alewife_dashboard_v2.html) — relocate to `App V1 Dynamic/frontend/index.html` and replace the hardcoded `apts` array (lines 195–291) + six `walkIso*/driveIso*` polygon literals (lines 184–192) with `fetch('/api/buildings')` and `fetch('/api/isochrones')` calls. Score math ported server-side from lines 294–302 (also fixes the existing `a.driveMin` undefined-variable bug).

**Deployment:** DigitalOcean droplet primary (Docker + Caddy). Posit Cloud usable as a read-only frontend if scraping is offloaded to GitHub Actions nightly — noted as fallback.

**Sprint roadmap (10 sequential sprints, each independently verifiable):**

See Section 17 of [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) for full deliverables, verification steps, and acceptance criteria per sprint.

- **Sprint 0** — Foundation & tooling (scaffold, ruff, mypy, pytest, CI, health check)
- **Sprint 1** — Data seed & building catalog (JSON extraction + SQLModel + idempotent loader)
- **Sprint 2** — Core API (buildings endpoints + ported scoring + TestClient tests)
- **Sprint 3** — API-driven frontend (fetch-based rewrite of the HTML)
- **Sprint 4** — Routing service (ORS travel-time matrix + isochrones, frontend uses GeoJSON)
- **Sprint 5** — Scrapers (apartments.com prices + Google ratings with offline fixture tests)
- **Sprint 6** — Refresh orchestration (TTL cache, APScheduler, `/api/refresh`, freshness UI chip)
- **Sprint 7** — **Local full-stack validation — MANDATORY gate.** Dockerfile, docker-compose.local.yml, E2E smoke test against real ORS + scrapers, manual QA checklist. Sprint 8 blocked until this passes.
- **Sprint 8** — Production deployment (DO droplet + Caddy + GitHub Actions; Posit Cloud fallback documented)
- **Sprint 9** — Documentation (root README, per-module READMEs, runbook, contributing guide, changelog)

Sprints 3, 4, and 5 can run in parallel once Sprint 2 is done; everything else is strictly sequential. Every sprint has tests that pass using seeded/mocked data so none depends on outputs of future sprints to close.