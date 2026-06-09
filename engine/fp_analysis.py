"""
Free Practice analysis engine.

Classifies each stint as:
  HOTLAP   — 1-2 timed laps (qualifying simulation)
  SHORT    — 3-5 timed laps (tyre eval / setup check)
  LONG     — 6+ timed laps (race pace simulation)

Calculates per-driver per-compound degradation rate using true tyre age
as X-axis, properly handling returned tyres across multiple stints.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import statistics

# ── Classification thresholds ────────────────────────────────────────────────
HOTLAP_MAX   = 2    # 1-2 timed laps → HOTLAP
SHORT_MAX    = 5    # 3-5 timed laps → SHORT
# 6+ timed laps → LONG

# ── Filtering ────────────────────────────────────────────────────────────────
OUTLIER_PCT  = 1.10  # laps more than 10% slower than stint best are noise
MAX_LAP_TIME = 600   # ignore laps longer than this (red flag, pit stop, etc.)

# ── Minimum data for degradation regression ──────────────────────────────────
DEG_MIN_LAPS = 5     # need at least this many timed laps to fit a deg rate


@dataclass
class FPLap:
    lap_number:  int
    true_age:    int    # tyre_age_at_start + position within stint
    lap_time:    float
    s1: float | None
    s2: float | None
    s3: float | None
    is_pit_out:  bool

    def to_dict(self) -> dict:
        return {
            "lap_number": self.lap_number,
            "true_age":   self.true_age,
            "lap_time":   round(self.lap_time, 3),
            "s1": round(self.s1, 3) if self.s1 else None,
            "s2": round(self.s2, 3) if self.s2 else None,
            "s3": round(self.s3, 3) if self.s3 else None,
            "is_pit_out": self.is_pit_out,
        }


@dataclass
class FPStint:
    stint_number:      int
    compound:          str
    tyre_age_at_start: int
    laps:              list[FPLap] = field(default_factory=list)

    @property
    def timed_laps(self) -> list[FPLap]:
        """Clean laps — exclude pit-out laps and obvious cool-down/slow laps."""
        valid = [l for l in self.laps if not l.is_pit_out and l.lap_time < MAX_LAP_TIME]
        if not valid:
            return []
        best = min(l.lap_time for l in valid)
        return [l for l in valid if l.lap_time <= best * OUTLIER_PCT]

    @property
    def classification(self) -> str:
        n = len(self.timed_laps)
        if n <= HOTLAP_MAX:  return "HOTLAP"
        if n <= SHORT_MAX:   return "SHORT"
        return "LONG"

    @property
    def best_lap(self) -> float | None:
        tl = self.timed_laps
        return min(l.lap_time for l in tl) if tl else None

    @property
    def avg_pace(self) -> float | None:
        """Average lap time of timed laps — only meaningful for SHORT/LONG runs."""
        tl = self.timed_laps
        if len(tl) < 2:
            return None
        return round(sum(l.lap_time for l in tl) / len(tl), 3)

    def to_dict(self) -> dict:
        return {
            "stint_number":      self.stint_number,
            "compound":          self.compound,
            "tyre_age_at_start": self.tyre_age_at_start,
            "classification":    self.classification,
            "lap_count":         len(self.laps),
            "timed_laps":        len(self.timed_laps),
            "best_lap":          self.best_lap,
            "avg_pace":          self.avg_pace,
            "laps":              [l.to_dict() for l in self.laps],
        }


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Returns (slope, intercept) via OLS."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    intercept = my - slope * mx
    return slope, intercept


def _compute_deg_rate(stints: list[FPStint], compound: str) -> float | None:
    """
    Compute degradation rate (s/lap of tyre age) for a given compound.

    Uses true tyre age as X (handles returned tyres correctly).
    Only uses laps from stints with enough data (DEG_MIN_LAPS).
    """
    relevant = [s for s in stints if s.compound == compound]
    # Pool laps from all long-enough stints
    xs, ys = [], []
    for s in relevant:
        tl = s.timed_laps
        if len(tl) < DEG_MIN_LAPS:
            continue
        for lap in tl:
            xs.append(float(lap.true_age))
            ys.append(lap.lap_time)

    if len(xs) < DEG_MIN_LAPS:
        return None

    slope, _ = _linear_regression(xs, ys)
    return round(slope, 4)  # seconds per lap of tyre age


@dataclass
class CompoundSummary:
    compound:    str
    stints:      list[FPStint]

    @property
    def hotlaps(self) -> list[FPStint]:
        return [s for s in self.stints if s.classification == "HOTLAP"]

    @property
    def short_runs(self) -> list[FPStint]:
        return [s for s in self.stints if s.classification == "SHORT"]

    @property
    def long_runs(self) -> list[FPStint]:
        return [s for s in self.stints if s.classification == "LONG"]

    @property
    def best_hotlap(self) -> float | None:
        times = [s.best_lap for s in self.hotlaps if s.best_lap]
        return min(times) if times else None

    @property
    def best_race_pace(self) -> float | None:
        """Best average pace across all long runs."""
        avgs = [s.avg_pace for s in self.long_runs if s.avg_pace]
        return min(avgs) if avgs else None

    def to_dict(self) -> dict:
        return {
            "compound":       self.compound,
            "hotlap_count":   len(self.hotlaps),
            "best_hotlap":    self.best_hotlap,
            "short_run_count": len(self.short_runs),
            "long_run_count": len(self.long_runs),
            "best_race_pace": self.best_race_pace,
            "long_runs": [s.to_dict() for s in self.long_runs],
            "short_runs": [s.to_dict() for s in self.short_runs],
        }


@dataclass
class FPDriverSummary:
    driver_number: int
    acronym:       str
    team:          str
    team_colour:   str
    stints:        list[FPStint] = field(default_factory=list)
    deg_rates:     dict[str, float] = field(default_factory=dict)

    @property
    def compounds_used(self) -> list[str]:
        seen, out = set(), []
        for s in self.stints:
            if s.compound not in seen:
                seen.add(s.compound)
                out.append(s.compound)
        return out

    @property
    def best_lap_overall(self) -> float | None:
        bests = [s.best_lap for s in self.stints if s.best_lap]
        return min(bests) if bests else None

    @property
    def compound_summaries(self) -> list[CompoundSummary]:
        groups: dict[str, list[FPStint]] = {}
        for s in self.stints:
            groups.setdefault(s.compound, []).append(s)
        COMPOUND_ORDER = {"SOFT": 0, "MEDIUM": 1, "HARD": 2,
                          "INTERMEDIATE": 3, "WET": 4}
        return [
            CompoundSummary(compound=c, stints=stints)
            for c, stints in sorted(groups.items(),
                                    key=lambda x: COMPOUND_ORDER.get(x[0], 9))
        ]

    def to_dict(self) -> dict:
        return {
            "driver_number":    self.driver_number,
            "acronym":          self.acronym,
            "team":             self.team,
            "team_colour":      self.team_colour,
            "best_lap_overall": self.best_lap_overall,
            "deg_rates":        self.deg_rates,
            "compound_summaries": [cs.to_dict() for cs in self.compound_summaries],
        }


def analyse_fp(laps_raw: list[dict], stints_raw: list[dict],
               drivers_raw: dict[int, dict]) -> list[FPDriverSummary]:
    """Build per-driver FP summaries."""

    # Build stint lookup: (driver, lap_number) → stint dict
    stint_map: dict[tuple, dict] = {}
    for s in stints_raw:
        end = s.get("lap_end") or 9999
        for lap_n in range(s["lap_start"], end + 1):
            stint_map[(s["driver_number"], lap_n)] = s

    # Group laps by driver
    laps_by_driver: dict[int, list[dict]] = {}
    for lap in laps_raw:
        if lap.get("lap_duration") is None:
            continue
        laps_by_driver.setdefault(lap["driver_number"], []).append(lap)

    summaries: list[FPDriverSummary] = []

    for num, d in drivers_raw.items():
        driver_laps = sorted(laps_by_driver.get(num, []), key=lambda l: l["lap_number"])
        if not driver_laps:
            continue

        summary = FPDriverSummary(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            team=d.get("team_name", ""),
            team_colour=d.get("team_colour") or "ffffff",
        )

        # Build stints
        stints_built: dict[int, FPStint] = {}
        for lap in driver_laps:
            stint_raw = stint_map.get((num, lap["lap_number"]))
            if stint_raw is None:
                continue
            sn = stint_raw["stint_number"]
            if sn not in stints_built:
                stints_built[sn] = FPStint(
                    stint_number=sn,
                    compound=stint_raw.get("compound", "UNKNOWN"),
                    tyre_age_at_start=stint_raw.get("tyre_age_at_start", 0),
                )
            age_at_start = stint_raw.get("tyre_age_at_start", 0)
            lap_in_stint = lap["lap_number"] - stint_raw["lap_start"]
            true_age = age_at_start + lap_in_stint

            stints_built[sn].laps.append(FPLap(
                lap_number=lap["lap_number"],
                true_age=max(0, true_age),
                lap_time=lap["lap_duration"],
                s1=lap.get("duration_sector_1"),
                s2=lap.get("duration_sector_2"),
                s3=lap.get("duration_sector_3"),
                is_pit_out=lap.get("is_pit_out_lap", False),
            ))

        summary.stints = sorted(stints_built.values(), key=lambda s: s.stint_number)

        # Compute degradation rates per compound
        for compound in summary.compounds_used:
            rate = _compute_deg_rate(summary.stints, compound)
            if rate is not None:
                summary.deg_rates[compound] = rate

        summaries.append(summary)

    # Sort by best lap
    summaries.sort(key=lambda d: (d.best_lap_overall is None, d.best_lap_overall or 999))
    return summaries
