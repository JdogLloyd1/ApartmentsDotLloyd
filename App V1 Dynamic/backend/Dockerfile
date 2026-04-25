# Backend container image for the Alewife dashboard.
#
# Based on the official Playwright image so Chromium + every OS-level
# dependency the scrapers need are already installed. Pinned to a
# specific Noble (Ubuntu 24.04) build so a future tag change can't silently
# regress the scrapers.
#
# IMPORTANT: this tag MUST match the ``playwright`` pin in
# ``backend/pyproject.toml``. Playwright publishes a new browser bundle
# in every minor release, and the Python client refuses to launch
# Chromium unless the two versions line up exactly (you'll see
# "Executable doesn't exist at /ms-playwright/chromium..." otherwise).
# When upgrading, bump both files in the same commit.
#
# Build from the repo root:
#   docker build -f "App V1 Dynamic/backend/Dockerfile" -t alewife-api "App V1 Dynamic"
#
# See App V1 Dynamic/RUN_LOCALLY.md for the developer-facing walkthrough.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# The repository ships both the backend Python package and the static
# frontend bundle next to each other. Copying them under /srv keeps the
# in-container path layout identical to the host so `BACKEND_DIR.parent
# / "frontend"` in app/main.py continues to resolve.
WORKDIR /srv/backend

COPY backend/pyproject.toml backend/README.md ./
# Dependency-only layer: changes to Python source don't bust the pip cache.
RUN pip install --upgrade pip \
 && pip install -e ".[scraping,scheduling]"

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY frontend /srv/frontend

# SQLite lives outside the app dir so a bind-mounted host directory can
# survive `docker compose down` without touching source.
RUN mkdir -p /srv/data
ENV DATABASE_URL=sqlite:////srv/data/alewife.db

EXPOSE 8000

# Single-process uvicorn is enough for this workload; APScheduler needs
# in-process state so multi-worker deployments would need a leader lock.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
