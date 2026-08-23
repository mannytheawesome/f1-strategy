"""Session analysis: FP stint breakdown, quali ranking, tyre inventory, the
FP-derived pre-race strategy forecast, the 1-stop-vs-2-stop duel, and the
RSS-style per-race charts."""

import statistics

from fastapi import APIRouter, HTTPException

from data.live import (
    get_session, get_laps, get_stints, get_drivers, get_weather_summary,
    get_avg_pit_loss, _get, _cached_get, HIST_TTL,
)
from engine.fp_analysis import analyse_fp, _field_compound_summary
from engine.quali_analysis import analyse_quali
from engine.tyre_inventory import compute_inventory
from engine.degradation import build_degradation_curves
from engine.strategy import generate_strategies
from engine.predictor import (
    sc_probability, build_deg_curves, curves_to_dict, optimize_strategy,
    strategy_duel, DRY, PIT_LOSS,
)
from engine import race_charts as rc
from api.helpers import _session_mode

router = APIRouter()


@router.get("/api/fp_analysis")
def fp_analysis(session_key: int):
    try:
        session      = get_session(session_key)
        session_name = session.get("session_name", "")
        laps_raw     = get_laps(session_key, HIST_TTL)
        stints_raw   = get_stints(session_key, HIST_TTL)
        drv_raw      = get_drivers(session_key, HIST_TTL)
        summaries    = analyse_fp(laps_raw, stints_raw, drv_raw, session_name=session_name)
        weather      = get_weather_summary(session_key, HIST_TTL)
        return {
            "session": session,
            "session_mode": _session_mode(session),
            "drivers": [s.to_dict() for s in summaries],
            "compound_field_summary": _field_compound_summary(summaries),
            "weather": weather,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/pre_race_strategy")
def pre_race_strategy(session_key: int, total_laps: int = 71):
    """
    Pre-race strategy forecast from FP data.
    Builds deg curves from all available FP sessions for this meeting and
    returns the top 1-stop and 2-stop strategies across all starting compounds,
    so teams/analysts can plan before the race starts.

    total_laps: circuit lap count (defaults to 71 for Austria / Red Bull Ring).
    """
    try:
        session     = get_session(session_key)
        meeting_key = session.get("meeting_key")
        circuit     = session.get("circuit_short_name", "")

        # Gather all FP sessions in this meeting
        all_sessions_raw = sorted(
            _get("sessions", meeting_key=meeting_key),
            key=lambda s: s.get("date_start", "")
        )
        fp_sessions = [s for s in all_sessions_raw
                       if s.get("session_type", "").lower() == "practice"]
        fp_names = ["FP1", "FP2", "FP3"]

        fp_data = []
        for i, fp_s in enumerate(fp_sessions[:3]):
            try:
                fp_data.append((
                    fp_names[i],
                    get_laps(fp_s["session_key"], HIST_TTL),
                    get_stints(fp_s["session_key"], HIST_TTL),
                ))
            except Exception:
                pass

        if not fp_data:
            raise HTTPException(status_code=404, detail="No FP data available yet")

        curves   = build_deg_curves(fp_data)
        sc_prob  = sc_probability([], 0, total_laps, circuit)

        # Field baseline from available compound baselines
        baselines = [c.baseline for c in curves.values() if c.baseline > 0]
        field_bl  = sum(baselines) / len(baselines) if baselines else 90.0

        # Generate optimal 1-stop and 2-stop for each starting compound
        strategies = []
        for start_c in DRY:
            strat = optimize_strategy(
                current_lap=0,
                total_laps=total_laps,
                current_compound=start_c,
                current_age=0,
                pace_delta=0.0,
                curves=curves,
                field_baseline=field_bl,
                needs_compound_change=True,
            )
            stops = len(strat.pits_remaining)
            compounds_seq = [start_c] + [p.compound for p in strat.pits_remaining]
            stint_lengths = []
            prev = 0
            for p in strat.pits_remaining:
                stint_lengths.append(p.lap - prev)
                prev = p.lap
            stint_lengths.append(total_laps - prev)
            strategies.append({
                "start_compound":  start_c,
                "stops":           stops,
                "compound_sequence": compounds_seq,
                "pit_laps":        [p.lap for p in strat.pits_remaining],
                "stint_lengths":   stint_lengths,
                "total_time":      round(strat.total_time_from_now, 2),
            })

        # Sort by total time — best strategy first
        strategies.sort(key=lambda s: s["total_time"])

        return {
            "session_key":   session_key,
            "meeting_key":   meeting_key,
            "circuit":       circuit,
            "total_laps":    total_laps,
            "sc_probability": sc_prob,
            "fp_sessions_used": [fp_names[i] for i in range(len(fp_data))],
            "deg_curves":    curves_to_dict(curves),
            "strategies":    strategies,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/quali_analysis")
def quali_analysis(session_key: int):
    try:
        session    = get_session(session_key)
        laps_raw   = get_laps(session_key, HIST_TTL)
        stints_raw = get_stints(session_key, HIST_TTL)
        drv_raw    = get_drivers(session_key, HIST_TTL)
        summaries  = analyse_quali(laps_raw, stints_raw, drv_raw)
        return {
            "session": session,
            "session_mode": _session_mode(session),
            "drivers": [s.to_dict() for s in summaries],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/tyre_inventory")
def tyre_inventory(session_key: int):
    """
    Returns remaining new tyre sets per driver for the meeting containing
    this session. Counts new sets (tyre_age_at_start=0) opened across all
    sessions up to and including the given session_key, then caps each
    driver's total at the real race-day pool the FIA regulations leave after
    mandatory in-weekend returns (see engine.tyre_inventory module docstring)
    — not just the full weekend allocation.

    q3_drivers is left at compute_inventory's default (unknown -> nobody
    treated as Q3) here: this endpoint can be called before qualifying has
    even happened, and mid-weekend Q3 status isn't part of this endpoint's
    data flow. That means Q3 qualifiers show one set more than they'll
    actually have on race day — a known, minor simplification, not a wrong
    total for the field generally.
    """
    try:
        session    = get_session(session_key)
        meeting_key = session.get("meeting_key")

        # Get all sessions in this meeting, ordered by date
        all_sessions = _cached_get(
            f"meeting_sessions:{meeting_key}", "sessions", HIST_TTL,
            meeting_key=meeting_key
        )
        all_sessions = sorted(all_sessions, key=lambda s: s["date_start"])

        # Collect sessions up to and including the current one
        relevant_sessions = []
        for s in all_sessions:
            relevant_sessions.append(s)
            if s["session_key"] == session_key:
                break

        # Detect sprint weekend (has a session named "Sprint")
        session_names = [s.get("session_name", "") for s in all_sessions]
        is_sprint = any("sprint" in n.lower() for n in session_names
                        if "qualifying" not in n.lower())

        # Fetch stints for each relevant session
        stints_by_session = []
        for s in relevant_sessions:
            sk = s["session_key"]
            try:
                stints = _cached_get(f"stints:{sk}", "stints", HIST_TTL,
                                     session_key=sk)
                stints_by_session.append(stints)
            except Exception:
                stints_by_session.append([])

        drivers_raw = get_drivers(session_key, HIST_TTL)
        inventory   = compute_inventory(stints_by_session, drivers_raw, is_sprint)

        return {
            "session_key": session_key,
            "meeting_key": meeting_key,
            "sessions_counted": [s["session_name"] for s in relevant_sessions],
            "is_sprint": is_sprint,
            "drivers": [d.to_dict() for d in inventory],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/strategy_duel")
def strategy_duel_route(session_key: int, total_laps: int = None):
    """1-stop vs 2-stop head-to-head ("the knife") for this session's meeting.

    Builds tyre-degradation curves from the meeting's practice sessions — and
    from the race itself if this is a completed race — then prices the optimal
    1-stop against the optimal 2-stop lap by lap. Works both pre-race (FP curves
    only; pass total_laps for the circuit's race distance) and retrospectively
    (a finished race supplies its own deg and lap count). Returns the lap-by-lap
    "1-stopper ahead (s)" trace, both pit plans, and the gap at the flag.
    """
    try:
        session     = get_session(session_key)
        meeting_key = session.get("meeting_key")
        mode        = _session_mode(session)

        # Practice sessions in this meeting → weighted deg-curve prior
        all_sessions = sorted(
            _get("sessions", meeting_key=meeting_key),
            key=lambda s: s.get("date_start", "")
        )
        fp_sessions = [s for s in all_sessions
                       if s.get("session_type", "").lower() == "practice"]
        fp_names = ["FP1", "FP2", "FP3"]
        fp_data = []
        for i, fp_s in enumerate(fp_sessions[:3]):
            try:
                fp_data.append((
                    fp_names[i],
                    get_laps(fp_s["session_key"], HIST_TTL),
                    get_stints(fp_s["session_key"], HIST_TTL),
                ))
            except Exception:
                pass

        race_laps     = get_laps(session_key, HIST_TTL)
        race_stints   = get_stints(session_key, HIST_TTL)
        race_distance = max((l["lap_number"] for l in race_laps), default=0)

        # Fold the race's own degradation in when it has meaningfully run
        if mode in ("RACE", "SPRINT") and race_distance > 30:
            fp_data.append(("RACE", race_laps, race_stints))

        if not fp_data:
            raise HTTPException(status_code=404,
                                detail="No practice or race data available yet")

        tl = total_laps or (race_distance if mode in ("RACE", "SPRINT") else 0)
        if not tl:
            raise HTTPException(
                status_code=400,
                detail="total_laps is required for a non-race session")

        curves    = build_deg_curves(fp_data)
        baselines = [c.baseline for c in curves.values() if c.baseline > 0]
        field_bl  = statistics.median(baselines) if baselines else 90.0
        pit_loss  = get_avg_pit_loss(session_key, HIST_TTL) or PIT_LOSS

        duel = strategy_duel(curves, field_bl, pit_loss, tl)
        if duel is None:
            raise HTTPException(
                status_code=422,
                detail="Race too short to compare a 1-stop against a 2-stop")

        return {
            "session_key":    session_key,
            "meeting_key":    meeting_key,
            "circuit":        session.get("circuit_short_name", ""),
            "session_mode":   mode,
            "field_baseline": round(field_bl, 3),
            "deg_curves":     curves_to_dict(curves),
            **duel,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/race_charts")
def race_charts_route(session_key: int):
    """RSS-style per-race chart datasets, all rebuilt from this race's public lap
    timing: the gap-to-leader trace (#5), the rejoin trap (#4a), the leader's
    lapping tax (#4b), and the decision-on-one-page panel (#3)."""
    try:
        session = get_session(session_key)
        if _session_mode(session) not in ("RACE", "SPRINT"):
            raise HTTPException(status_code=400,
                                detail="Race charts are only available for race sessions")

        all_laps    = get_laps(session_key, HIST_TTL)
        race_stints = get_stints(session_key, HIST_TTL)
        drivers_raw = get_drivers(session_key, HIST_TTL)
        total_laps  = max((l["lap_number"] for l in all_laps), default=0)
        if total_laps < 5:
            raise HTTPException(status_code=422, detail="Not enough lap data for race charts")

        stints_by_driver: dict[int, list[dict]] = {}
        for s in race_stints:
            stints_by_driver.setdefault(s["driver_number"], []).append(s)
        acronyms = {num: (d.get("name_acronym") or str(num))
                    for num, d in drivers_raw.items()}
        team_colours = {num: d.get("team_colour") for num, d in drivers_raw.items()}

        pit_loss = get_avg_pit_loss(session_key, HIST_TTL) or PIT_LOSS
        curves   = build_degradation_curves(all_laps, race_stints)

        # A rough pit window from the best 1-stop on this race's deg curves.
        window = None
        try:
            strats = generate_strategies(0, total_laps, "MEDIUM", 0, curves)
            one = next((s for s in strats if s.stop_count == 1 and len(s.stints) >= 2), None)
            if one:
                pit = one.stints[0].end_lap
                window = {"earliest": max(1, pit - 3),
                          "latest": min(total_laps, pit + 3), "target": pit}
        except Exception:
            pass

        baselines = [c.baseline for c in curves.values()
                     if getattr(c, "baseline", 0) and c.baseline > 0]
        field_bl = statistics.median(baselines) if baselines else 90.0

        return {
            "session_key":   session_key,
            "circuit":       session.get("circuit_short_name", ""),
            "total_laps":    total_laps,
            "race_trace":    rc.race_trace(all_laps, stints_by_driver, acronyms, total_laps, team_colours),
            "rejoin_map":    rc.rejoin_map(all_laps, pit_loss, total_laps),
            "lapping_tax":   rc.lapping_tax(all_laps, total_laps),
            "decision_page": rc.decision_page(curves, pit_loss, total_laps, field_bl, window),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
