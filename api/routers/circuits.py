"""Standalone circuit-guide pages (frontend/circuits.html) -- a real, named
history of Safety Cars/VSCs/red flags per circuit, plotted at their real
corners. See engine/circuit_guide.py's module docstring for why this is a
hand-curated dataset rather than derived from OpenF1."""

from fastapi import APIRouter, HTTPException

from engine.circuit_guide import get_circuit_guide
from engine.pit_loss import pit_loss_for
from engine.predictor import SC_PIT_FACTOR, VSC_PIT_FACTOR

router = APIRouter()


@router.get("/api/circuit_guide")
def circuit_guide(circuit: str):
    guide = get_circuit_guide(circuit)
    if guide is None:
        raise HTTPException(status_code=404,
                            detail=f"No circuit guide for '{circuit}' yet.")

    green = pit_loss_for(circuit)
    guide = dict(guide)
    guide["pit_loss"] = {
        "green": round(green, 1),
        "sc": round(green * SC_PIT_FACTOR, 1),
        "vsc": round(green * VSC_PIT_FACTOR, 1),
        "redflag": 0.0,
    }
    return guide
