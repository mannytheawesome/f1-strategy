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
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers import meta, timing, analysis, strategy, briefings, usage
from data.warmer import start_background_warmer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-fetches a recently-completed session's live-board data so the
    # first real user request is a cache hit, not a 10+s cold OpenF1
    # round-trip that looks broken on the frontend (see data/warmer.py).
    start_background_warmer()
    yield


app = FastAPI(title="F1 Strategy Predictor", lifespan=lifespan)

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


def _serve_page(filename: str, status_code: int = 200) -> HTMLResponse:
    """Serve an HTML page with the current ASSET_VERSION stamped into its asset
    URLs (the pages use ?v=__ASSET_VERSION__ on their css/js references). The
    HTML document itself is marked no-store so the version tokens are always
    fresh; the versioned css/js can then be cached hard and safely."""
    with open(os.path.join(FRONTEND_DIR, filename)) as f:
        html = f.read().replace("__ASSET_VERSION__", ASSET_VERSION)
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """A styled 404 page for a human landing on a bad/stale URL -- API paths
    (and this app's own frontend JS, which reads `.detail` off the JSON
    body) keep the plain `{"detail": ...}` shape unchanged for every other
    case, matching FastAPI's own default handler."""
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return _serve_page("404.html", status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

app.include_router(meta.router)
app.include_router(timing.router)
app.include_router(analysis.router)
app.include_router(strategy.router)
app.include_router(briefings.router)
app.include_router(usage.router)


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


@app.get("/admin")
def admin_page():
    # Not linked from anywhere public -- gated behind ADMIN_TOKEN at the API
    # layer (see api/routers/usage.py), not by obscurity, but there's no
    # reason to advertise it either.
    return _serve_page("admin.html")


# Direct .html paths (e.g. bookmarked /briefing.html) get the same version
# injection — defined before the static mount so they win over the raw file.
@app.get("/briefing.html")
def briefing_page():
    return _serve_page("briefing.html")


@app.get("/index.html")
def index_page():
    return _serve_page("index.html")


@app.get("/admin.html")
def admin_html_page():
    return _serve_page("admin.html")


# Mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
