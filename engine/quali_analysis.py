"""
Qualifying analysis engine.

Produces per-driver qualifying summary:
  - Best timed lap (overall, per segment)
  - Best sectors
  - Gap to P1
  - Compound used on best lap
"""

from __future__ import annotations
from dataclasses import dataclass, field

# A lap is "timed" if it's not a pit-out lap and faster than this threshold
# relative to the session best (avoids picking up cool-down or aborted laps)
TIMED_LAP_THRESHOLD = 1.10  # within 10% of session best


@dataclass
class QualiLap:
    lap_number: int
    lap_time: float
    s1: float | None
    s2: float | None
    s3: float | None
    compound: str
    tyre_age: int

    def to_dict(self) -> dict:
        return {
            "lap_number": self.lap_number,
            "lap_time": round(self.lap_time, 3),
            "s1": round(self.s1, 3) if self.s1 else None,
            "s2": round(self.s2, 3) if self.s2 else None,
            "s3": round(self.s3, 3) if self.s3 else None,
            "compound": self.compound,
            "tyre_age": self.tyre_age,
        }


@dataclass
class QualiDriverSummary:
    driver_number: int
    acronym: str
    team: str
    team_colour: str
    timed_laps: list[QualiLap] = field(default_factory=list)
    gap_to_p1: float | None = None
    position: int | None = None

    @property
    def best_lap(self) -> float | None:
        return min((l.lap_time for l in self.timed_laps), default=None)

    @property
    def best_s1(self) -> float | None:
        vals = [l.s1 for l in self.timed_laps if l.s1]
        return min(vals) if vals else None

    @property
    def best_s2(self) -> float | None:
        vals = [l.s2 for l in self.timed_laps if l.s2]
        return min(vals) if vals else None

    @property
    def best_s3(self) -> float | None:
        vals = [l.s3 for l in self.timed_laps if l.s3]
        return min(vals) if vals else None

    @property
    def theoretical_best(self) -> float | None:
        s1, s2, s3 = self.best_s1, self.best_s2, self.best_s3
        if all(v is not None for v in [s1, s2, s3]):
            return round(s1 + s2 + s3, 3)
        return None

    @property
    def best_compound(self) -> str | None:
        best_time = self.best_lap
        if best_time is None:
            return None
        for l in self.timed_laps:
            if l.lap_time == best_time:
                return l.compound
        return None

    def to_dict(self) -> dict:
        return {
            "driver_number": self.driver_number,
            "acronym": self.acronym,
            "team": self.team,
            "team_colour": self.team_colour,
            "position": self.position,
            "best_lap": self.best_lap,
            "best_s1": round(self.best_s1, 3) if self.best_s1 else None,
            "best_s2": round(self.best_s2, 3) if self.best_s2 else None,
            "best_s3": round(self.best_s3, 3) if self.best_s3 else None,
            "theoretical_best": self.theoretical_best,
            "best_compound": self.best_compound,
            "gap_to_p1": round(self.gap_to_p1, 3) if self.gap_to_p1 is not None else None,
            "laps": [l.to_dict() for l in self.timed_laps],
        }


def analyse_quali(laps_raw: list[dict], stints_raw: list[dict],
                  drivers_raw: dict[int, dict]) -> list[QualiDriverSummary]:
    """Build qualifying summaries from raw OpenF1 data."""

    # Stint lookup for compound + age
    stint_map: dict[tuple, dict] = {}
    for s in stints_raw:
        end = s.get("lap_end") or 9999
        for lap_n in range(s["lap_start"], end + 1):
            stint_map[(s["driver_number"], lap_n)] = s

    # Find session best to filter noise
    all_times = [
        l["lap_duration"] for l in laps_raw
        if l.get("lap_duration") and not l.get("is_pit_out_lap")
        and l["lap_duration"] < 200
    ]
    session_best = min(all_times) if all_times else 90.0

    summaries: list[QualiDriverSummary] = []

    for num, d in drivers_raw.items():
        driver_laps = [
            l for l in laps_raw
            if l["driver_number"] == num
            and l.get("lap_duration")
            and not l.get("is_pit_out_lap")
            and l["lap_duration"] < session_best * TIMED_LAP_THRESHOLD
        ]
        if not driver_laps:
            continue

        summary = QualiDriverSummary(
            driver_number=num,
            acronym=d.get("name_acronym", str(num)),
            team=d.get("team_name", ""),
            team_colour=d.get("team_colour") or "ffffff",
        )

        for lap in driver_laps:
            stint_raw = stint_map.get((num, lap["lap_number"]))
            compound = stint_raw.get("compound", "SOFT") if stint_raw else "SOFT"
            tyre_age = (stint_raw.get("tyre_age_at_start", 0) +
                        lap["lap_number"] - stint_raw.get("lap_start", 1)) if stint_raw else 0

            summary.timed_laps.append(QualiLap(
                lap_number=lap["lap_number"],
                lap_time=lap["lap_duration"],
                s1=lap.get("duration_sector_1"),
                s2=lap.get("duration_sector_2"),
                s3=lap.get("duration_sector_3"),
                compound=compound,
                tyre_age=max(0, tyre_age),
            ))

        summaries.append(summary)

    # Sort by best lap, assign positions
    summaries.sort(key=lambda d: (d.best_lap is None, d.best_lap or 999))
    p1_time = summaries[0].best_lap if summaries else None
    for i, s in enumerate(summaries):
        s.position = i + 1
        if p1_time and s.best_lap:
            s.gap_to_p1 = 0.0 if i == 0 else round(s.best_lap - p1_time, 3)

    return summaries
