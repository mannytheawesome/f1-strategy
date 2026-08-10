"""
Full-history backtest + parameter tuning harness.

Phase 1 (collect): download and disk-cache raw OpenF1 data for every race
  weekend 2023-2026 (FP sessions + race). Resumable — re-running skips
  anything already cached in ./cache/.

Phase 2 (evaluate): run the prediction engine directly (no HTTP) at 25/50/75%
  distance for every race, computing winner/podium/top10/MAE metrics.

Phase 3 (sweep): grid-search track_position_weight (street vs normal) and
  other knobs over the cached data, reporting the best configuration.

Usage:
  python backtest_full.py collect      # phase 1 — slow, rate-limited
  python backtest_full.py evaluate     # phase 2 — uses default params
  python backtest_full.py sweep        # phase 3 — parameter grid search
"""

from __future__ import annotations
import json
import os
import sys
import time
import statistics
import urllib.request
import urllib.parse
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

RESULTS_FILE = os.path.join(CACHE_DIR, "backtest_results.json")

YEARS = [2023, 2024, 2025, 2026]
EVAL_FRACTIONS = [0.25, 0.50, 0.75]

from engine.circuits import STREET_CIRCUITS as _CANONICAL_STREET
from engine.circuits import (STREET_TRACK_POSITION_WEIGHT,
                             NORMAL_TRACK_POSITION_WEIGHT)
from engine.pit_loss import pit_loss_for
from data.live import _merge_stint_fragments
# The offline harness matches a couple of extra name spellings that show up in
# historical OpenF1 circuit_short_name values.
STREET_CIRCUITS = _CANONICAL_STREET | {"las vegas", "marina bay"}


# ── Disk-cached OpenF1 fetch ──────────────────────────────────────────────────

def _cache_path(endpoint: str, params: dict) -> str:
    key = endpoint + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    safe = key.replace("/", "_").replace(" ", "")
    return os.path.join(CACHE_DIR, safe + ".json")


def fetch(endpoint: str, max_retries: int = 6, cache_only: bool = False, **params):
    path = _cache_path(endpoint, params)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    if cache_only:
        raise FileNotFoundError(f"not in cache: {endpoint} {params}")

    qs = urllib.parse.urlencode(params)
    url = f"https://api.openf1.org/v1/{endpoint}?{qs}"
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read())
            with open(path, "w") as f:
                json.dump(data, f)
            time.sleep(2.2)   # stay under 30 req/min
            return data
        except urllib.error.HTTPError as e:
            # 404 means this session simply has no data (a race that hasn't run,
            # or one OpenF1 never published laps for). Retrying can't help, and
            # the escalating backoff burned ~5 minutes per such session.
            if e.code == 404:
                print(f"    fetch {endpoint} {params} -> 404, no data — skipping")
                raise RuntimeError(f"no data (404): {url}") from e
            wait = 15 * (attempt + 1)
            print(f"    fetch {endpoint} {params} failed ({e}) — retry in {wait}s")
            time.sleep(wait)
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"    fetch {endpoint} {params} failed ({e}) — retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"fetch failed permanently: {url}")


# ── Race weekend enumeration ──────────────────────────────────────────────────

def enumerate_weekends() -> list[dict]:
    """Returns [{year, country, circuit, race_key, fp_keys, total_laps?}]"""
    weekends = []
    for year in YEARS:
        sessions = fetch("sessions", year=year)
        by_meeting: dict[int, list[dict]] = {}
        for s in sessions:
            by_meeting.setdefault(s["meeting_key"], []).append(s)
        for mk, sess in sorted(by_meeting.items()):
            race = next((s for s in sess if s.get("session_name") == "Race"), None)
            if race is None:
                continue
            fps = sorted(
                (s for s in sess if s.get("session_type") == "Practice"),
                key=lambda s: s.get("date_start", "")
            )
            weekends.append({
                "year": year,
                "country": race.get("country_name", ""),
                "circuit": race.get("circuit_short_name", ""),
                "race_key": race["session_key"],
                "fp_keys": [s["session_key"] for s in fps],
            })
    return weekends


# ── Data assembly per race ────────────────────────────────────────────────────

def _sanitise_stints(rows: list[dict]) -> list[dict]:
    """Same cleaning the app applies in data.live.get_stints.

    The harness reads raw cached rows, so without this it evaluates on OpenF1's
    fragmented stints — 1-lap slivers that invent extra stops — while the live
    app sees the repaired ones. Measuring the engine on data the engine never
    sees in production makes the backtest quietly wrong.
    """
    rows = [s for s in rows if s.get("lap_start") is not None]
    rows = [s for s in rows
            if not (s.get("lap_end") is not None and s["lap_end"] < s["lap_start"])]
    rows = [{**s,
             "compound": s.get("compound") or "UNKNOWN",
             "tyre_age_at_start": s.get("tyre_age_at_start") or 0}
            for s in rows]
    return _merge_stint_fragments(rows)


def load_weekend(w: dict, cache_only: bool = False) -> dict | None:
    """Fetch all needed data for one weekend. Returns None if unusable."""
    _fetch = lambda ep, **kw: fetch(ep, cache_only=cache_only, **kw)
    try:
        race_laps   = _fetch("laps", session_key=w["race_key"])
        race_stints = _fetch("stints", session_key=w["race_key"])
        drivers_raw = _fetch("drivers", session_key=w["race_key"])
        positions   = _fetch("position", session_key=w["race_key"])
        intervals   = _fetch("intervals", session_key=w["race_key"])
    except (RuntimeError, FileNotFoundError):
        return None
    if not race_laps or not drivers_raw:
        return None

    fp_data = []
    names = ["FP1", "FP2", "FP3"]
    for i, k in enumerate(w["fp_keys"][:3]):
        try:
            fl = _fetch("laps", session_key=k)
            fs = _fetch("stints", session_key=k)
            fp_data.append((names[i] if i < 3 else f"FP{i+1}", fl, _sanitise_stints(fs)))
        except (RuntimeError, FileNotFoundError):
            pass

    return {
        "weekend": w,
        "race_laps": race_laps,
        "race_stints": _sanitise_stints(race_stints),
        "drivers": {d["driver_number"]: d for d in drivers_raw},
        "positions": positions,
        "intervals": intervals,
        "fp_data": fp_data,
    }


# ── State reconstruction at lap N (standalone, no live.py dependency) ────────

def state_at_lap(data: dict, lap: int) -> list[dict]:
    """Build the serialised driver list the predictor expects, as of end of lap N."""
    laps_to_now = [l for l in data["race_laps"] if l["lap_number"] <= lap]

    laps_done: dict[int, int] = {}
    for l in laps_to_now:
        n = l["driver_number"]
        laps_done[n] = max(laps_done.get(n, 0), l["lap_number"])

    # Position at this lap: latest position record before the lap's rough end.
    # Use per-driver lap completion order as proxy: sort by (-laps_done, last lap date)
    # Simpler robust proxy: use position feed filtered by date <= date of lap N completion
    lap_dates = [l.get("date_start") for l in laps_to_now if l.get("date_start")]
    cutoff = max(lap_dates) if lap_dates else None

    pos_at: dict[int, int] = {}
    for p in data["positions"]:
        if cutoff and p.get("date") and p["date"] > cutoff:
            continue
        pos_at[p["driver_number"]] = p["position"]

    # Interval/gap at this lap
    gap_at: dict[int, dict] = {}
    for iv in data["intervals"]:
        if cutoff and iv.get("date") and iv["date"] > cutoff:
            continue
        gap_at[iv["driver_number"]] = iv

    # Stints: current compound and age at lap N
    cur_stint: dict[int, dict] = {}
    compounds_used: dict[int, set] = {}
    for s in data["race_stints"]:
        n = s["driver_number"]
        if s["lap_start"] > lap:
            continue
        compounds_used.setdefault(n, set()).add(s.get("compound", ""))
        cur = cur_stint.get(n)
        if cur is None or s["lap_start"] > cur["lap_start"]:
            cur_stint[n] = s

    # Retired: hasn't completed a lap within 3 of the current leader lap
    leader_lap = max(laps_done.values()) if laps_done else lap

    out = []
    for n, meta in data["drivers"].items():
        if n not in laps_done:
            continue
        st = cur_stint.get(n, {})
        age0 = st.get("tyre_age_at_start", 0) or 0
        age = age0 + (laps_done[n] - st.get("lap_start", laps_done[n]))
        iv = gap_at.get(n, {})
        retired = laps_done[n] < leader_lap - 3
        out.append({
            "driver_number": n,
            "acronym": meta.get("name_acronym", str(n)),
            "position": pos_at.get(n, 99),
            "compound": st.get("compound") or "MEDIUM",
            "tyre_age": max(0, age),
            "gap_to_leader": iv.get("gap_to_leader"),
            "interval": iv.get("interval"),
            "retired": retired,
            "compounds_used": list(compounds_used.get(n, set())),
            "current_lap": laps_done[n],
        })
    out.sort(key=lambda d: d["position"])
    return out


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_weekend(data: dict, tpw_street: float, tpw_normal: float) -> list[dict]:
    from engine.predictor import (build_deg_curves, build_pace_model,
                                  detect_sc, simulate_race)

    w = data["weekend"]
    laps_done: dict[int, int] = {}
    for l in data["race_laps"]:
        n = l["driver_number"]
        laps_done[n] = max(laps_done.get(n, 0), l["lap_number"])
    total_laps = max(laps_done.values())
    if total_laps < 20:
        return []

    finishers = {n for n, l in laps_done.items() if l >= total_laps - 2}
    final_pos: dict[int, int] = {}
    for p in data["positions"]:
        final_pos[p["driver_number"]] = p["position"]

    is_street = any(c in (w["circuit"] or "").lower() for c in STREET_CIRCUITS)
    tpw = tpw_street if is_street else tpw_normal

    results = []
    for frac in EVAL_FRACTIONS:
        eval_lap = int(total_laps * frac)
        laps_to_now = [l for l in data["race_laps"] if l["lap_number"] <= eval_lap]

        fp_plus_race = list(data["fp_data"])
        if len(laps_to_now) > 60:
            fp_plus_race.append(("RACE", laps_to_now, data["race_stints"]))

        try:
            curves = build_deg_curves(fp_plus_race)
            sc = detect_sc(laps_to_now)
            pace = build_pace_model(laps_to_now, sc, data["drivers"],
                                    curves, data["race_stints"])
            state = state_at_lap(data, eval_lap)
            forecasts = simulate_race(state, eval_lap, total_laps, curves,
                                      pace, sc, track_position_weight=tpw,
                                      pit_loss=pit_loss_for(w["circuit"]))
        except Exception as e:
            results.append({"race": f"{w['year']} {w['country']}", "lap": eval_lap,
                            "error": str(e)[:80]})
            continue

        if not forecasts:
            continue

        pred = {f.driver_number: f.predicted_position for f in forecasts}
        comparable = [n for n in pred if n in finishers and n in final_pos]
        if len(comparable) < 8:
            continue
        pred_rank = {n: r for r, n in enumerate(
            sorted(comparable, key=lambda n: pred[n]), 1)}
        act_rank = {n: r for r, n in enumerate(
            sorted(comparable, key=lambda n: final_pos[n]), 1)}
        errors = [abs(pred_rank[n] - act_rank[n]) for n in comparable]

        pred_order = sorted(pred, key=lambda n: pred[n])
        act_order = sorted(final_pos, key=lambda n: final_pos[n])

        results.append({
            "race": f"{w['year']} {w['country']}",
            "circuit": w["circuit"],
            "street": is_street,
            "frac": frac,
            "lap": eval_lap,
            "total": total_laps,
            "winner": pred_order[0] == act_order[0],
            "podium": len(set(pred_order[:3]) & set(act_order[:3])),
            "top10": len(set(pred_order[:10]) & set(act_order[:10])),
            "mae": sum(errors) / len(errors),
            "n": len(comparable),
        })
    return results


# ── Phases ────────────────────────────────────────────────────────────────────

def phase_collect():
    weekends = enumerate_weekends()
    print(f"{len(weekends)} race weekends found")
    ok = 0
    for i, w in enumerate(weekends):
        label = f"{w['year']} {w['country']}"
        print(f"[{i+1}/{len(weekends)}] {label} ...", flush=True)
        data = load_weekend(w)
        if data:
            ok += 1
    print(f"\nCollected {ok}/{len(weekends)} weekends into {CACHE_DIR}")


def phase_evaluate(tpw_street=STREET_TRACK_POSITION_WEIGHT,
                   tpw_normal=NORMAL_TRACK_POSITION_WEIGHT, quiet=False):
    weekends = enumerate_weekends()
    all_results = []
    for w in weekends:
        data = load_weekend(w)
        if not data:
            continue
        res = evaluate_weekend(data, tpw_street, tpw_normal)
        ok = [r for r in res if "error" not in r]
        all_results.extend(ok)
        if not quiet:
            for r in ok:
                wflag = "✓" if r["winner"] else "✗"
                print(f"  {r['race']:<22} {int(r['frac']*100)}%: {wflag} "
                      f"podium {r['podium']}/3 top10 {r['top10']}/10 MAE {r['mae']:.2f}")
            for r in res:
                if "error" in r:
                    print(f"  {r['race']:<22} lap {r['lap']}: ERROR {r['error']}")

    if not all_results:
        print("no results")
        return None

    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=1)

    summary = summarize(all_results)
    print_summary(summary, all_results)
    return all_results


def summarize(results: list[dict]) -> dict:
    n = len(results)
    return {
        "n": n,
        "winner_rate": sum(r["winner"] for r in results) / n,
        "podium_avg": sum(r["podium"] for r in results) / n,
        "top10_avg": sum(r["top10"] for r in results) / n,
        "mae": sum(r["mae"] for r in results) / n,
    }


def print_summary(s: dict, results: list[dict]):
    print("\n" + "=" * 64)
    print(f"SUMMARY over {s['n']} checkpoints")
    print(f"  winner rate: {s['winner_rate']:.1%}")
    print(f"  podium avg:  {s['podium_avg']:.2f}/3")
    print(f"  top10 avg:   {s['top10_avg']:.2f}/10")
    print(f"  MAE:         {s['mae']:.2f} positions")
    for frac in EVAL_FRACTIONS:
        sub = [r for r in results if r["frac"] == frac]
        if sub:
            ss = summarize(sub)
            print(f"  at {int(frac*100)}%: winner {ss['winner_rate']:.0%}, MAE {ss['mae']:.2f} (n={ss['n']})")
    for street in (True, False):
        sub = [r for r in results if r["street"] == street]
        if sub:
            ss = summarize(sub)
            kind = "street" if street else "normal"
            print(f"  {kind} circuits: winner {ss['winner_rate']:.0%}, MAE {ss['mae']:.2f} (n={ss['n']})")


def phase_sweep():
    """Grid-search track position weights over the cached data."""
    weekends = enumerate_weekends()
    loaded = []
    for w in weekends:
        d = load_weekend(w, cache_only=True)
        if d:
            loaded.append(d)
    print(f"{len(loaded)} weekends loaded for sweep")

    grid_street = [0.5, 0.65, 0.75, 0.85]
    grid_normal = [0.3, 0.4, 0.5, 0.6]

    best = None
    for ts in grid_street:
        for tn in grid_normal:
            results = []
            for d in loaded:
                results.extend(
                    r for r in evaluate_weekend(d, ts, tn) if "error" not in r)
            if not results:
                continue
            s = summarize(results)
            line = (f"tpw_street={ts} tpw_normal={tn}: MAE {s['mae']:.3f} "
                    f"winner {s['winner_rate']:.1%} top10 {s['top10_avg']:.2f}")
            print(line, flush=True)
            if best is None or s["mae"] < best[0]["mae"]:
                best = (s, ts, tn)

    if best:
        s, ts, tn = best
        print(f"\nBEST: tpw_street={ts} tpw_normal={tn} "
              f"(MAE {s['mae']:.3f}, winner {s['winner_rate']:.1%})")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "evaluate"
    if phase == "collect":
        phase_collect()
    elif phase == "evaluate":
        phase_evaluate()
    elif phase == "sweep":
        phase_sweep()
    else:
        print(__doc__)
