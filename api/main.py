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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.routers import meta, timing, analysis, strategy, briefings

app = FastAPI(title="F1 Strategy Predictor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

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
    return FileResponse(os.path.join(FRONTEND_DIR, "briefing.html"))


@app.get("/live")
def live_board():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# Mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
