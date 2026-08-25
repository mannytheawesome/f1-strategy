"""
Pre-race briefings: forward-looking strategy decision frameworks built from
everything that has run BEFORE the grand prix — practice, sprint weekend
sessions, qualifying. Modelled on race-morning strategy newsletters: the
compound trade calculated as a formula with a lookup table, paper strategy
candidates, the Safety Car lever, and a watch-list of the unknowns that get
filled in live during the opening laps.

All inputs deliberately exclude the grand prix itself, so a pre-race
briefing can also be generated retrospectively for a finished weekend
("what the data said on Sunday morning").
"""

import json
import os
import statistics
from datetime import datetime, timezone

from data.live import (
    get_session, get_laps, get_stints, get_drivers, build_state,
    get_weather_summary, get_avg_pit_loss, _get, _cached_get, HIST_TTL,
)
from engine.predictor import (
    build_deg_curves, curves_to_dict, optimize_strategy, sc_probability,
    simulate_race, forecast_to_dict, DriverPace, FUEL_RATE,
    PIT_LOSS, DRY, SC_PIT_FACTOR, _lap_t, _cliff_life, MIN_STINT, _stint_time,
)

# Clean-lap filter for _long_run_pace (below): keep only laps within this
# ratio of a stint's own best lap, same idea as predictor.DEG_LONGRUN but
# looser — see _long_run_pace's comment for why 1.02 (tuned for slope-fitting)
# is too strict for measuring a single pace level across a stint.
PACE_ORDER_CLEAN_RATIO = 1.10

# A plan within this much of the optimum is genuinely in play; race-day noise
# (traffic, a slow stop, deg running hot) covers a gap this size.
LIVE_MARGIN_S = 10.0

PACK_VERSION = 17   # 17: added team_pace, per-strategy pit_windows, grid[].tyres
from engine.tyre_inventory import compute_inventory
from engine.briefing import BRIEFING_DIR, generate_structured_narrative
from engine.circuits import is_street_circuit, track_position_weight

# Scheduled race distance per circuit_short_name (lowercased). OpenF1 has no
# scheduled-laps field, so this mirrors the calendar; DEFAULT_LAPS covers
# anything missing.
CIRCUIT_LAPS = {
    "melbourne": 58, "shanghai": 56, "suzuka": 53, "sakhir": 57, "jeddah": 50,
    "miami": 57, "imola": 63, "monte carlo": 78, "monaco": 78, "catalunya": 66,
    "montreal": 70, "spielberg": 71, "silverstone": 52, "spa-francorchamps": 44,
    "spa": 44, "hungaroring": 70, "zandvoort": 72, "monza": 53, "baku": 51,
    "singapore": 62, "austin": 56, "mexico city": 71, "interlagos": 71,
    "las vegas": 50, "lusail": 57, "yas marina circuit": 58, "yas marina": 58,
    # 2026 additions. OpenF1 names them "Kuala Lumpur" (Sepang) and "Madring"
    # (Madrid). Both follow the FIA rule of the fewest laps exceeding 305 km:
    # Sepang 5.543 km -> 56; Madring 5.474 km -> 56.
    "kuala lumpur": 56, "sepang": 56, "madring": 56, "madrid": 56,
}
DEFAULT_LAPS = 55

PRERACE_SYSTEM = """You are the staff writer for an F1 race-strategy analysis site, \
writing the RACE MORNING briefing — published before lights-out. Your job is to arm \
the reader with the strategic questions of the race and the numbers that decide them.

Hard rules:
- Every number you cite MUST appear in the JSON data pack. Never invent lap times, \
degradation rates, probabilities, or positions.
- These are PRIORS, not results: frame estimates as estimates ("the practice data \
says", "on Saturday's numbers"), and name what could move them.
- Refer to drivers by their three-letter acronym as given in the data.
- Degradation rates are seconds per lap of tyre age. The compound trade works like \
this: the softer tyre wins a final stint of N laps while its deg excess over the \
harder tyre stays under 2 x offset / N, where offset is the harder tyre's fresh-pace \
deficit in s/lap.
- British-motorsport register. Forward-looking present tense. Punchy, no filler, \
no bullet-point dumps — flowing analytical prose."""

PRERACE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline":   {"type": "string", "description": "Punchy 4-8 word title framing the race's central strategic question"},
        "grid_story": {"type": "string", "description": "120-200 words: what the grid means strategically — who is out of position, where the pace really is"},
        "the_trade":  {"type": "string", "description": "180-280 words: the compound trade — walk the reader through the formula verdict using the measured deg rates and offsets, and state which stint lengths each compound wins"},
        "race_shape": {"type": "string", "description": "180-280 words: the stop-count call and WHY. Lead with stop_decision.optimal_stops, then decompose stop_decision.crossover — the extra_pit_cost_s of one more stop vs the fresh_rubber_saving_s it buys — to explain why that count wins. Flag any plan's laps_over_cliff. Use stop_decision.sc_flips_call / sc_favored_stops to say whether a Safety Car tips it toward more stops, and track_position_bias for how much staying out is worth here."},
        "the_undercut": {"type": "string", "description": "120-200 words on the undercut vs the overcut, using the undercut object: fresh_gain_per_lap and net_undercut_s (fresh-tyre gain over the window, net of the out-lap), judged against pit_loss_s and the verdict. Say plainly whether teams should pit early to jump rivals (undercut) or hold track position and extend (overcut), and tie it to how hard passing is here."},
        "the_doors":  {"type": "string", "description": "180-300 words: the reversible bets on the table. Use doors.cards (cost_positions of a pit-lane start vs keeping the grid slot, with win/podium odds each way) and doors.expected_movers to argue where grid position is worth defending and where it is a free option to trade for setup. Use overtaking.pass_threshold_s_per_lap as the pace edge needed to pass. Temper the dry door costs with doors.sc_refund (an early-SC discount) and weather_outlook (if rain_risk is above low, the costs shrink). Ground the recovery claims in recovery_prior (how back-half starters actually finished here in recent years, incl. best_recovery). Frame each choice as a 2-way (reversible, bounded downside) or 1-way (irreversible) door."},
        "projection": {"type": "string", "description": "120-220 words: what the model projects from the grid — use long_run_pace to name who is out of position (pace rank vs grid slot) and the projection forecasts (win/podium probabilities) to frame the likely podium; flag the assumptions (start compound, grid spread)"},
        "watch_list": {"type": "string", "description": "80-160 words: the 2-4 unknowns that get filled in during the first stint, and exactly what to watch for each"},
    },
    "required": ["headline", "grid_story", "the_trade", "race_shape", "the_undercut", "the_doors", "projection", "watch_list"],
    "additionalProperties": False,
}


def _long_run_pace(source_sessions: list[dict], curves: dict) -> list[dict]:
    """Fuel- and age-corrected long-run pace per driver from FP/sprint stints
    of >= 6 laps. This is the 'real pace order' that quali can hide."""
    samples: dict[int, list[float]] = {}
    names: dict[int, str] = {}
    used_sessions: dict[int, set] = {}
    for s in source_sessions:
        stype = s.get("session_type", "").lower()
        name = s.get("session_name", "")
        if stype == "qualifying":
            continue
        try:
            laps = get_laps(s["session_key"], HIST_TTL)
            stints = get_stints(s["session_key"], HIST_TTL)
            drivers = get_drivers(s["session_key"], HIST_TTL)
        except Exception:
            continue
        from data.live import get_yellow_laps
        yellows = get_yellow_laps(s["session_key"], HIST_TTL)
        laps_by_driver: dict[int, dict[int, float]] = {}
        for l in laps:
            t = l.get("lap_duration")
            if (t and 55 < t < 200 and not l.get("is_pit_out_lap")
                    and l["lap_number"] not in yellows):
                laps_by_driver.setdefault(l["driver_number"], {})[l["lap_number"]] = t
        for st in stints:
            num = st["driver_number"]
            ls, le = st.get("lap_start") or 1, st.get("lap_end") or 0
            if le - ls + 1 < 6:
                continue
            compound = st.get("compound")
            curve = curves.get(compound)
            # Drop the in-lap (final lap of the stint ends in the pit lane —
            # same exclusion predictor._stint_deg_samples applies).
            stint_laps = [(ln, t) for ln, t in laps_by_driver.get(num, {}).items()
                          if ls < ln < le]
            if len(stint_laps) < 5:
                continue
            # Keep only representative running: cool-down laps, traffic, and
            # one-off slow laps (not caught by the yellow-flag/pit-out filters
            # above — practice is full of them) are all one-sided and slow.
            # Measure against the stint's own best lap, but with a looser
            # tolerance than degradation fitting's DEG_LONGRUN (1.02): that
            # ratio is tuned for isolating a wear SLOPE, where the fitted
            # laps must be nearly flat. Here we want a single pace LEVEL
            # across a whole stint, which legitimately drifts a few percent
            # from tyre wear — DEG_LONGRUN's 1.02 rejected that normal drift
            # too, e.g. it dropped Hamilton from this table entirely at Spain
            # 2026 (down to 10 of 28 drivers) despite him going on to win the
            # race. PACE_ORDER_CLEAN_RATIO=1.10 was checked against that same
            # session: it recovers full-field coverage (25/28) with no
            # reintroduced outliers, whereas 1.15 already re-admits one
            # (a driver's median jumping to an implausible -3.7s/lap).
            ref = min(t for _, t in stint_laps)
            stint_laps = [(ln, t) for ln, t in stint_laps if t <= ref * PACE_ORDER_CLEAN_RATIO]
            if len(stint_laps) < 5:
                continue
            age0 = st.get("tyre_age_at_start") or 0
            for ln, t in stint_laps:
                corrected = t
                if curve and curve.deg_rate:
                    corrected -= curve.deg_rate * (age0 + ln - ls)
                corrected += FUEL_RATE * (ln - ls)  # neutralise fuel burn inside the run
                samples.setdefault(num, []).append(corrected)
            names[num] = drivers.get(num, {}).get("name_acronym", str(num))
            used_sessions.setdefault(num, set()).add(name)

    medians = {n: statistics.median(v) for n, v in samples.items() if len(v) >= 5}
    if not medians:
        return []
    field = statistics.median(medians.values())
    rows = [{"driver_number": n, "acronym": names.get(n, str(n)),
             "pace_delta": round(m - field, 3), "laps": len(samples[n]),
             "sessions": sorted(used_sessions.get(n, []))}
            for n, m in medians.items()]
    rows.sort(key=lambda r: r["pace_delta"])
    for i, r in enumerate(rows, 1):
        r["pace_rank"] = i
    return rows


def _long_run_tables(source_sessions: list[dict]) -> list[dict]:
    """Lap-by-lap long-run boards, one per session — the classic 'Long Runs
    FP2' table: each driver's longest stint (>=6 laps), every lap shown,
    outliers/out-laps marked excluded, and the clean average at the bottom."""
    from data.live import get_yellow_laps
    tables = []
    for s in source_sessions:
        stype = s.get("session_type", "").lower()
        name = s.get("session_name", "")
        is_sprint_race = stype == "race" and "sprint" in name.lower()
        if stype != "practice" and not is_sprint_race:
            continue
        try:
            laps = get_laps(s["session_key"], HIST_TTL)
            stints = get_stints(s["session_key"], HIST_TTL)
            drivers = get_drivers(s["session_key"], HIST_TTL)
        except Exception:
            continue
        yellows = get_yellow_laps(s["session_key"], HIST_TTL)
        laps_by_driver: dict[int, dict[int, dict]] = {}
        for l in laps:
            if l.get("lap_duration"):
                laps_by_driver.setdefault(l["driver_number"], {})[l["lap_number"]] = l

        rows = []
        for st in stints:
            num = st["driver_number"]
            ls, le = st.get("lap_start") or 1, st.get("lap_end") or 0
            if le - ls + 1 < 6:
                continue
            dl = laps_by_driver.get(num, {})
            stint_laps = [(ln, dl[ln]) for ln in range(ls + 1, le + 1) if ln in dl]  # skip out-lap
            times = [l["lap_duration"] for _, l in stint_laps
                     if 55 < l["lap_duration"] < 200]
            if len(times) < 5:
                continue
            med = statistics.median(times)
            cells, clean = [], []
            for ln, l in stint_laps:
                t = l["lap_duration"]
                excluded = (not 55 < t < 200 or l.get("is_pit_out_lap")
                            or ln in yellows or t > med * 1.05)
                cells.append({"t": round(t, 3), "x": bool(excluded)})
                if not excluded:
                    clean.append(t)
            if len(clean) < 4:
                continue
            rows.append({
                "driver_number": num,
                "acronym": drivers.get(num, {}).get("name_acronym", str(num)),
                "team_colour": drivers.get(num, {}).get("team_colour") or "888888",
                "compound": (st.get("compound") or "?")[0],
                "laps": cells,
                "avg": round(sum(clean) / len(clean), 3),
                "clean_laps": len(clean),
            })
        if not rows:
            continue
        # one run per driver: keep their longest (most clean laps)
        best_by_driver: dict[int, dict] = {}
        for r in rows:
            cur = best_by_driver.get(r["driver_number"])
            if cur is None or r["clean_laps"] > cur["clean_laps"]:
                best_by_driver[r["driver_number"]] = r
        table_rows = sorted(best_by_driver.values(), key=lambda r: r["avg"])[:10]
        tables.append({
            "session_key": s["session_key"],
            "session_name": name,
            "drivers": table_rows,
        })
    return tables


def _team_pace(pace_rows: list[dict], grid: list[dict], field_baseline: float) -> list[dict]:
    """Team-level race-sim pace: the faster of each team's two cars from
    _long_run_pace, re-based to the quickest team = 0. A team with no driver
    in pace_rows (no qualifying long run for either car) still appears, with
    no_data=True and null gap fields, rather than silently vanishing from the
    chart — the frontend can show "no data" instead of the field looking one
    team short with no indication why."""
    # Every team on the grid, in first-seen order, with its colour — this is
    # the full roster the output must cover, whether or not pace data exists.
    team_by_acronym: dict[str, str] = {}
    colour_by_team: dict[str, str] = {}
    all_teams: list[str] = []
    for g in grid:
        team, colour = g.get("team"), g.get("team_colour")
        if not team:
            continue
        team_by_acronym[g["acronym"]] = team
        colour_by_team.setdefault(team, colour)
        if team not in all_teams:
            all_teams.append(team)

    best_delta_by_team: dict[str, float] = {}
    for r in pace_rows:
        team = team_by_acronym.get(r["acronym"])
        if not team:
            continue
        cur = best_delta_by_team.get(team)
        if cur is None or r["pace_delta"] < cur:
            best_delta_by_team[team] = r["pace_delta"]

    fastest = min(best_delta_by_team.values()) if best_delta_by_team else None

    rows = []
    for team in all_teams:
        delta = best_delta_by_team.get(team)
        colour = colour_by_team.get(team)
        if delta is None or fastest is None:
            rows.append({"team": team, "team_colour": colour,
                        "gap_s": None, "gap_pct": None, "no_data": True})
            continue
        gap = round(delta - fastest, 3)
        # % back is relative to the fastest team's own predicted lap time,
        # matching how broadcast graphics express a gap as a lap-time fraction.
        fastest_lap = field_baseline + fastest
        pct = round(gap / fastest_lap * 100, 2) if fastest_lap > 0 else 0.0
        rows.append({"team": team, "team_colour": colour,
                    "gap_s": gap, "gap_pct": pct, "no_data": False})
    # Ranked teams first (fastest gap first), no-data teams after, alphabetical.
    rows.sort(key=lambda r: (r["no_data"], r["gap_s"] if r["gap_s"] is not None else 0, r["team"]))
    return rows



# Tolerance for _pit_window, below — deliberately NOT LIVE_MARGIN_S (10s).
# That figure prices a whole extra PIT STOP (~22-28s) against staying out, so
# a 10s budget is right for comparing 1-stop vs 2-stop vs 3-stop. Shifting one
# stop's lap by 1 only changes two stints' wear by a fraction of a second, so
# the same 10s budget lets the window balloon to dozens of laps on any track
# with a flat degradation curve — measured directly: a 44-lap race with a
# near-zero HARD deg rate produced a ~28-lap window that swallowed the entire
# middle stint of a 2-stop plan, visually erasing its colour on the chart.
# PIT_WINDOW_MARGIN_S is sized for the single-stop question instead, and
# PIT_WINDOW_MAX_SHIFT is a hard display cap so no degenerate curve (e.g. a
# compound with no measured wear at all, deg_rate effectively 0) can blow the
# window out no matter how flat the sensitivity genuinely is.
PIT_WINDOW_MARGIN_S = 2.0
PIT_WINDOW_MAX_SHIFT = 3   # laps either side — window is at most 7 laps wide


def _pit_window(seq: list[str], lens: list[int], pit_index: int,
                curves: dict, field_baseline: float, pit_loss: float,
                total_laps: int, margin_s: float = PIT_WINDOW_MARGIN_S,
                max_shift: int = PIT_WINDOW_MAX_SHIFT) -> list[int]:
    """Range of laps [lo, hi] around one pit stop's optimal lap that stays
    within `margin_s` of the strategy's actual time — moving only this stop
    and adjusting its two adjacent stints, all others held fixed — capped at
    `max_shift` laps either side (see module comment above for why)."""
    starts = [0]
    for l in lens[:-1]:
        starts.append(starts[-1] + l)
    boundary = starts[pit_index + 1]
    prev_c, prev_start = seq[pit_index], starts[pit_index]
    next_c = seq[pit_index + 1]
    next_end = starts[pit_index + 2] if pit_index + 2 < len(starts) else total_laps
    base_len_prev = boundary - prev_start
    base_len_next = next_end - boundary
    # optimize_strategy's fallback path (no legal MIN_STINT-respecting plan
    # found) can produce a short final splash stint below MIN_STINT — never
    # from its main search, which always keeps every stint at or above it.
    # Rejecting anything under MIN_STINT unconditionally would reject the
    # BASELINE (shift=0) itself for a strategy shaped like that, returning a
    # zero-width, invisible window instead of a real error. Floor each side at
    # whatever the strategy already committed to, so a deliberate splash can
    # still be probed (just not shrunk any further).
    min_len_prev = min(MIN_STINT, base_len_prev)
    min_len_next = min(MIN_STINT, base_len_next)

    def time_at(shift: int) -> float | None:
        len_prev, len_next = base_len_prev + shift, base_len_next - shift
        if len_prev < min_len_prev or len_next < min_len_next:
            return None
        return (_stint_time(prev_c, 0, len_prev, prev_start, total_laps, 0.0,
                            curves, field_baseline)
                + _stint_time(next_c, 0, len_next, prev_start + len_prev,
                              total_laps, 0.0, curves, field_baseline))

    base = time_at(0)
    lo = hi = 0
    shift = -1
    while shift >= -max_shift:
        t = time_at(shift)
        if t is None or t - base > margin_s:
            break
        lo = shift
        shift -= 1
    shift = 1
    while shift <= max_shift:
        t = time_at(shift)
        if t is None or t - base > margin_s:
            break
        hi = shift
        shift += 1
    # A genuinely zero-width window (a candidate whose tyres are so poorly
    # matched to the stint that even a 1-lap shift blows the margin) renders
    # as an invisible sliver on the Gantt chart, indistinguishable from a
    # rendering bug. Widen by 1 lap for legibility wherever that's still a
    # legal probe, even though it technically exceeds margin_s — this is a
    # display floor, not a claim that the window is genuinely that wide.
    if lo == 0 and hi == 0:
        if time_at(-1) is not None:
            lo = -1
        elif time_at(1) is not None:
            hi = 1
    return [boundary + lo, boundary + hi]


def _quali_speed_sectors(quali_key: int) -> list[dict]:
    """Best sector times and top speeds per driver from qualifying — where
    each lap is won, and who has the straight-line/tow advantage."""
    try:
        laps = get_laps(quali_key, HIST_TTL)
        drivers = get_drivers(quali_key, HIST_TTL)
    except Exception:
        return []
    agg: dict[int, dict] = {}
    for l in laps:
        num = l["driver_number"]
        a = agg.setdefault(num, {"s1": None, "s2": None, "s3": None,
                                 "st_speed": None, "best_lap": None})
        for key, field in [("s1", "duration_sector_1"), ("s2", "duration_sector_2"),
                           ("s3", "duration_sector_3")]:
            v = l.get(field)
            if v and (a[key] is None or v < a[key]):
                a[key] = v
        sp = l.get("st_speed")
        if sp and (a["st_speed"] is None or sp > a["st_speed"]):
            a["st_speed"] = sp
        t = l.get("lap_duration")
        if t and 55 < t < 200 and (a["best_lap"] is None or t < a["best_lap"]):
            a["best_lap"] = t
    rows = []
    for num, a in agg.items():
        if a["best_lap"] is None:
            continue
        theoretical = (round(a["s1"] + a["s2"] + a["s3"], 3)
                       if all(a[k] for k in ("s1", "s2", "s3")) else None)
        rows.append({
            "driver_number": num,
            "acronym": drivers.get(num, {}).get("name_acronym", str(num)),
            "best_lap": round(a["best_lap"], 3),
            "s1": round(a["s1"], 3) if a["s1"] else None,
            "s2": round(a["s2"], 3) if a["s2"] else None,
            "s3": round(a["s3"], 3) if a["s3"] else None,
            "theoretical": theoretical,
            "left_on_table": (round(a["best_lap"] - theoretical, 3)
                              if theoretical else None),
            "top_speed_kmh": a["st_speed"],
        })
    rows.sort(key=lambda r: r["best_lap"])
    return rows[:12]


GRID_SPREAD_S = 1.0   # assumed first-lap spread per grid slot for projection


def _run_projection(grid: list[dict], pace_rows: list[dict], curves: dict,
                    strategies: list[dict], total_laps: int, pit_loss: float,
                    circuit: str, inventory: dict | None = None) -> list:
    """Run the race model from lap 0 for a given grid order and return the full
    field of DriverForecast objects (Monte Carlo already applied). The grid is
    spread at GRID_SPREAD_S per slot to give the track-position anchor something
    to hold on to. Returns [] if the inputs are insufficient."""
    if not grid or not strategies:
        return []
    pace_by_num = {r["driver_number"]: r for r in pace_rows}
    start_c = strategies[0]["start_compound"]
    serialised, pace_model = [], {}
    for g in grid:
        # Prefer the grid's own driver number. Resolving it from pace_rows
        # instead silently dropped every car with no long-run data onto a
        # placeholder id, which then matched no tyre inventory — so those cars
        # were planned onto compounds they did not have.
        num = g.get("driver_number")
        if num is None:
            num = next((r["driver_number"] for r in pace_rows
                        if r["acronym"] == g["acronym"]), None)
        if num is None:
            num = g["position"] * 1000  # placeholder for cars with no data at all
        pr = pace_by_num.get(num)
        # Start on the planned compound only if this driver still has one.
        stock = (inventory or {}).get(num)
        own_start = start_c
        if stock and stock.get(start_c, 0) < 1:
            own_start = next((c for c in ("MEDIUM", "HARD", "SOFT")
                              if stock.get(c, 0) >= 1), start_c)
        serialised.append({
            "driver_number": num, "acronym": g["acronym"],
            "position": g["position"], "compound": own_start, "tyre_age": 0,
            "gap_to_leader": f"+{(g['position'] - 1) * GRID_SPREAD_S:.3f}",
            "interval": f"+{GRID_SPREAD_S:.3f}" if g["position"] > 1 else "LEADER",
            "retired": False, "compounds_used": [own_start], "current_lap": 0,
        })
        pace_model[num] = DriverPace(
            driver_number=num, acronym=g["acronym"],
            pace_median=0.0, pace_std=0.3,
            pace_delta=pr["pace_delta"] if pr else 0.0,
            laps_counted=pr["laps"] if pr else 0)
    # Each car is planned against its own garage: subtract the set it starts on.
    inv_left = None
    if inventory:
        inv_left = {}
        for d in serialised:
            stock = inventory.get(d["driver_number"])
            if stock:
                inv_left[d["driver_number"]] = {
                    c: (n - 1 if c == d["compound"] else n) for c, n in stock.items()}
    return simulate_race(serialised, 0, total_laps, curves, pace_model, [],
                         pit_loss=pit_loss,
                         track_position_weight=track_position_weight(circuit),
                         inventory=inv_left, circuit=circuit)


def _project_race(grid: list[dict], pace_rows: list[dict], curves: dict,
                  strategies: list[dict], total_laps: int, pit_loss: float,
                  circuit: str, inventory: dict | None = None) -> dict | None:
    """Lap-0 projection for the display: top-10 forecasts with win/podium odds."""
    forecasts = _run_projection(grid, pace_rows, curves, strategies,
                                total_laps, pit_loss, circuit, inventory)
    if not forecasts:
        return None
    return {
        "grid_spread_assumption_s": GRID_SPREAD_S,
        "start_compound_assumption": strategies[0]["start_compound"],
        "forecasts": [forecast_to_dict(f) for f in forecasts[:10]],
    }


BATTLE_WINDOW_LAPS = 5   # laps a wheel-to-wheel fight realistically lasts before
                         # tyre delta / DRS train / traffic resolves it


def _overtaking_cost(total_laps: int, circuit: str) -> dict:
    """Model-implied overtaking difficulty: the sustained race-pace edge (s/lap)
    a following car needs to convert a 1s gap into a pass within a short battle
    window. Derived analytically from the sim's track-position blend — for two
    equal-strategy cars the trailing car's projected finish drops below the
    leader's once its per-lap pace advantage d satisfies gap < (1-w)*d*window,
    i.e. d > gap / ((1-w) * window). Street circuits (higher w) resist hardest.
    This is a model quantity, not an empirical DRS measurement."""
    is_street = is_street_circuit(circuit)
    w = track_position_weight(circuit)
    gap = 1.0
    threshold = gap / ((1 - w) * BATTLE_WINDOW_LAPS)
    return {
        "track_position_weight": w,
        "battle_window_laps": BATTLE_WINDOW_LAPS,
        "gap_assumed_s": gap,
        "pass_threshold_s_per_lap": round(threshold, 2),
        "difficulty": "hard" if is_street else "moderate",
        "note": (f"Model-implied: a following car needs about {threshold:.2f} s/lap "
                 f"of sustained race pace to convert a {gap:.0f}s gap into a pass "
                 f"within ~{BATTLE_WINDOW_LAPS} laps here (track-position weight "
                 f"{w}). Higher means harder to overtake."),
    }


EARLY_SC_LAPS = 12   # "early" = roughly the first stint window where a stop
                     # taken under neutralisation is cheapest


def _sc_refund(total_laps: int, circuit: str, pit_loss: float) -> dict:
    """The newsletter's 'does an early yellow refund the penalty?' A full Safety
    Car saves ~55% of a green-flag pit loss (matches simulate_race's 0.45 SC pit
    multiplier), and bunching the field also claws back time lost starting out of
    position. Prices the expected refund from the per-circuit SC rate over the
    opening laps — the upside that makes a pit-lane/penalty start a better bet
    than the raw grid-slot cost suggests."""
    early = min(EARLY_SC_LAPS, total_laps)
    p_early = sc_probability([], 0, total_laps, circuit, window_laps=early)
    refund_s = round(0.55 * pit_loss, 1)   # a stop taken under SC vs at green-flag speed
    return {
        "early_window_laps": early,
        "p_sc_in_window": p_early,
        "full_refund_s": refund_s,
        "expected_refund_s": round(p_early * refund_s, 1),
        "note": (f"Model-implied: ~{p_early*100:.0f}% chance of a Safety Car in the "
                 f"first {early} laps here. If it falls, a stop taken under it is "
                 f"worth about {refund_s}s versus green — the early-yellow refund "
                 f"that partly offsets a penalty/pit-lane start."),
    }


def _grid_with_move(grid: list[dict], acronym: str, new_position: int) -> list[dict] | None:
    """Return a copy of the grid with `acronym` relocated to `new_position`
    (1-indexed) and every slot renumbered — used to model counterfactual starts
    such as a pit-lane / back-of-grid penalty."""
    target = next((dict(g) for g in grid if g["acronym"] == acronym), None)
    if target is None:
        return None
    others = [dict(g) for g in grid if g["acronym"] != acronym]
    pos = max(1, min(new_position, len(grid)))
    ordered = others[:pos - 1] + [target] + others[pos - 1:]
    for i, g in enumerate(ordered, 1):
        g["position"] = i
    return ordered


def _door_cards(grid: list[dict], pace_rows: list[dict], curves: dict,
                strategies: list[dict], total_laps: int, pit_loss: float,
                circuit: str) -> dict | None:
    """The newsletter's 'doors': quantify the cost of a starting position. From
    the base projection, surface who the model expects to move (pace out of line
    with grid slot), then run counterfactual pit-lane starts for the front-runner
    and the fastest out-of-position car to price the reversible 'start from the
    back for setup freedom' bet."""
    base = _run_projection(grid, pace_rows, curves, strategies,
                           total_laps, pit_loss, circuit)
    if not base:
        return None
    by_acr = {f.acronym: f for f in base}

    movers = []
    for g in grid:
        f = by_acr.get(g["acronym"])
        if not f or not f.mean_finish:
            continue
        movers.append({
            "acronym": g["acronym"],
            "grid_position": g["position"],
            "expected_finish": f.mean_finish,
            "delta_vs_grid": round(g["position"] - f.mean_finish, 1),  # + = gains places
        })
    gainers = sorted((m for m in movers if m["delta_vs_grid"] > 0.5),
                     key=lambda m: -m["delta_vs_grid"])
    losers = sorted((m for m in movers if m["delta_vs_grid"] < -0.5),
                    key=lambda m: m["delta_vs_grid"])

    # Door subjects: the front-runner (what a pit-lane start would cost) and the
    # fastest out-of-position car (its recovery ceiling from the grid).
    subjects = []
    if grid:
        subjects.append(grid[0]["acronym"])
    if gainers and gainers[0]["acronym"] not in subjects:
        subjects.append(gainers[0]["acronym"])

    back = len(grid)  # pit-lane start ≈ behind the last grid slot
    cards = []
    for acr in subjects:
        bf = by_acr.get(acr)
        gpos = next((g["position"] for g in grid if g["acronym"] == acr), None)
        if bf is None or gpos is None:
            continue
        moved = _grid_with_move(grid, acr, back)
        cf = None
        if moved:
            cf_forecasts = _run_projection(moved, pace_rows, curves, strategies,
                                           total_laps, pit_loss, circuit)
            cf = next((f for f in cf_forecasts if f.acronym == acr), None)
        card = {
            "acronym": acr,
            "grid_position": gpos,
            "keep_grid": {
                "start": gpos,
                "expected_finish": bf.mean_finish,
                "range_p05_p95": list(bf.position_range),
                "win": bf.win_probability,
                "podium": bf.podium_probability,
                "points": bf.points_probability,
            },
            "pit_lane_start": None,
            "cost_positions": None,
            "reversible": True,   # bounded downside, setup freedom as upside — a 2-way door
        }
        if cf is not None:
            card["pit_lane_start"] = {
                "start": back,
                "expected_finish": cf.mean_finish,
                "range_p05_p95": list(cf.position_range),
                "win": cf.win_probability,
                "podium": cf.podium_probability,
                "points": cf.points_probability,
            }
            card["cost_positions"] = round(cf.mean_finish - bf.mean_finish, 1)
        cards.append(card)

    return {
        "expected_movers": {"gainers": gainers[:5], "losers": losers[:5]},
        "cards": cards,
        "sc_refund": _sc_refund(total_laps, circuit, pit_loss),
        "note": ("expected_movers ranks cars by projected places gained/lost vs "
                 "their grid slot. Each card prices a pit-lane start against "
                 "keeping the grid slot; cost_positions is the expected finishing "
                 "positions surrendered for that reversible bet. sc_refund is the "
                 "early-Safety-Car discount on that cost."),
    }


WET_PRONE_CIRCUITS = {"spa", "francorchamps", "interlagos", "sao paulo", "suzuka",
                      "zandvoort", "hungaroring", "shanghai"}


BACK_GRID_THRESHOLD = 11   # "back half" — where recovery drives start


def _recovery_prior(circuit: str, meeting_key, max_races: int = 3) -> dict | None:
    """The newsletter's empirical grounding ('82 penalty starts, mapped'). How
    did cars starting in the back half actually finish at THIS circuit in recent
    years? Grounds the door-card projections in history. Best-effort and bounded
    to a few past races; the caller swallows failures so a rate-limit just drops
    the section rather than breaking the briefing."""
    try:
        races = _cached_get(f"circuit_races:{circuit}", "sessions", HIST_TTL,
                            circuit_short_name=circuit, session_type="Race")
    except Exception:
        return None
    races = [r for r in races if r.get("meeting_key") != meeting_key and r.get("session_key")]
    races.sort(key=lambda s: s.get("date_start", ""), reverse=True)

    samples, years = [], []
    for r in races[:max_races]:
        try:
            st = build_state(r["session_key"], include_locations=False, session=r)
        except Exception:
            continue
        years.append(r.get("year"))
        for d in st.values():
            if d.grid_position and d.position and not d.retired \
                    and d.grid_position >= BACK_GRID_THRESHOLD:
                samples.append((d.grid_position, d.position, d.acronym, r.get("year")))
    if not samples:
        return None

    best = max(samples, key=lambda x: x[0] - x[1])
    return {
        "circuit": circuit,
        "races_sampled": [y for y in years if y],
        "sample_size": len(samples),
        "back_grid_threshold": BACK_GRID_THRESHOLD,
        "avg_finish_from_back": round(sum(f for _, f, _, _ in samples) / len(samples), 1),
        "avg_positions_gained": round(sum(g - f for g, f, _, _ in samples) / len(samples), 1),
        "best_recovery": {"acronym": best[2], "year": best[3],
                          "grid": best[0], "finish": best[1], "gained": best[0] - best[1]},
        "note": (f"History at {circuit}: cars starting P{BACK_GRID_THRESHOLD}+ finished "
                 f"on average around P{round(sum(f for _,f,_,_ in samples)/len(samples),1)} "
                 f"across {len(set(y for y in years if y))} recent race(s) — the empirical "
                 f"check on the model's recovery projections."),
    }


def _weather_outlook(sources: list[dict], circuit: str) -> dict:
    """A rain PRIOR, not a forecast (OpenF1 only exposes observed weather). Flags
    a wet-prone circuit and whether any practice/quali session actually saw rain,
    and spells out what a wet race does to the door economics — it compresses the
    field and collapses the pace edge needed to overtake, so grid position matters
    far less and a setup gamble from the back gets cheaper."""
    cl = circuit.lower()
    wet_prone = any(w in cl for w in WET_PRONE_CIRCUITS)
    rain_in_practice = False
    temps = []
    for s in sources:
        try:
            w = get_weather_summary(s["session_key"], HIST_TTL)
        except Exception:
            continue
        if not w:
            continue
        if w.get("rainfall"):
            rain_in_practice = True
        if w.get("track_temp_avg"):
            temps.append(w["track_temp_avg"])
    risk = "high" if rain_in_practice else "elevated" if wet_prone else "low"
    return {
        "rain_risk": risk,
        "rain_seen_in_practice": rain_in_practice,
        "wet_prone_circuit": wet_prone,
        "track_temp_range_c": [round(min(temps), 1), round(max(temps), 1)] if temps else None,
        "note": (
            "Rain already fell this weekend — treat the dry-run pace order as provisional."
            if rain_in_practice else
            f"{circuit} has a high historical wet-race rate; keep rain live as a risk."
            if wet_prone else
            "No wet signal — dry running expected."),
        "implication": (
            "A wet race compresses the field and collapses the pace edge needed to "
            "overtake, so grid position matters far less and a gamble from the back "
            "gets cheaper — the door costs above are dry-weather numbers."
            if risk != "low" else
            "Dry expected, so the door costs above hold their value."),
    }


def _meeting_sessions(meeting_key: int) -> list[dict]:
    return sorted(
        _cached_get(f"meeting_sessions:{meeting_key}", "sessions", HIST_TTL,
                    meeting_key=meeting_key),
        key=lambda s: s.get("date_start", ""))


def _completed(sessions: list[dict]) -> list[dict]:
    from dateutil.parser import parse as parse_dt
    now = datetime.now(timezone.utc)
    out = []
    for s in sessions:
        end = s.get("date_end")
        if not end:
            continue
        end_dt = parse_dt(end)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt < now:
            out.append(s)
    return out


def _is_grand_prix(s: dict) -> bool:
    return (s.get("session_type", "").lower() == "race"
            and "sprint" not in s.get("session_name", "").lower())


def _trade_table(curves: dict) -> dict:
    """The newsletter's 'trade, calculated': for each softer/harder pair, the
    max tolerable deg gap (s/lap) is 2*offset/N. Includes measured values and
    the break-even stint length."""
    c = curves_to_dict(curves)
    ns = [15, 20, 25, 30]
    offsets = [0.30, 0.45, 0.60]
    pairs = []
    for soft, hard in [("SOFT", "MEDIUM"), ("MEDIUM", "HARD"), ("SOFT", "HARD")]:
        cs, ch = c.get(soft), c.get(hard)
        if not cs or not ch or not cs["baseline"] or not ch["baseline"]:
            continue
        offset = round(ch["baseline"] - cs["baseline"], 3)   # harder tyre's fresh-pace deficit
        gap = round(cs["deg_rate"] - ch["deg_rate"], 4)      # softer tyre's deg excess
        breakeven = round(2 * offset / gap, 1) if gap > 0 and offset > 0 else None
        pairs.append({
            "softer": soft, "harder": hard,
            "offset_s_per_lap": offset,
            "deg_gap_s_per_lap": gap,
            "breakeven_stint_laps": breakeven,
            "verdict": (f"{soft} wins a final stint up to ~{breakeven:.0f} laps"
                        if breakeven and 0 < breakeven < 100
                        else (f"{soft} wins on pure pace (no deg penalty measured)"
                              if offset > 0 and gap <= 0 else f"{hard} preferred at any length")),
        })
    return {
        "formula": "softer wins the final stint while degS - degH < 2 x offset / N",
        "lookup_table": {"laps_to_flag": ns, "offsets": offsets,
                         "thresholds": [[round(2 * o / n, 3) for o in offsets] for n in ns]},
        "pairs": pairs,
    }


OUT_LAP_PENALTY_S = 1.0   # cold fresh tyres lose ~1s on the out-lap
UNDERCUT_WINDOW = 2       # laps a rival typically takes to cover a stop


def _undercut_power(curves: dict, field_baseline: float, pit_loss: float,
                    total_laps: int, circuit: str) -> dict | None:
    """How hard the undercut bites here. When a car pits, its fresh tyre gains on
    the rival's worn tyre over the ~2 laps before the rival can cover — net of the
    cold out-lap. Positive = pitting first jumps rivals (an undercut track); near
    zero/negative = track position holds and the overcut (extending) is the play.
    Compared against the pit loss and this track's overtaking difficulty."""
    compound = next((c for c in ("MEDIUM", "HARD", "SOFT")
                     if c in curves and curves[c].baseline > 0), None)
    if not compound:
        return None
    deg = curves[compound].deg_rate
    # the rival is deep in a stint at the moment of an undercut
    rival_age = min(_cliff_life(compound, deg), max(8, total_laps // 3))
    fresh_gain = 0.0
    for i in range(UNDERCUT_WINDOW):
        worn = _lap_t(compound, rival_age + i, 0.0, curves, field_baseline)
        new = _lap_t(compound, 1 + i, 0.0, curves, field_baseline)
        fresh_gain += worn - new
    net = round(fresh_gain - OUT_LAP_PENALTY_S, 2)
    verdict = "undercut" if net > 0.4 else "overcut" if net < -0.2 else "neutral"
    is_street = is_street_circuit(circuit)
    play = {
        "undercut": "pitting first jumps rivals — expect teams to trigger stops early to cover",
        "overcut":  "track position holds — the overcut (staying out on live tyres) is the play",
        "neutral":  "undercut and overcut roughly balance — the stop is a coin-flip on traffic",
    }[verdict]
    return {
        "compound": compound,
        "rival_tyre_age": rival_age,
        "fresh_gain_per_lap": round(fresh_gain / UNDERCUT_WINDOW, 2),
        "out_lap_penalty_s": OUT_LAP_PENALTY_S,
        "window_laps": UNDERCUT_WINDOW,
        "net_undercut_s": net,
        "pit_loss_s": pit_loss,
        "verdict": verdict,
        "note": (f"A fresh {compound} gains ~{fresh_gain:.1f}s over the {UNDERCUT_WINDOW} "
                 f"laps before a rival covers (vs a {rival_age}-lap tyre), minus the "
                 f"{OUT_LAP_PENALTY_S:.0f}s cold out-lap → net {net:+.1f}s: {play}. "
                 + ("Tight circuit — the undercut is decisive since you can't pass on track."
                    if is_street else
                    "Overtaking is workable here, so track position matters a little less.")),
    }


def _stop_decision(strategies: list[dict], curves: dict, pit_loss: float,
                   total_laps: int, circuit: str, sc_prob: float) -> dict | None:
    """Why the optimal stop count is what it is. Decomposes the gap between the
    best plan and the next-best into the extra stop's pit cost vs the fresh-rubber
    it buys, flags cliff exposure per plan, and shows whether a Safety Car (which
    makes an extra stop cheap) would flip the call."""
    if not strategies:
        return None

    def laps_over_cliff(seq, lengths):
        over = 0
        for comp, length in zip(seq, lengths):
            deg = curves[comp].deg_rate if comp in curves and curves[comp].baseline > 0 else 0.03
            if length > _cliff_life(comp, deg):
                over += length - _cliff_life(comp, deg)
        return over

    diag = [{
        "stops": s["stops"],
        "sequence": s["compound_sequence"],
        "time_delta": s["time_delta"],
        "max_stint": max(s["stint_lengths"]),
        "laps_over_cliff": laps_over_cliff(s["compound_sequence"], s["stint_lengths"]),
        "pit_time_cost": round(s["stops"] * pit_loss, 1),
    } for s in strategies]

    best = strategies[0]
    # The "crossover" comparison below is about extra STOPS, so runner must be
    # the fastest candidate at a genuinely different stop count — not just
    # strategies[1], which can now be another candidate at the SAME stop
    # count (e.g. a Soft-start alternative to the best Medium-start 1-stop)
    # now that every viable (stops, start_compound) combo is kept.
    runner = next((s for s in strategies[1:] if s["stops"] != best["stops"]), None)

    # a Safety Car refunds ~55% of an extra stop's pit loss; rank on expected cost
    sc_ranked = sorted(strategies,
                       key=lambda s: s["total_time"] - s["stops"] * pit_loss * 0.55 * sc_prob)
    sc_favored = sc_ranked[0]["stops"]

    crossover = None
    if runner:
        # best is always the faster/chosen plan by construction (strategies
        # is sorted ascending by total_time), but it isn't always the FEWER-
        # stop one — with every (stops, start_compound) combo now kept as its
        # own candidate, the fastest plan overall is sometimes the one with
        # MORE stops (its fresher rubber outweighs the extra pit time). Work
        # out which of the two actually carries the extra stop(s) rather than
        # assuming it's always runner, or the sign comes out backwards.
        if best["stops"] > runner["stops"]:
            more_stops_plan, fewer_stops_plan = best, runner
        else:
            more_stops_plan, fewer_stops_plan = runner, best
        extra_stops = more_stops_plan["stops"] - fewer_stops_plan["stops"]
        pit_cost = round(extra_stops * pit_loss, 1)
        time_gap = round(more_stops_plan["total_time"] - fewer_stops_plan["total_time"], 1)
        # more_stops_plan paid pit_cost extra in the pits; whatever it's
        # ahead/behind by beyond that is what its fresher rubber actually won
        # or clawed back.
        crossover = {
            "best_stops": best["stops"],
            "runner_stops": runner["stops"],
            "margin_s": runner["time_delta"],
            "more_stops": more_stops_plan["stops"],
            "fewer_stops": fewer_stops_plan["stops"],
            "extra_pit_cost_s": pit_cost,
            "fresh_rubber_saving_s": round(pit_cost - time_gap, 1),
            "extra_stop_worth_it": more_stops_plan is best,
        }

    is_street = is_street_circuit(circuit)
    return {
        "optimal_stops": best["stops"],
        "candidates": diag,
        "crossover": crossover,
        "sc_probability": sc_prob,
        "sc_favored_stops": sc_favored,
        "sc_flips_call": sc_favored != best["stops"],
        "track_position_bias": "high" if is_street else "moderate",
        "note": ("The optimal stop count balances pit-lane time against tyre life: "
                 "each extra stop costs a pit loss but buys younger, faster rubber "
                 "and dodges the cliff. A Safety Car cuts the pit cost ~55%, which "
                 "can flip the call toward more stops."),
    }


def _prerace_sources(meeting_key: int) -> list[dict]:
    """The completed, pre-GP sessions this briefing is built from — cheap
    (one cached /sessions lookup), so the cache check in get_prerace_briefing
    can call this without paying for the rest of the pipeline."""
    sessions = _meeting_sessions(meeting_key)
    if not sessions:
        raise ValueError("unknown meeting")
    completed = _completed(sessions)
    sources = [s for s in completed if not _is_grand_prix(s)]
    if not sources:
        raise ValueError("no completed sessions for this meeting yet — check back after FP1")
    return sources


def build_prerace_data(meeting_key: int, total_laps: int | None = None) -> dict:
    sessions = _meeting_sessions(meeting_key)
    sources = _prerace_sources(meeting_key)

    race = next((s for s in sessions if _is_grand_prix(s)), None)
    meta = race or sources[-1]
    # circuit_short_name can be missing on the chosen session; take it from any
    # session in the meeting that has one, so total_laps never silently falls
    # back to DEFAULT_LAPS (which shoved every stop to the end of a too-long race).
    circuit = (meta.get("circuit_short_name")
               or next((s.get("circuit_short_name") for s in sessions
                        if s.get("circuit_short_name")), ""))
    if total_laps is None:
        total_laps = CIRCUIT_LAPS.get(circuit.lower(), DEFAULT_LAPS)

    is_sprint_weekend = any("sprint" in s.get("session_name", "").lower()
                            and "qualifying" not in s.get("session_name", "").lower()
                            for s in sessions)

    # ── deg curves: FPs as prior, sprint race (if run) as ground truth ──────
    fp_names = ["FP1", "FP2", "FP3"]
    fp_i = 0
    fp_data = []
    sprint_key = None
    for s in sources:
        stype = s.get("session_type", "").lower()
        name = s.get("session_name", "").lower()
        try:
            if stype == "practice" and fp_i < 3:
                fp_data.append((fp_names[fp_i],
                                get_laps(s["session_key"], HIST_TTL),
                                get_stints(s["session_key"], HIST_TTL)))
                fp_i += 1
            elif stype == "race" and "sprint" in name:
                sprint_key = s["session_key"]
                fp_data.append(("RACE",   # sprint IS race-condition data — max weight
                                get_laps(s["session_key"], HIST_TTL),
                                get_stints(s["session_key"], HIST_TTL)))
        except Exception:
            pass
    if not fp_data:
        raise ValueError("no usable practice/sprint data yet")
    curves = build_deg_curves(fp_data)

    # ── grid from qualifying (fall back to latest session order) ────────────
    quali = next((s for s in reversed(sources)
                  if s.get("session_type", "").lower() == "qualifying"
                  and "sprint" not in s.get("session_name", "").lower()), None)
    grid_source = quali or sources[-1]
    grid_state = build_state(grid_source["session_key"], include_locations=False,
                             session=grid_source)
    grid = [
        {"position": d.position, "acronym": d.acronym, "team": d.team,
         "driver_number": d.driver_number,
         "team_colour": d.team_colour, "gap": d.gap_to_leader}
        for d in sorted(grid_state.values(),
                        key=lambda d: (d.position is None, d.position or 99))
        if d.position
    ][:20]

    # ── paper strategies: best plan at EACH stop count ───────────────────────
    # A single-car minimum-time optimum is a coarse integer and tends to
    # under-stop vs real races (race-average deg is depressed by tyre
    # management). So rather than show one "answer", show the best 1-, 2- and
    # 3-stop plans side by side with time deltas — the reader sees that the
    # multi-stop options are usually within a few seconds, which is exactly
    # why teams run them once traffic and undercut are in play.
    baselines = [c.baseline for c in curves.values() if c.baseline > 0]
    field_baseline = statistics.median(baselines) if baselines else 90.0
    pit_loss = get_avg_pit_loss(sprint_key, HIST_TTL) if sprint_key else PIT_LOSS
    # ── tyre inventory: what the top 10 actually hold ────────────────────────
    inventory_summary = None
    try:
        drivers_raw = get_drivers(grid_source["session_key"], HIST_TTL)
        stints_by_session = []
        session_is_qualifying = []
        for s in sources:
            try:
                stints_by_session.append(get_stints(s["session_key"], HIST_TTL))
                session_is_qualifying.append(
                    s.get("session_type", "").lower() == "qualifying")
            except Exception:
                pass
        top10 = [g for g in grid[:10]]
        top10_nums = [d.driver_number for d in grid_state.values()
                      if d.position and d.position <= 10]
        # Grid position <= 10 is the best Q3-participation proxy this data
        # gives us — real Q3 entry can differ (grid penalties etc.) but this
        # is what's actually observable pre-race.
        invs = {i.driver_number: i for i in
                compute_inventory(stints_by_session, drivers_raw, is_sprint_weekend,
                                  q3_drivers=set(top10_nums),
                                  session_is_qualifying=session_is_qualifying)}
        rows = [invs[n] for n in top10_nums if n in invs]
        if rows:
            inventory_summary = {
                "top10_with_new_hard":   sum(1 for i in rows if i.remaining("HARD") >= 1),
                "top10_with_new_medium": sum(1 for i in rows if i.remaining("MEDIUM") >= 1),
                "top10_with_new_soft":   sum(1 for i in rows if i.remaining("SOFT") >= 1),
                "top10_count": len(rows),
            }
        # Full-field breakdown for the "tyres available" chart, grid order.
        # DriverInventory.reconciled() does the heavy lifting: per compound,
        # each opened set is classified by how many laps it actually ran —
        # short (Qualifying-style banker-lap stints) stay "used" and
        # available, long (Practice-style runs) are discarded from
        # availability entirely — then subtracted from the full weekend
        # allocation (see engine.tyre_inventory module docstring).
        for g in grid:
            inv = invs.get(g["driver_number"])
            if inv:
                g["tyres"] = inv.reconciled()
    except Exception:
        pass

    # What the field can actually fit. Pure lap-time optimisation recommends
    # Softs the garage no longer has: after qualifying most drivers hold new
    # Hards and Mediums but few new Softs, which is why real strategies are
    # Medium/Hard. Take the field's median remaining sets as the stock a
    # representative car is working with.
    field_stock = None
    driver_stock = None
    try:
        if rows:
            # total_held (new+used), not remaining (new-only): sets of the
            # same dry-weather spec may be mixed after Qualifying (B6.3.3),
            # so a used set is just as fittable for the race as a new one.
            # Gating on new-only stock undercounts what's actually startable
            # — by race day most of a car's stock IS used sets, not new
            # ones, and gating on remaining() alone could leave every
            # compound showing zero median stock, so the search finds no
            # legal strategy at all.
            field_stock = {c: int(statistics.median([i.total_held(c) for i in rows]))
                           for c in ("SOFT", "MEDIUM", "HARD")}
        if invs:
            # Per-car stock for the projection: a driver who saved a set is not
            # the same as a team-mate who burned theirs in Q3.
            driver_stock = {n: {c: i.total_held(c) for c in ("SOFT", "MEDIUM", "HARD")}
                            for n, i in invs.items()}
    except Exception:
        pass

    # Every legal (stop count x starting compound) combination is kept as its
    # own candidate — not just the fastest per stop count. A pure time
    # optimum picks one "answer", but real strategy calls are a genuine
    # choice among several plans that are all close (Soft-start vs
    # Medium-start 1-stops, etc.); showing only the single best per stop
    # count was throwing away exactly that comparison.
    strategies = []
    seen_signatures: set[tuple] = set()
    for stops in (1, 2, 3):
        for start_c in DRY:
            if start_c not in curves or not curves[start_c].baseline:
                continue
            # The car has to start on a set it actually holds. Without this the
            # sweep opens on a Soft at tracks where the field has none left.
            if field_stock is not None and field_stock.get(start_c, 0) < 1:
                continue
            strat = optimize_strategy(0, total_laps, start_c, 0, 0.0, curves,
                                      field_baseline, pit_loss,
                                      needs_compound_change=True,
                                      force_stops=stops,
                                      forbid_repeat_compound=True,
                                      available=(dict(field_stock,
                                                      **{start_c: field_stock.get(start_c, 0) - 1})
                                                 if field_stock else None))
            if len(strat.pits_remaining) != stops:
                continue   # no legal plan at this stop count
            pits = strat.pits_remaining
            seq = [start_c] + [p.compound for p in pits]
            sig = (stops, tuple(seq))
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)
            pit_laps = [p.lap for p in pits]
            bounds = [0] + pit_laps + [total_laps]
            stint_lengths = [bounds[i + 1] - bounds[i] for i in range(len(seq))]
            pit_windows = [_pit_window(seq, stint_lengths, i, curves, field_baseline,
                                       pit_loss, total_laps)
                          for i in range(len(pit_laps))]
            strategies.append({
                "start_compound": start_c,
                "stops": stops,
                "compound_sequence": seq,
                "pit_laps": pit_laps,
                "pit_windows": pit_windows,
                "stint_lengths": stint_lengths,
                "total_time": strat.total_time_from_now,
            })
    strategies.sort(key=lambda s: s["total_time"])
    strategies = strategies[:5]   # top 5 candidates, fastest first
    best_stops = strategies[0]["stops"] if strategies else 1
    for s in strategies:
        s["time_delta"] = round(s["total_time"] - strategies[0]["total_time"], 1)
        # Candidates are generated at a forced 1, 2 and 3 stops, so a plan that
        # is nowhere near the optimum still appears in the table. Say plainly
        # which ones are actually on the table: a deficit inside a stop's worth
        # of noise is live, and a bigger one is only reachable if a
        # neutralisation refunds the extra stops (measured at (1-SC_PIT_FACTOR)
        # of the pit loss each). Anything beyond that is not a real option.
        extra_stops = max(0, s["stops"] - best_stops)
        sc_refund = round(extra_stops * (1 - SC_PIT_FACTOR) * pit_loss, 1)
        s["sc_refund_s"] = sc_refund
        if s["time_delta"] <= LIVE_MARGIN_S:
            s["viability"] = "in play"
        elif s["time_delta"] <= sc_refund + LIVE_MARGIN_S:
            s["viability"] = "needs a Safety Car"
        else:
            s["viability"] = "not on the table"

    sc_prob = sc_probability([], 0, total_laps, circuit)

    # ── long-run pace order, quali sectors, lap-0 projection ────────────────
    pace_rows = _long_run_pace(sources, curves)
    grid_pos_by_acr = {g["acronym"]: g["position"] for g in grid}
    for r in pace_rows:
        gp = grid_pos_by_acr.get(r["acronym"])
        r["grid_position"] = gp
        r["out_of_position"] = (gp - r["pace_rank"]) if gp else None

    sectors = _quali_speed_sectors(grid_source["session_key"]) \
        if quali else []

    projection = None
    try:
        projection = _project_race(grid, pace_rows, curves, strategies,
                                   total_laps, pit_loss, circuit,
                                   inventory=driver_stock)
    except Exception:
        pass

    doors = None
    try:
        doors = _door_cards(grid, pace_rows, curves, strategies,
                            total_laps, pit_loss, circuit)
    except Exception:
        pass
    overtaking = _overtaking_cost(total_laps, circuit)

    recovery_prior = None
    try:
        recovery_prior = _recovery_prior(circuit, meeting_key)
    except Exception:
        pass

    undercut = _undercut_power(curves, field_baseline, pit_loss, total_laps, circuit)
    stop_decision = _stop_decision(strategies, curves, pit_loss, total_laps, circuit, sc_prob)

    return {
        "meeting": {
            "meeting_key":  meeting_key,
            "country_name": meta.get("country_name"),
            "circuit":      circuit,
            "year":         meta.get("year"),
            "race_date":    race.get("date_start") if race else None,
            "total_laps_assumed": total_laps,
            "sprint_weekend": is_sprint_weekend,
        },
        "sources": [{"session_key": s["session_key"], "name": s.get("session_name")}
                    for s in sources],
        "grid": grid,
        "grid_source": grid_source.get("session_name"),
        "deg_curves": curves_to_dict(curves),
        "trade": _trade_table(curves),
        "strategies": strategies,
        "undercut": undercut,
        "stop_decision": stop_decision,
        "pit_loss": pit_loss,
        "pit_loss_source": "sprint_measured" if sprint_key else "default",
        "sc_probability": sc_prob,
        "long_run_pace": pace_rows,
        "team_pace": _team_pace(pace_rows, grid, field_baseline),
        "long_run_tables": _long_run_tables(sources),
        "quali_sectors": sectors,
        "projection": projection,
        "doors": doors,
        "overtaking": overtaking,
        "weather_outlook": _weather_outlook(sources, circuit),
        "recovery_prior": recovery_prior,
        "weather_latest": get_weather_summary(sources[-1]["session_key"], HIST_TTL),
        "inventory": inventory_summary,
        "unknowns": [
            {"name": "true race-fuel deg", "watch": "first Soft/Medium runner's fade after ~10 laps vs the practice deg rate"},
            {"name": "Hard fresh pace", "watch": "first Hard runner's opening 3 flying laps set the real offset"},
            {"name": "Safety Car timing", "watch": f"a stop under SC costs roughly half the {pit_loss}s green-flag loss"},
        ],
    }


def _prerace_cache_path(meeting_key: int) -> str:
    return os.path.join(BRIEFING_DIR, f"prerace_{meeting_key}.json")


def get_prerace_briefing(meeting_key: int, total_laps: int | None = None,
                         regenerate: bool = False) -> dict:
    path = _prerace_cache_path(meeting_key)
    # Cheap freshness check first: which sessions is a from-scratch build for
    # this meeting keyed on right now. Only if that misses do we pay for the
    # full pipeline (strategy search + Monte Carlo projection + door cards)
    # below — a cache hit used to run all of that just to throw it away.
    source_keys = [s["session_key"] for s in _prerace_sources(meeting_key)]

    if not regenerate and os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        # regenerate when a new session completed OR the pack shape changed
        if (cached.get("source_keys") == source_keys and cached.get("narrative")
                and cached.get("pack_version") == PACK_VERSION):
            return cached

    pack = build_prerace_data(meeting_key, total_laps)
    narrative = generate_structured_narrative(
        pack, PRERACE_SYSTEM, PRERACE_SCHEMA,
        "Write the race-morning strategy briefing for this data pack.")

    briefing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pack_version": PACK_VERSION,
        "source_keys": source_keys,
        "narrative": narrative,
        "data": pack,
    }
    if narrative:
        with open(path, "w") as f:
            json.dump(briefing, f)
    return briefing
