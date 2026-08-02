"""
Race-chart datasets reconstructed from public lap timing — the data behind the
RSS-style briefing graphs:

  race_trace    — each driver's gap to the leader over the whole race (#5)
  rejoin_map    — how many cars the leader would rejoin behind if they pit on
                  lap L (the "rejoin trap") (#4a)
  lapping_tax   — the time the leader bleeds in backmarker traffic, per lap (#4b)
  decision_page — the measured deg rates, the pit window, and the compound
                  rules on one panel (#3)

All of this is DERIVED from lap/stint data already fetched for the debrief; none
of it feeds the prediction engine, so it can't move the backtest.
"""

import statistics

DRY = ["SOFT", "MEDIUM", "HARD"]


def _cum_race_time(all_laps: list[dict], total_laps: int) -> dict[int, dict[int, float]]:
    """Cumulative race time per driver per lap, from lap_duration.

    A missing or implausible lap time is filled with the field's median for that
    lap number so a single dropout doesn't break a driver's whole trace. Returns
    {driver_number: {lap_number: cumulative_seconds}}.
    """
    # Field median duration per lap number (for gap-filling).
    per_lap: dict[int, list[float]] = {}
    for l in all_laps:
        t = l.get("lap_duration")
        if t is not None and 30 < t < 300:
            per_lap.setdefault(l["lap_number"], []).append(t)
    lap_median = {ln: statistics.median(v) for ln, v in per_lap.items() if v}
    field_median = statistics.median(lap_median.values()) if lap_median else 90.0

    laps_by_driver: dict[int, dict[int, float]] = {}
    for l in all_laps:
        laps_by_driver.setdefault(l["driver_number"], {})[l["lap_number"]] = l.get("lap_duration")

    out: dict[int, dict[int, float]] = {}
    for num, laps in laps_by_driver.items():
        last = max(laps)
        cum = 0.0
        series: dict[int, float] = {}
        for ln in range(1, last + 1):
            t = laps.get(ln)
            if t is None or not (30 < t < 300):
                t = lap_median.get(ln, field_median)
            cum += t
            series[ln] = round(cum, 3)
        out[num] = series
    return out


def _compound_at(stints: list[dict], lap: int) -> str:
    for s in stints:
        lo = s.get("lap_start") or 1
        hi = s.get("lap_end") or 9999
        if lo <= lap <= hi:
            return (s.get("compound") or "UNKNOWN").upper()
    return "UNKNOWN"


def race_trace(all_laps: list[dict], stints_by_driver: dict[int, list[dict]],
               acronyms: dict[int, str], total_laps: int,
               team_colours: dict[int, str] | None = None) -> dict:
    """Per-driver gap-to-leader (seconds) at the end of each lap. Positive = that
    driver is behind the lap leader on cumulative time. Each point carries the
    driver's compound so the trace can be coloured by stint; each driver carries
    their team colour so the whole field can be drawn, not just the leaders."""
    team_colours = team_colours or {}
    cum = _cum_race_time(all_laps, total_laps)
    # Leader cumulative time at each lap = the minimum among drivers present.
    leader_time: dict[int, float] = {}
    for ln in range(1, total_laps + 1):
        present = [c[ln] for c in cum.values() if ln in c]
        if present:
            leader_time[ln] = min(present)

    drivers = []
    for num, series in cum.items():
        stints = stints_by_driver.get(num, [])
        points = [
            {"lap": ln,
             "gap": round(series[ln] - leader_time[ln], 2),
             "compound": _compound_at(stints, ln)}
            for ln in sorted(series) if ln in leader_time
        ]
        if len(points) < 2:
            continue
        drivers.append({
            "driver_number": num,
            "acronym": acronyms.get(num, str(num)),
            "team_colour": team_colours.get(num),
            "final_gap": points[-1]["gap"],
            "laps_completed": points[-1]["lap"],
            "points": points,
        })
    # Order by who finished ahead (most laps, then smallest final gap).
    drivers.sort(key=lambda d: (-d["laps_completed"], d["final_gap"]))
    return {"total_laps": total_laps, "drivers": drivers}


def rejoin_map(all_laps: list[dict], pit_loss: float, total_laps: int) -> dict:
    """The "rejoin trap": if the lap leader pits on lap L and loses `pit_loss`
    seconds, how many cars do they rejoin behind? A car is jumped when its
    cumulative time at lap L sits inside (leader_time, leader_time + pit_loss).
    High counts mark the laps where a stop drops you into a DRS train."""
    cum = _cum_race_time(all_laps, total_laps)
    points = []
    for ln in range(1, total_laps + 1):
        times = sorted(c[ln] for c in cum.values() if ln in c)
        if len(times) < 2:
            continue
        leader = times[0]
        rejoin_behind = sum(1 for t in times[1:] if t <= leader + pit_loss)
        points.append({"lap": ln, "rejoin_behind": rejoin_behind})
    # Ignore the opening laps for the headline — the field is bunched at the
    # start, so a "rejoin behind everyone" there isn't a real strategic trap.
    trap_candidates = [p for p in points if p["lap"] >= 6] or points
    worst = max(trap_candidates, key=lambda p: p["rejoin_behind"], default=None)
    return {
        "total_laps": total_laps,
        "pit_loss": round(pit_loss, 2),
        "points": points,
        "worst_lap": worst["lap"] if worst else None,
        "worst_count": worst["rejoin_behind"] if worst else 0,
    }


def lapping_tax(all_laps: list[dict], total_laps: int) -> dict:
    """The leader's "lapping tax": as the leader catches backmarkers, count the
    lapped cars running within ~pit-window time of the leader each lap and
    estimate the pace lost. The tax is an ESTIMATE — a proxy for traffic density,
    not a measured clean-air delta."""
    cum = _cum_race_time(all_laps, total_laps)
    TRAFFIC_WINDOW_S = 25.0     # a backmarker within this many s is "in the way"
    TAX_PER_CAR_S = 0.4         # rough pace cost per lapped car cleared, per lap

    points = []
    running_tax = 0.0
    for ln in range(1, total_laps + 1):
        present = {num: c[ln] for num, c in cum.items() if ln in c}
        if len(present) < 2:
            continue
        leader_num = min(present, key=present.get)
        leader_t = present[leader_num]
        # Cars a full lap or more down that this lap have completed fewer laps
        # but sit just ahead of the leader on the road (within the window).
        laps_done = {num: max(c) for num, c in cum.items()}
        in_traffic = 0
        for num, t in present.items():
            if num == leader_num:
                continue
            behind_on_laps = laps_done[leader_num] - (ln)  # not used directly
            # "About to be lapped": car has completed fewer laps overall and is
            # within the traffic window ahead on corrected time.
            if laps_done[num] < laps_done[leader_num] and 0 < t - leader_t <= TRAFFIC_WINDOW_S:
                in_traffic += 1
        running_tax += in_traffic * TAX_PER_CAR_S
        points.append({"lap": ln, "cars_in_traffic": in_traffic,
                       "cumulative_tax_s": round(running_tax, 1)})
    return {
        "total_laps": total_laps,
        "estimate": True,
        "total_tax_s": round(running_tax, 1),
        "points": points,
    }


def decision_page(curves: dict, pit_loss: float, total_laps: int,
                  field_baseline: float, window: dict | None = None) -> dict:
    """The 'whole decision on one page': measured degradation per compound, the
    pit window, and the F1 compound rules — assembled from data that already
    exists. `curves` is a dict of compound -> object with .deg_rate/.baseline."""
    compounds = []
    for c in DRY:
        cur = curves.get(c)
        deg = getattr(cur, "deg_rate", None) if cur else None
        base = getattr(cur, "baseline", None) if cur else None
        compounds.append({
            "compound": c,
            "deg_rate": round(deg, 4) if deg else None,
            "baseline": round(base, 3) if base else None,
            "measured": bool(deg),
        })
    measured = [x for x in compounds if x["deg_rate"]]
    softest = min(measured, key=lambda x: x["deg_rate"]) if measured else None
    return {
        "total_laps": total_laps,
        "pit_loss": round(pit_loss, 2),
        "field_baseline": round(field_baseline, 3),
        "compounds": compounds,
        "window": window,   # {"earliest": lap, "latest": lap} or None
        "rules": [
            "Must use at least two different dry compounds.",
            "A stop costs about %.0fs on track." % pit_loss,
            ("Lowest measured deg: %s at %.3f s/lap." %
             (softest["compound"], softest["deg_rate"])) if softest else
            "Degradation not yet measurable from the data.",
        ],
    }
