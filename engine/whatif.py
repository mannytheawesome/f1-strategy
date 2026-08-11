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

from data.live import (build_state, get_session, get_laps, get_stints,
                       get_drivers, _get, HIST_TTL)
from engine.predictor import (
    build_deg_curves, build_pace_model, detect_sc, simulate_race,
    PitPlan, SCEvent, forecast_to_dict, DRY, strategy_lap_trace,
)
import statistics
from types import SimpleNamespace
from data.live import (get_sc_laps_from_race_control, get_avg_pit_loss,
                       get_quali_times, get_yellow_laps)
from engine.tyre_inventory import compute_inventory, COMPOUNDS

from engine.circuits import track_position_weight

USED_SET_DEFAULT_AGE = 3   # typical scrub (one quali/practice run) when age unknown


def _pit_plans_from_stints(stints: list[dict]) -> list[PitPlan]:
    """A pit happens on the last lap of each stint except the final one.
    OpenF1 stints carry lap_start = first lap on the new tyre, so the pit
    lap (in optimizer convention: last lap completed on the OLD tyre) is
    lap_start - 1 of the following stint. tyre_age_at_start rides along so
    used sets are costed from their true starting age."""
    ordered = sorted(stints, key=lambda s: s.get("lap_start") or 0)
    return [PitPlan(lap=(s.get("lap_start") or 1) - 1,
                    compound=s.get("compound") or "MEDIUM",
                    tyre_age=s.get("tyre_age_at_start") or 0)
            for s in ordered[1:]]


def _race_start_sets(session: dict, session_key: int,
                     drivers_raw: dict) -> dict[int, dict]:
    """Per-driver tyre sets available at race start: weekend allocation minus
    new sets opened in the sessions run BEFORE this race. Each pre-race set
    opened is afterwards available as a used set. (Slight overcount vs the
    real rules, which also force sets to be returned during the weekend.)"""
    meeting_key = session.get("meeting_key")
    if not meeting_key:
        return {}
    try:
        all_sessions = sorted(_get("sessions", meeting_key=meeting_key),
                              key=lambda s: s.get("date_start", ""))
    except Exception:
        return {}
    prior = [s for s in all_sessions
             if s.get("date_start", "") < session.get("date_start", "")
             and s["session_key"] != session_key]
    is_sprint = any("sprint" in s.get("session_name", "").lower()
                    and "qualifying" not in s.get("session_name", "").lower()
                    for s in all_sessions)
    stints_by_session = []
    for s in prior:
        try:
            stints_by_session.append(get_stints(s["session_key"], HIST_TTL))
        except Exception:
            pass
    invs = compute_inventory(stints_by_session, drivers_raw, is_sprint)
    return {
        i.driver_number: {
            c: {"new": i.remaining(c), "used": i.used.get(c, 0)}
            for c in COMPOUNDS
        }
        for i in invs
    }


def _reconcile_sets_with_race(sets_by_driver: dict[int, dict],
                              stints_by_driver: dict[int, list[dict]]) -> None:
    """The pre-race reconstruction can undercount (OpenF1 stint/age data has
    gaps, and real allocations vary) — but sets fitted in the actual race are
    proof they existed. Raise each availability floor so every driver's real
    strategy always validates; edits are then judged against at least reality."""
    for num, sets in sets_by_driver.items():
        actual: dict[tuple, int] = {}
        for s in stints_by_driver.get(num, []):
            compound = s.get("compound")
            if compound not in sets:
                continue
            is_new = (s.get("tyre_age_at_start") or 0) == 0
            actual[(compound, is_new)] = actual.get((compound, is_new), 0) + 1
        for (compound, is_new), count in actual.items():
            key = "new" if is_new else "used"
            sets[compound][key] = max(sets[compound][key], count)


def _validate_edited(stints: list[dict], total_laps: int,
                     sets_available: dict | None) -> str | None:
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

    # Tyre inventory: the plan can only fit sets the driver actually had
    if sets_available:
        need: dict[tuple, int] = {}
        for s in ordered:
            is_new = (s.get("tyre_age") or 0) == 0
            need[(s["compound"], is_new)] = need.get((s["compound"], is_new), 0) + 1
        for (compound, is_new), count in need.items():
            have = sets_available.get(compound, {})
            avail = have.get("new" if is_new else "used", 0)
            if count > avail:
                kind = "new" if is_new else "used"
                return (f"plan needs {count} {kind} {compound} set(s); only "
                        f"{have.get('new', 0)} new + {have.get('used', 0)} used "
                        f"{compound} available at race start")
    return None


def _divergence_lap(edited: list[dict], actual_stints: list[dict], total_laps: int) -> int:
    """First lap at which the edited world differs from history. Everything
    strictly before this lap is identical, so the replay state there is a
    valid shared starting point for both simulations. A change of set state
    (new vs used) diverges just like a compound change does."""
    ordered_edit = sorted(edited, key=lambda s: s["lap_start"])
    ordered_act = sorted(actual_stints, key=lambda s: s.get("lap_start") or 0)

    if ordered_act:
        act_first = ordered_act[0]
        if (ordered_edit[0]["compound"] != (act_first.get("compound") or "MEDIUM")
                or (ordered_edit[0].get("tyre_age") or 0) != (act_first.get("tyre_age_at_start") or 0)):
            return 1

    edit_pits = _edited_pit_plans(ordered_edit)
    act_pits = _pit_plans_from_stints(ordered_act)

    # Anchor strictly BEFORE the earliest differing pit lap, so the sim
    # (which only applies pits with lap > current_lap) still executes it
    for e, a in zip(edit_pits, act_pits):
        if e.lap != a.lap or e.compound != a.compound or e.tyre_age != a.tyre_age:
            return max(1, min(e.lap, a.lap) - 1)
    if len(edit_pits) != len(act_pits):
        extra = edit_pits[len(act_pits):] or act_pits[len(edit_pits):]
        return max(1, extra[0].lap - 1)
    return max(1, total_laps - 1)  # identical plans — nothing to diverge on


def _edited_pit_plans(ordered_edit: list[dict]) -> list[PitPlan]:
    return [PitPlan(lap=s["lap_start"] - 1, compound=s["compound"],
                    tyre_age=s.get("tyre_age") or 0)
            for s in ordered_edit[1:]]


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

    stints_by_driver: dict[int, list[dict]] = {}
    for s in stints_raw:
        stints_by_driver.setdefault(s["driver_number"], []).append(s)

    if driver_number not in stints_by_driver:
        raise ValueError(f"driver {driver_number} not in session")

    all_sets = _race_start_sets(session, session_key, drivers_raw)
    _reconcile_sets_with_race(all_sets, stints_by_driver)
    driver_sets = all_sets.get(driver_number)

    err = _validate_edited(edited_stints, total_laps, driver_sets)
    if err:
        raise ValueError(err)

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
                                  stints_raw, quali_times=quali_times or None,
                                  exclude_laps=get_yellow_laps(session_key, HIST_TTL))
    pit_loss = get_avg_pit_loss(session_key, HIST_TTL)
    track_pos_weight = track_position_weight(circuit)

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
            # laps run in this stint so far, on top of the set's fitted age
            d["tyre_age"] = max(0, anchor - edit_current["lap_start"]) \
                + (edit_current.get("tyre_age") or 0)

    actual_plans = {num: _pit_plans_from_stints(sts)
                    for num, sts in stints_by_driver.items()}
    edited_plans = dict(actual_plans)
    edited_plans[driver_number] = _edited_pit_plans(
        sorted(edited_stints, key=lambda s: s["lap_start"]))

    common = dict(current_lap=anchor, total_laps=total_laps, curves=curves,
                  pace_model=pace_model, sc_events=sc_events, pit_loss=pit_loss,
                  track_position_weight=track_pos_weight, circuit=circuit)
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

    # Race trace, RSS-style: the edited driver's actual vs edited strategy, the
    # whole field underneath for context, SC/VSC bands, and a pace-fix sweep on
    # the edited strategy (car-setup "what if we found 0.3s"). All derived from
    # the existing lap model — the detrend by reference_lap_time makes pit stops
    # read as steps ("offset from average pace").
    trace = None
    if base_fc and mod_fc:
        baselines = [c.baseline for c in curves.values() if c.baseline > 0]
        field_baseline = statistics.median(baselines) if baselines else 90.0
        pace = pace_model.get(driver_number)
        pd = pace.pace_delta if pace else 0.0

        def _trace(strategy, pace_delta):
            return strategy_lap_trace(strategy, anchor, total_laps, curves,
                                      field_baseline, pace_delta, pit_loss)

        # field underlay: every driver on their actual strategy
        field = []
        for f in baseline:
            fpd = (pace_model.get(f.driver_number).pace_delta
                   if pace_model.get(f.driver_number) else 0.0)
            pts = _trace(f.strategy, fpd)
            if pts:
                field.append({"driver_number": f.driver_number, "acronym": f.acronym,
                              "final": pts[-1]["cumulative"], "points": pts})

        # pace-fix sweep (lower pace_delta = faster car), race-time-ranked against
        # the field: how many OTHER drivers finish on less cumulative time.
        others_final = sorted(t["final"] for t in field if t["driver_number"] != driver_number)

        def _sweep(strategy, with_points):
            out = []
            for fix in (0.0, 0.3, 0.5):
                pts = _trace(strategy, pd - fix)
                if not pts:
                    continue
                final = pts[-1]["cumulative"]
                item = {"pace_fix": fix, "label": "no fix" if fix == 0 else f"+{fix:g}s/lap",
                        "final_cumulative": round(final, 1),
                        "race_time_rank": 1 + sum(1 for c in others_final if c < final)}
                if with_points:
                    item["points"] = pts
                out.append(item)
            return out

        # the two tyre orders (RSS's second axis): the edited compound sequence
        # and its reverse, same stop laps. The drawn scenarios use the edited
        # order; tyre_orders compares both so the reader sees which order wins.
        edited_pits = sorted(mod_fc.strategy.pits_remaining, key=lambda p: p.lap)
        edited_seq = [mod_fc.strategy.current_compound] + [p.compound for p in edited_pits]
        order_label = lambda seq: "-".join((c or "?")[0] for c in seq)
        scenarios = _sweep(mod_fc.strategy, with_points=True)
        tyre_orders = [{"order": order_label(edited_seq), "sequence": edited_seq,
                        "scenarios": _sweep(mod_fc.strategy, with_points=False)}]
        rev_seq = edited_seq[::-1]
        if len(set(edited_seq)) > 1 and rev_seq != edited_seq:
            rev_strat = SimpleNamespace(
                current_compound=rev_seq[0], current_age=mod_fc.strategy.current_age,
                pits_remaining=[PitPlan(p.lap, rev_seq[i + 1]) for i, p in enumerate(edited_pits)])
            tyre_orders.append({"order": order_label(rev_seq), "sequence": rev_seq,
                                "scenarios": _sweep(rev_strat, with_points=False)})

        trace = {
            "anchor_lap": anchor,
            "total_laps": total_laps,
            "reference_lap_time": round(field_baseline, 3),
            "subject_number": driver_number,
            "baseline": _trace(base_fc.strategy, pd),
            "modified": _trace(mod_fc.strategy, pd),
            "field": field,
            "scenarios": scenarios,
            "tyre_orders": tyre_orders,
            "sc_bands": [{"start": e.start_lap, "end": e.end_lap, "type": e.type}
                         for e in sc_events],
        }

    return {
        "session_key": session_key,
        "driver_number": driver_number,
        "anchor_lap": anchor,
        "total_laps": total_laps,
        "circuit": circuit,
        "pit_loss_used": pit_loss,
        "tyre_sets_available": driver_sets,
        "used_set_default_age": USED_SET_DEFAULT_AGE,
        "baseline": [forecast_to_dict(f) for f in baseline],
        "modified": [forecast_to_dict(f) for f in modified],
        "trace": trace,
        "actual": actual_result,
        "delta": {
            "position": (base_fc.predicted_position - mod_fc.predicted_position)
                        if base_fc and mod_fc else None,
            "gap": round(base_fc.predicted_gap - mod_fc.predicted_gap, 2)
                   if base_fc and mod_fc else None,
        },
    }
