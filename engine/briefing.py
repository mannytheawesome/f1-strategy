"""
Race briefings: a structured per-race data pack (results, stints, tyre
degradation, SC events, notable stats) plus LLM-written narrative sections.

The narrative is generated once per session by Claude and cached to disk in
./briefings/. The model is instructed to ground every claim in the numbers
present in the data pack — it writes prose, it does not invent data. If no
Anthropic credentials are configured, the briefing still returns the full
data pack with narrative=None so the frontend can degrade gracefully.
"""

import json
import os
import statistics
from datetime import datetime, timezone

from data.live import (
    get_session, get_laps, get_stints, get_drivers, build_state,
    get_sc_laps_from_race_control, get_avg_pit_loss, get_weather_summary,
    get_quali_times, _get, HIST_TTL,
)
from engine.predictor import (
    build_deg_curves, build_pace_model, detect_sc, curves_to_dict, SCEvent,
    FUEL_RATE,
)

# Bumped whenever the data-pack shape changes; cached briefings with an older
# version are rebuilt (and their narrative regenerated) on next request.
PACK_VERSION = 3

BRIEFING_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "briefings")
os.makedirs(BRIEFING_DIR, exist_ok=True)

NARRATIVE_MODEL = "claude-opus-4-8"

NARRATIVE_SYSTEM = """You are the staff writer for an F1 race-strategy analysis site. \
You write sharp, data-literate briefings in the style of a strategy engineer's debrief: \
concrete numbers, causal reasoning, no hype and no filler.

Hard rules:
- Every number you cite MUST appear in the JSON data pack you are given. Never invent \
lap times, gaps, degradation rates, or positions. If the data doesn't support a claim, \
don't make it.
- Refer to drivers by their three-letter acronym as given in the data.
- Degradation rates are seconds per lap of tyre age; pace deltas are seconds per lap \
vs the field median (negative = faster).
- British-motorsport register, present tense for analysis, past tense for events.
- No bullet-point dumps: write flowing analytical prose with occasional short punchy \
sentences for emphasis."""

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline":          {"type": "string", "description": "Punchy 4-8 word title for the briefing"},
        "race_story":        {"type": "string", "description": "250-400 words: how the race was won and lost — key strategy calls, position changes, SC influence"},
        "tyre_story":        {"type": "string", "description": "150-250 words: what the degradation numbers say — compound comparison, use the stint_pace table to name who managed tyres well/badly and whether used sets matched new ones"},
        "the_stops":         {"type": "string", "description": "120-220 words: the pit calls, judged from the stops_graded table — name the best-timed and worst-timed stops with their measured gains/losses in seconds, and credit SC windfalls"},
        "strategy_verdicts": {"type": "string", "description": "150-250 words: the best and worst overall strategy calls of the race, judged against the deg/pace data"},
    },
    "required": ["headline", "race_story", "tyre_story", "the_stops", "strategy_verdicts"],
    "additionalProperties": False,
}


def _cache_path(session_key: int) -> str:
    return os.path.join(BRIEFING_DIR, f"briefing_{session_key}.json")


GRADE_LABELS = [(3.0, "inspired"), (1.0, "good"), (-1.0, "neutral"),
                (-3.0, "costly")]  # below the last threshold: "howler"
STOP_WINDOW = 5  # laps over which a stop's timing is judged


def _grade_stops(stints_by_driver: dict, acronyms: dict, curves: dict,
                 sc_events: list, pit_loss: float, total_laps: int) -> list[dict]:
    """Judge every actual pit stop over the following STOP_WINDOW laps:
    the tyre-time saved by pitting now (fresh rubber) vs staying out on the
    old set — both worlds pay one pit loss inside the window, so the delta is
    purely curve-vs-curve. Stops taken under SC additionally bank the
    discounted pit lane (0.55 x pit loss vs a green-flag alternative)."""
    out = []
    for num, stints in stints_by_driver.items():
        ordered = sorted(stints, key=lambda s: s.get("lap_start") or 0)
        for prev, nxt in zip(ordered, ordered[1:]):
            stop_lap = (nxt.get("lap_start") or 1) - 1
            old_c, new_c = prev.get("compound"), nxt.get("compound")
            oc, nc = curves.get(old_c), curves.get(new_c)
            if not oc or not nc or not oc.baseline or not nc.baseline:
                continue
            age_at_stop = ((prev.get("tyre_age_at_start") or 0)
                           + stop_lap - (prev.get("lap_start") or 1) + 1)
            window = min(STOP_WINDOW, max(1, total_laps - stop_lap))
            stay_out = sum(oc.lap_time(age_at_stop + i) for i in range(1, window + 1))
            pit_now = sum(nc.lap_time(i) for i in range(1, window + 1))
            gain = stay_out - pit_now
            under_sc = any(e.start_lap <= stop_lap <= e.end_lap + 1 for e in sc_events)
            if under_sc:
                gain += pit_loss * 0.55
            label = "howler"
            for threshold, name in GRADE_LABELS:
                if gain >= threshold:
                    label = name
                    break
            out.append({
                "acronym":      acronyms.get(num, str(num)),
                "driver_number": num,
                "lap":          stop_lap,
                "from":         old_c, "to": new_c,
                "old_tyre_age": age_at_stop,
                "under_sc":     under_sc,
                "gain_s":       round(gain, 2),
                "grade":        label,
            })
    out.sort(key=lambda s: -s["gain_s"])
    return out


def _stint_pace_table(all_laps: list, stints_by_driver: dict, acronyms: dict,
                      sc_events: list, total_laps: int) -> dict:
    """Per-stint fuel-corrected pace: median lap and deg slope (s/lap of age)
    with the fuel effect removed, plus a field-level new-vs-used comparison
    per compound — the 'is the medium a rock' read."""
    sc_laps = set()
    for e in sc_events:
        sc_laps.update(range(e.start_lap, e.end_lap + 2))
    laps_by_driver: dict[int, list] = {}
    for l in all_laps:
        t = l.get("lap_duration")
        if (t and 55 < t < 200 and not l.get("is_pit_out_lap")
                and l["lap_number"] not in sc_laps):
            laps_by_driver.setdefault(l["driver_number"], []).append(l)

    rows = []
    compound_agg: dict[tuple, list] = {}
    for num, stints in stints_by_driver.items():
        for s in sorted(stints, key=lambda x: x.get("lap_start") or 0):
            ls, le = s.get("lap_start") or 1, s.get("lap_end") or total_laps
            in_stint = [l for l in laps_by_driver.get(num, [])
                        if ls < l["lap_number"] <= le]  # excl. out-lap
            if len(in_stint) < 5:
                continue
            # fuel-corrected: add back the fuel-burn gain so slope = wear only
            pts = [(l["lap_number"] - ls,
                    l["lap_duration"] + FUEL_RATE * l["lap_number"])
                   for l in in_stint]
            n = len(pts)
            mean_x = sum(p[0] for p in pts) / n
            mean_y = sum(p[1] for p in pts) / n
            denom = sum((p[0] - mean_x) ** 2 for p in pts)
            slope = (sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts) / denom
                     if denom else 0.0)
            new_set = (s.get("tyre_age_at_start") or 0) == 0
            row = {
                "acronym":   acronyms.get(num, str(num)),
                "compound":  s.get("compound"),
                "new_set":   new_set,
                "laps":      [ls, le],
                "clean_laps": n,
                "median":    round(statistics.median(l["lap_duration"] for l in in_stint), 3),
                "slope":     round(slope, 4),
                "flat":      abs(slope) <= FUEL_RATE * 1.5,  # inside the fuel+evo band
            }
            rows.append(row)
            compound_agg.setdefault((s.get("compound"), new_set), []).append(slope)

    field = []
    for (compound, new_set), slopes in sorted(compound_agg.items(),
                                              key=lambda kv: (kv[0][0] or "", not kv[0][1])):
        field.append({
            "compound":     compound,
            "new_set":      new_set,
            "stint_count":  len(slopes),
            "median_slope": round(statistics.median(slopes), 4),
        })
    rows.sort(key=lambda r: r["slope"])
    return {"fuel_evo_band": round(FUEL_RATE * 1.5, 3), "stints": rows, "field": field}


def build_briefing_data(session_key: int) -> dict:
    session = get_session(session_key)
    mode_raw = session.get("session_type", "").lower()
    if mode_raw != "race":
        raise ValueError("briefings are only available for races and sprints")

    all_laps    = get_laps(session_key, HIST_TTL)
    stints_raw  = get_stints(session_key, HIST_TTL)
    drivers_raw = get_drivers(session_key, HIST_TTL)
    total_laps  = max((l["lap_number"] for l in all_laps), default=0)
    if total_laps < 10:
        raise ValueError("race has too little data for a briefing (not finished yet?)")

    # Deg curves: FP prior + race data, same recipe as /api/predict
    meeting_key = session.get("meeting_key")
    fp_data = []
    if meeting_key:
        try:
            all_sessions = sorted(_get("sessions", meeting_key=meeting_key),
                                  key=lambda s: s.get("date_start", ""))
            fp_names = ["FP1", "FP2", "FP3"]
            for i, fp in enumerate([s for s in all_sessions
                                    if s.get("session_type", "").lower() == "practice"][:3]):
                try:
                    fp_data.append((fp_names[i],
                                    get_laps(fp["session_key"], HIST_TTL),
                                    get_stints(fp["session_key"], HIST_TTL)))
                except Exception:
                    pass
        except Exception:
            pass
    fp_data.append(("RACE", all_laps, stints_raw))
    curves = build_deg_curves(fp_data)

    rc_events = get_sc_laps_from_race_control(session_key, HIST_TTL)
    if rc_events:
        sc_events = [SCEvent(e["start_lap"], e["end_lap"], e["type"]) for e in rc_events]
        sc_source = "race_control"
    else:
        sc_events = detect_sc(all_laps)
        sc_source = "heuristic"

    quali_times = get_quali_times(meeting_key) if meeting_key else {}
    pace_model = build_pace_model(all_laps, sc_events, drivers_raw, curves,
                                  stints_raw, quali_times=quali_times or None)

    state = build_state(session_key, include_locations=False, session=session)
    stints_by_driver: dict[int, list[dict]] = {}
    for s in stints_raw:
        stints_by_driver.setdefault(s["driver_number"], []).append(s)

    fastest = None
    for l in all_laps:
        t = l.get("lap_duration")
        if t and 55 < t < 200 and (fastest is None or t < fastest[1]):
            fastest = (l["driver_number"], t, l["lap_number"])

    results = []
    for d in sorted(state.values(), key=lambda d: (d.position is None, d.position or 99)):
        pace = pace_model.get(d.driver_number)
        stints = [
            {"compound": s.get("compound"), "lap_start": s.get("lap_start"),
             "lap_end": s.get("lap_end"),
             "length": ((s.get("lap_end") or total_laps) - (s.get("lap_start") or 1) + 1),
             "tyre_age": s.get("tyre_age_at_start") or 0}
            for s in sorted(stints_by_driver.get(d.driver_number, []),
                            key=lambda s: s.get("lap_start") or 0)
        ]
        results.append({
            "driver_number":  d.driver_number,
            "acronym":        d.acronym,
            "team":           d.team,
            "team_colour":    d.team_colour,
            "position":       d.position,
            "grid_position":  d.grid_position,
            "positions_delta": d.positions_delta,
            "retired":        d.retired,
            "gap_to_leader":  d.gap_to_leader,
            "stops":          max(0, len(stints) - 1),
            "stints":         stints,
            "pace_delta":     round(pace.pace_delta, 3) if pace else None,
        })

    finishers = [r for r in results if not r["retired"] and r["position"]]
    movers = sorted((r for r in finishers if r["positions_delta"] is not None),
                    key=lambda r: r["positions_delta"], reverse=True)
    stop_counts = [r["stops"] for r in finishers]

    stats = {
        "winner":            finishers[0]["acronym"] if finishers else None,
        "biggest_gainer":    ({"acronym": movers[0]["acronym"], "gained": movers[0]["positions_delta"]}
                              if movers and movers[0]["positions_delta"] > 0 else None),
        "biggest_loser":     ({"acronym": movers[-1]["acronym"], "lost": -movers[-1]["positions_delta"]}
                              if movers and movers[-1]["positions_delta"] < 0 else None),
        "fastest_lap":       ({"acronym": next((r["acronym"] for r in results
                                                if r["driver_number"] == fastest[0]), str(fastest[0])),
                               "time": round(fastest[1], 3), "lap": fastest[2]}
                              if fastest else None),
        "modal_stop_count":  statistics.mode(stop_counts) if stop_counts else None,
        "retirements":       [r["acronym"] for r in results if r["retired"]],
        "sc_count":          len(sc_events),
    }

    acronyms = {r["driver_number"]: r["acronym"] for r in results}
    pit_loss = get_avg_pit_loss(session_key, HIST_TTL)

    # Tyre sets each driver still had at race start (for the what-if editor)
    try:
        from engine.whatif import _race_start_sets, _reconcile_sets_with_race
        sets_at_start = _race_start_sets(session, session_key, drivers_raw)
        _reconcile_sets_with_race(sets_at_start, stints_by_driver)
        for r in results:
            r["sets_at_start"] = sets_at_start.get(r["driver_number"])
    except Exception:
        for r in results:
            r["sets_at_start"] = None

    return {
        "session": {
            "session_key":  session_key,
            "session_name": session.get("session_name"),
            "country_name": session.get("country_name"),
            "circuit":      session.get("circuit_short_name"),
            "date_start":   session.get("date_start"),
            "year":         session.get("year"),
            "total_laps":   total_laps,
        },
        "weather":     get_weather_summary(session_key, HIST_TTL),
        "pit_loss":    pit_loss,
        "sc_events":   [{"start_lap": e.start_lap, "end_lap": e.end_lap, "type": e.type}
                        for e in sc_events],
        "sc_source":   sc_source,
        "deg_curves":  curves_to_dict(curves),
        "results":     results,
        "stats":       stats,
        "stops_graded": _grade_stops(stints_by_driver, acronyms, curves,
                                     sc_events, pit_loss, total_laps),
        "stint_pace":  _stint_pace_table(all_laps, stints_by_driver, acronyms,
                                         sc_events, total_laps),
    }


def generate_structured_narrative(pack: dict, system: str, schema: dict,
                                  task: str) -> dict | None:
    """One-shot Claude generation, structured JSON output. Returns None if
    no credentials are available or the call fails — caller degrades.
    Shared by the post-race and pre-race briefing generators."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=NARRATIVE_MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{
                "role": "user",
                "content": (task + " Remember: every number must come from the pack.\n\n"
                            + json.dumps(pack)),
            }],
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        return json.loads(text) if text else None
    except Exception as e:
        print(f"[briefing] narrative generation failed: {e}")
        return None


def generate_narrative(pack: dict) -> dict | None:
    return generate_structured_narrative(
        pack, NARRATIVE_SYSTEM, NARRATIVE_SCHEMA,
        "Write the race briefing for this data pack.")


def get_briefing(session_key: int, regenerate: bool = False) -> dict:
    path = _cache_path(session_key)
    if not regenerate and os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        if cached.get("pack_version") == PACK_VERSION:
            return cached
        # pack shape changed since this was cached — rebuild below

    pack = build_briefing_data(session_key)
    narrative = generate_narrative(pack)

    briefing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pack_version": PACK_VERSION,
        "narrative_model": NARRATIVE_MODEL if narrative else None,
        "narrative": narrative,
        "data": pack,
    }
    # Only cache complete briefings — a missing narrative (no API key yet)
    # should retry on the next request rather than pinning the degraded copy
    if narrative:
        with open(path, "w") as f:
            json.dump(briefing, f)
    return briefing
