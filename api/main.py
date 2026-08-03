"""
F1 Strategy Predictor — FastAPI backend.

App setup and wiring only. Routes live in api/routers/, grouped by domain:
  meta       — session metadata, auth diagnostics
  timing     — live/replay board, locations, sectors, intervals
  analysis   — FP/quali analysis, tyre inventory, pre-race strategy
  strategy   — strategy generation, the prediction engine, what-if
  briefings  — race listings, pre-race + post-race briefings
"""

import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from api.routers import meta, timing, analysis, strategy, briefings

app = FastAPI(title="F1 Strategy Predictor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

# Cache-busting token stamped into the HTML's asset URLs so browsers can never
# serve a stale .js/.css after a deploy. Tied to the deployed commit on Railway
# (RAILWAY_GIT_COMMIT_SHA), so it changes only when the code changes; falls back
# to a process-start timestamp locally.
ASSET_VERSION = (os.environ.get("RAILWAY_GIT_COMMIT_SHA")
                 or str(int(time.time())))[:12]


def _serve_page(filename: str) -> HTMLResponse:
    """Serve an HTML page with the current ASSET_VERSION stamped into its asset
    URLs (the pages use ?v=__ASSET_VERSION__ on their css/js references). The
    HTML document itself is marked no-store so the version tokens are always
    fresh; the versioned css/js can then be cached hard and safely."""
    with open(os.path.join(FRONTEND_DIR, filename)) as f:
        html = f.read().replace("__ASSET_VERSION__", ASSET_VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})

app.include_router(meta.router)
app.include_router(timing.router)
app.include_router(analysis.router)
app.include_router(strategy.router)
app.include_router(briefings.router)


# Serve frontend
@app.get("/")
def index():
    # Strategy briefings are the product's front door. The live timing board is
    # frozen (available at /live) — real-time timing already exists everywhere;
    # the strategy analysis is the differentiated part.
    return _serve_page("briefing.html")


@app.get("/live")
def live_board():
    return _serve_page("index.html")


# Direct .html paths (e.g. bookmarked /briefing.html) get the same version
# injection — defined before the static mount so they win over the raw file.
@app.get("/briefing.html")
def briefing_page():
    return _serve_page("briefing.html")


@app.get("/index.html")
def index_page():
    return _serve_page("index.html")


# Mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
