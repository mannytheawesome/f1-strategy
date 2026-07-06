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
    PIT_LOSS, DRY,
)
from engine.tyre_inventory import compute_inventory
from engine.briefing import BRIEFING_DIR, generate_structured_narrative

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
        "watch_list": {"type": "string", "description": "80-160 words: the 2-4 unknowns that get filled in during the first stint, and exactly what to watch for each"},
    },
    "required": ["headline", "grid_story", "the_trade", "race_shape", "watch_list"],
    "additionalProperties": False,
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
        # regenerate automatically when a new session has completed since
        if cached.get("source_keys") == source_keys and cached.get("narrative"):
            return cached

    narrative = generate_structured_narrative(
        pack, PRERACE_SYSTEM, PRERACE_SCHEMA,
        "Write the race-morning strategy briefing for this data pack.")

    briefing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_keys": source_keys,
        "narrative": narrative,
        "data": pack,
    }
    if narrative:
        with open(path, "w") as f:
            json.dump(briefing, f)
    return briefing
