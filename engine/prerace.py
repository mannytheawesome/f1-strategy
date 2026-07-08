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
    PIT_LOSS, DRY,
)

PACK_VERSION = 3
from engine.tyre_inventory import compute_inventory
from engine.briefing import BRIEFING_DIR, generate_structured_narrative
from engine.whatif import STREET_CIRCUITS

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
        "race_shape": {"type": "string", "description": "180-280 words: expected stop count, the paper strategies and what breaks them, how the Safety Car probability and pit loss change the calculus"},
        "projection": {"type": "string", "description": "120-220 words: what the model projects from the grid — use long_run_pace to name who is out of position (pace rank vs grid slot) and the projection forecasts (win/podium probabilities) to frame the likely podium; flag the assumptions (start compound, grid spread)"},
        "watch_list": {"type": "string", "description": "80-160 words: the 2-4 unknowns that get filled in during the first stint, and exactly what to watch for each"},
    },
    "required": ["headline", "grid_story", "the_trade", "race_shape", "projection", "watch_list"],
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
            stint_laps = [(ln, t) for ln, t in laps_by_driver.get(num, {}).items()
                          if ls < ln <= le]
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


def _project_race(grid: list[dict], pace_rows: list[dict], curves: dict,
                  strategies: list[dict], total_laps: int, pit_loss: float,
                  circuit: str) -> dict | None:
    """Run the race model from lap 0: grid order + long-run pace + deg curves,
    optimizer free to choose each car's strategy. Monte Carlo supplies win and
    podium probabilities. The grid is spread at GRID_SPREAD_S per slot to give
    the track-position anchor something to hold on to."""
    if not grid or not strategies:
        return None
    pace_by_num = {r["driver_number"]: r for r in pace_rows}
    start_c = strategies[0]["start_compound"]
    serialised, pace_model = [], {}
    for g in grid:
        num = next((r["driver_number"] for r in pace_rows
                    if r["acronym"] == g["acronym"]), None)
        if num is None:
            num = g["position"] * 1000  # placeholder for cars with no long-run data
        pr = pace_by_num.get(num)
        serialised.append({
            "driver_number": num, "acronym": g["acronym"],
            "position": g["position"], "compound": start_c, "tyre_age": 0,
            "gap_to_leader": f"+{(g['position'] - 1) * GRID_SPREAD_S:.3f}",
            "interval": f"+{GRID_SPREAD_S:.3f}" if g["position"] > 1 else "LEADER",
            "retired": False, "compounds_used": [start_c], "current_lap": 0,
        })
        pace_model[num] = DriverPace(
            driver_number=num, acronym=g["acronym"],
            pace_median=0.0, pace_std=0.3,
            pace_delta=pr["pace_delta"] if pr else 0.0,
            laps_counted=pr["laps"] if pr else 0)
    is_street = any(c in circuit.lower() for c in STREET_CIRCUITS)
    forecasts = simulate_race(serialised, 0, total_laps, curves, pace_model, [],
                              pit_loss=pit_loss,
                              track_position_weight=0.75 if is_street else 0.6)
    return {
        "grid_spread_assumption_s": GRID_SPREAD_S,
        "start_compound_assumption": start_c,
        "forecasts": [forecast_to_dict(f) for f in forecasts[:10]],
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


def build_prerace_data(meeting_key: int, total_laps: int | None = None) -> dict:
    sessions = _meeting_sessions(meeting_key)
    if not sessions:
        raise ValueError("unknown meeting")
    completed = _completed(sessions)
    sources = [s for s in completed if not _is_grand_prix(s)]
    if not sources:
        raise ValueError("no completed sessions for this meeting yet — check back after FP1")

    race = next((s for s in sessions if _is_grand_prix(s)), None)
    meta = race or sources[-1]
    circuit = meta.get("circuit_short_name", "")
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
         "team_colour": d.team_colour, "gap": d.gap_to_leader}
        for d in sorted(grid_state.values(),
                        key=lambda d: (d.position is None, d.position or 99))
        if d.position
    ][:20]

    # ── paper strategies from each start compound ────────────────────────────
    baselines = [c.baseline for c in curves.values() if c.baseline > 0]
    field_baseline = statistics.median(baselines) if baselines else 90.0
    pit_loss = get_avg_pit_loss(sprint_key, HIST_TTL) if sprint_key else PIT_LOSS
    strategies = []
    for start_c in DRY:
        if start_c not in curves or not curves[start_c].baseline:
            continue
        strat = optimize_strategy(0, total_laps, start_c, 0, 0.0, curves,
                                  field_baseline, pit_loss,
                                  needs_compound_change=True)
        seq = [start_c] + [p.compound for p in strat.pits_remaining]
        pit_laps = [p.lap for p in strat.pits_remaining]
        bounds = [0] + pit_laps + [total_laps]
        strategies.append({
            "start_compound": start_c,
            "stops": len(pit_laps),
            "compound_sequence": seq,
            "pit_laps": pit_laps,
            "stint_lengths": [bounds[i + 1] - bounds[i] for i in range(len(seq))],
            "total_time": strat.total_time_from_now,
        })
    strategies.sort(key=lambda s: s["total_time"])
    for s in strategies:
        s["time_delta"] = round(s["total_time"] - strategies[0]["total_time"], 1)

    # ── tyre inventory: what the top 10 actually hold ────────────────────────
    inventory_summary = None
    try:
        drivers_raw = get_drivers(grid_source["session_key"], HIST_TTL)
        stints_by_session = []
        for s in sources:
            try:
                stints_by_session.append(get_stints(s["session_key"], HIST_TTL))
            except Exception:
                pass
        invs = {i.driver_number: i for i in
                compute_inventory(stints_by_session, drivers_raw, is_sprint_weekend)}
        top10 = [g for g in grid[:10]]
        top10_nums = [d.driver_number for d in grid_state.values()
                      if d.position and d.position <= 10]
        rows = [invs[n] for n in top10_nums if n in invs]
        if rows:
            inventory_summary = {
                "top10_with_new_hard":   sum(1 for i in rows if i.remaining("HARD") >= 1),
                "top10_with_new_medium": sum(1 for i in rows if i.remaining("MEDIUM") >= 1),
                "top10_with_new_soft":   sum(1 for i in rows if i.remaining("SOFT") >= 1),
                "top10_count": len(rows),
            }
    except Exception:
        pass

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
                                   total_laps, pit_loss, circuit)
    except Exception:
        pass

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
        "pit_loss": pit_loss,
        "pit_loss_source": "sprint_measured" if sprint_key else "default",
        "sc_probability": sc_prob,
        "long_run_pace": pace_rows,
        "quali_sectors": sectors,
        "projection": projection,
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
    pack = build_prerace_data(meeting_key, total_laps)
    source_keys = [s["session_key"] for s in pack["sources"]]

    if not regenerate and os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        # regenerate when a new session completed OR the pack shape changed
        if (cached.get("source_keys") == source_keys and cached.get("narrative")
                and cached.get("pack_version") == PACK_VERSION):
            return cached

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
