import os
import sys

# Make the repo root importable regardless of how pytest is invoked (repo
# root isn't a package, so pytest's own path insertion doesn't reach it).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_stint(driver_number, compound, lap_start, lap_end, tyre_age_at_start=0,
               stint_number=1, **extra):
    """A minimal OpenF1-shaped stint record, for building synthetic sessions
    without hitting the network."""
    return {
        "driver_number": driver_number,
        "compound": compound,
        "lap_start": lap_start,
        "lap_end": lap_end,
        "tyre_age_at_start": tyre_age_at_start,
        "stint_number": stint_number,
        **extra,
    }


def make_driver(driver_number, acronym, team_colour="ffffff"):
    return {"name_acronym": acronym, "team_colour": team_colour}
