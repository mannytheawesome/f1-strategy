"""
Counterfactual ("what-if") race simulation.

Given a finished race and ONE driver's edited stint plan, re-run the race
simulation from the lap where the edited plan first diverges from what
actually happened. Every other driver runs their ACTUAL historical strategy
(as a prescribed pit plan), so the only variable is the edit.

Two simulations are returned:
  baseline — everyone on their actual strategy (the model's own view of
             reality from the anchor lap; absorbs model error)
  modified — same, but the edited driver runs the user's plan

Comparing modified vs baseline isolates the effect of the strategy change;
comparing either against the actual classification shows raw model error.

Known simplification: drivers who retired after the anchor lap are simulated
as finishing (the counterfactual can't know about future DNFs).
"""

from data.live import build_state, get_session, get_laps, get_stints, get_drivers, HIST_TTL
from engine.predictor import (
    build_deg_curves, build_pace_model, detect_sc, simulate_race,
    PitPlan, SCEvent, forecast_to_dict, DRY,
)
from data.live import get_sc_laps_from_race_control, get_avg_pit_loss, get_quali_times

STREET_CIRCUITS = ["monaco", "baku", "singapore", "jeddah", "las_vegas", "miami"]


def _pit_plans_from_stints(stints: list[dict]) -> list[PitPlan]:
    """A pit happens on the last lap of each stint except the final one.
    OpenF1 stints carry lap_start = first lap on the new tyre, so the pit
    lap (in optimizer convention: last lap completed on the OLD tyre) is
    lap_start - 1 of the following stint."""
    ordered = sorted(stints, key=lambda s: s.get("lap_start") or 0)
    return [PitPlan(lap=(s.get("lap_start") or 1) - 1, compound=s.get("compound") or "MEDIUM")
            for s in ordered[1:]]


def _validate_edited(stints: list[dict], total_laps: int) -> str | None:
    if not stints:
        return "empty stint plan"
    ordered = sorted(stints, key=lambda s: s["lap_start"])
    if ordered[0]["lap_start"] != 1:
        return "first stint must start at lap 1"
    prev_end = 0
    for s in ordered:
        if s.get("compound") not in DRY:
            return f"unsupported compound: {s.get('compound')}"
        if s["lap_start"] != prev_end + 1:
            return f"stints not contiguous at lap {s['lap_start']}"
        if s["lap_end"] < s["lap_start"]:
            return f"stint ending before it starts at lap {s['lap_start']}"
        prev_end = s["lap_end"]
    if prev_end != total_laps:
        return f"plan covers {prev_end} laps, race is {total_laps}"
    if len({s["compound"] for s in ordered}) < 2:
        return "F1 rules require at least two different dry compounds"
    return None


def _divergence_lap(edited: list[dict], actual_stints: list[dict], total_laps: int) -> int:
    """First lap at which the edited world differs from history. Everything
    strictly before this lap is identical, so the replay state there is a
    valid shared starting point for both simulations."""
    ordered_edit = sorted(edited, key=lambda s: s["lap_start"])
    ordered_act = sorted(actual_stints, key=lambda s: s.get("lap_start") or 0)

    if ordered_act and ordered_edit[0]["compound"] != (ordered_act[0].get("compound") or "MEDIUM"):
        return 1

    edit_pits = _pit_plans_from_stints(ordered_edit)
    act_pits = _pit_plans_from_stints(ordered_act)

    # Anchor strictly BEFORE the earliest differing pit lap, so the sim
    # (which only applies pits with lap > current_lap) still executes it
    for e, a in zip(edit_pits, act_pits):
        if e.lap != a.lap or e.compound != a.compound:
            return max(1, min(e.lap, a.lap) - 1)
    if len(edit_pits) != len(act_pits):
        extra = edit_pits[len(act_pits):] or act_pits[len(edit_pits):]
        return max(1, extra[0].lap - 1)
    return max(1, total_laps - 1)  # identical plans — nothing to diverge on


def _serialise(drivers_sorted) -> list[dict]:
    return [
        {
            "driver_number": d.driver_number,
            "acronym":       d.acronym,
            "position":      d.position,
            "compound":      d.current_stint.compound if d.current_stint else "MEDIUM",
            "tyre_age":      d.tyre_age or 0,
            "gap_to_leader": d.gap_to_leader,
            "interval":      d.interval,
            "retired":       d.retired,
            "compounds_used": list({s.compound for s in d.stints}),
            "current_lap":   d.current_lap,
        }
        for d in drivers_sorted
    ]


def run_whatif(session_key: int, driver_number: int, edited_stints: list[dict]) -> dict:
    session = get_session(session_key)
    circuit = session.get("circuit_short_name", "")

    all_laps    = get_laps(session_key, HIST_TTL)
    stints_raw  = get_stints(session_key, HIST_TTL)
    drivers_raw = get_drivers(session_key, HIST_TTL)

    total_laps = max((l["lap_number"] for l in all_laps), default=0)
    if total_laps < 10:
        raise ValueError("session has too few laps to simulate")

    err = _validate_edited(edited_stints, total_laps)
    if err:
        raise ValueError(err)

    stints_by_driver: dict[int, list[dict]] = {}
    for s in stints_raw:
        stints_by_driver.setdefault(s["driver_number"], []).append(s)

    if driver_number not in stints_by_driver:
        raise ValueError(f"driver {driver_number} not in session")

    anchor = _divergence_lap(edited_stints, stints_by_driver[driver_number], total_laps)
    anchor = min(anchor, total_laps - 2)

    # Model inputs from full-race data (best available estimate of pace/deg)
    curves = build_deg_curves([("RACE", all_laps, stints_raw)])
    rc_events = get_sc_laps_from_race_control(session_key, HIST_TTL)
    if rc_events:
        sc_events = [SCEvent(e["start_lap"], e["end_lap"], e["type"]) for e in rc_events]
    else:
        sc_events = detect_sc(all_laps)
    quali_times = get_quali_times(session.get("meeting_key")) if session.get("meeting_key") else {}
    pace_model = build_pace_model(all_laps, sc_events, drivers_raw, curves,
                                  stints_raw, quali_times=quali_times or None)
    pit_loss = get_avg_pit_loss(session_key, HIST_TTL)
    track_pos_weight = 0.75 if any(c in circuit.lower() for c in STREET_CIRCUITS) else 0.6

    # Shared starting state at the anchor lap
    state = build_state(session_key, include_locations=False,
                        session=session, max_lap=anchor)
    drivers_sorted = sorted(state.values(),
                            key=lambda d: (d.position is None, d.position or 99))
    serialised_base = _serialise(drivers_sorted)

    # Modified world: edited driver's tyre state at the anchor comes from the
    # edited plan (differs from history when the stint-1 compound was changed).
    # Baseline keeps the actual state, so the copies must be independent.
    serialised_mod = [dict(d) for d in serialised_base]
    edit_current = next(s for s in sorted(edited_stints, key=lambda s: s["lap_start"])
                        if s["lap_start"] <= anchor <= s["lap_end"])
    for d in serialised_mod:
        if d["driver_number"] == driver_number:
            d["compound"] = edit_current["compound"]
            d["tyre_age"] = max(0, anchor - edit_current["lap_start"])

    actual_plans = {num: _pit_plans_from_stints(sts)
                    for num, sts in stints_by_driver.items()}
    edited_plans = dict(actual_plans)
    edited_plans[driver_number] = _pit_plans_from_stints(
        sorted(edited_stints, key=lambda s: s["lap_start"]))

    common = dict(current_lap=anchor, total_laps=total_laps, curves=curves,
                  pace_model=pace_model, sc_events=sc_events, pit_loss=pit_loss,
                  track_position_weight=track_pos_weight)
    baseline = simulate_race(serialised_base, prescribed_strategies=actual_plans, **common)
    modified = simulate_race(serialised_mod, prescribed_strategies=edited_plans, **common)

    # Actual final classification for reference
    final_state = build_state(session_key, include_locations=False, session=session)
    actual_result = [
        {"driver_number": d.driver_number, "acronym": d.acronym,
         "position": d.position, "retired": d.retired}
        for d in sorted(final_state.values(),
                        key=lambda d: (d.position is None, d.position or 99))
    ]

    base_fc = next((f for f in baseline if f.driver_number == driver_number), None)
    mod_fc = next((f for f in modified if f.driver_number == driver_number), None)

    return {
        "session_key": session_key,
        "driver_number": driver_number,
        "anchor_lap": anchor,
        "total_laps": total_laps,
        "circuit": circuit,
        "pit_loss_used": pit_loss,
        "baseline": [forecast_to_dict(f) for f in baseline],
        "modified": [forecast_to_dict(f) for f in modified],
        "actual": actual_result,
        "delta": {
            "position": (base_fc.predicted_position - mod_fc.predicted_position)
                        if base_fc and mod_fc else None,
            "gap": round(base_fc.predicted_gap - mod_fc.predicted_gap, 2)
                   if base_fc and mod_fc else None,
        },
    }
