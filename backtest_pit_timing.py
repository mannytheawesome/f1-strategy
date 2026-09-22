"""
Backtest for the pre-race strategy chart's predicted OPTIMAL PIT LAP,
specifically -- as distinct from backtest_prerace_projection.py (finish
position / win probability) and audit_strategies.py (structural sanity of
the candidate list). No prior script checks whether the pit LAP our model
recommends for a given compound sequence is actually close to when real
drivers running that same sequence pitted.

Built 2026-09-22 after a user-reported gap: our Monza 2026 Soft->Medium
candidate recommended pitting at lap 22 (window 19-25); the user reported
F1.com's own published strategy guide showed the same Soft->Medium plan
with a window of 22-28. A single-race check of the SOFT/MEDIUM MIN_DEG
floors found they don't explain it (real race-measured Monza degradation
for MEDIUM/HARD was actually HIGHER than the floors, which would push our
prediction earlier still, not later) -- so this checks for a real,
general, cross-race bias instead of tuning on the one anecdote.

Method: for each completed 2026 race, build the same pre-race data pack
the live site serves (FP-only degradation curves, no race data), find
every REAL driver who ran a genuine two-stint one-stop race (excluding
laps lost to pit stops entirely from the "genuine" definition -- a driver
who stopped under a Safety Car or for damage is not testing the model's
green-flag-only pace assumptions), and compare their real pit lap against
our model's own optimize_strategy() answer for that exact compound
sequence and stop count. A real driver's own choice is shaped by track
position/undercut play too, so any single comparison is noisy -- the
question is whether the SIGNED error is centred on zero across many of
them, or systematically one-sided.

Run: python3 backtest_pit_timing.py
Results cached to cache/backtest_pit_timing_results.json.
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
from data.live import _get, get_stints, HIST_TTL
from engine.prerace import build_prerace_data, _prerace_sources
from engine.predictor import optimize_strategy

RESULTS_FILE = "cache/backtest_pit_timing_results.json"
MAX_RETRIES = 4
RETRY_DELAY_S = 5


def _completed_2026_races() -> list[dict]:
    meetings = _get("meetings", year=2026)
    races = [m for m in meetings if "grand prix" in (m.get("meeting_name") or "").lower()]
    races.sort(key=lambda m: m["date_start"])
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for m in races:
        try:
            sessions = _get("sessions", meeting_key=m["meeting_key"])
        except Exception:
            continue
        race = next((s for s in sessions if s.get("session_type") == "Race"), None)
        if not race or not race.get("date_end"):
            continue
        end = datetime.datetime.fromisoformat(race["date_end"].replace("Z", "+00:00"))
        if end < now:
            out.append({"meeting_key": m["meeting_key"], "name": m["meeting_name"],
                        "circuit": m.get("circuit_short_name"),
                        "race_session_key": race["session_key"]})
    return out


def _real_one_stops(race_session_key: int, total_laps: int) -> list[dict]:
    """Real drivers who ran exactly two stints (one genuine stop) this race,
    with the compound sequence and the lap they pitted on. Excludes stints
    that don't cover essentially the whole race distance (a driver who
    retired early, or started from the pit lane / had an extra tyre-only
    stop for damage, would corrupt the comparison)."""
    stints = get_stints(race_session_key, HIST_TTL)
    by_driver: dict[int, list[dict]] = {}
    for s in stints:
        by_driver.setdefault(s["driver_number"], []).append(s)

    out = []
    for num, driver_stints in by_driver.items():
        driver_stints.sort(key=lambda s: s.get("stint_number", 0))
        if len(driver_stints) != 2:
            continue
        s1, s2 = driver_stints
        c1, c2 = s1.get("compound"), s2.get("compound")
        if c1 not in ("SOFT", "MEDIUM", "HARD") or c2 not in ("SOFT", "MEDIUM", "HARD"):
            continue
        if s1.get("lap_start") != 1:
            continue
        last_lap = s2.get("lap_end")
        if not last_lap or last_lap < total_laps - 2:
            continue   # retired / didn't finish close to race distance
        pit_lap = s1.get("lap_end")
        if not pit_lap:
            continue
        # A first-stint this short isn't a tyre-strategy decision -- it's
        # damage/incident/Lap-1-chaos (confirmed: Monza 2026 showed SIX
        # different drivers all pitting on exactly lap 3, which is a mass
        # Turn-1 incident, not six independent strategic calls). 8 laps
        # matches this codebase's existing DEG_LONGRUN min_laps convention
        # for "a real, representative stint."
        if pit_lap < 8:
            continue
        out.append({"driver_number": num, "sequence": [c1, c2], "real_pit_lap": pit_lap})
    return out


def evaluate_one(meeting_key: int, race_session_key: int) -> dict | None:
    pack = None
    for attempt in range(MAX_RETRIES):
        try:
            pack = build_prerace_data(meeting_key)
            break
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"  meeting {meeting_key}: gave up after {MAX_RETRIES} attempts ({e})")
                return None
            time.sleep(RETRY_DELAY_S)
    if not pack:
        return None

    total_laps = pack.get("meeting", {}).get("total_laps_assumed")
    if not total_laps:
        return None

    real_drivers = _real_one_stops(race_session_key, total_laps)
    if not real_drivers:
        return {"meeting_key": meeting_key, "matches": []}

    # Our model's own predicted-optimal lap for each real compound sequence,
    # forcing that exact start/end compound so it's an apples-to-apples
    # comparison against a driver who was locked into that same choice --
    # not just whichever sequence our DP happens to like best overall.
    by_seq: dict[tuple, int] = {}
    for s in pack["strategies"]:
        seq = tuple(s["compound_sequence"])
        if s["stops"] == 1 and len(seq) == 2:
            by_seq[seq] = s["pit_laps"][0]

    matches = []
    for d in real_drivers:
        seq = tuple(d["sequence"])
        if seq not in by_seq:
            continue
        predicted = by_seq[seq]
        matches.append({
            "driver_number": d["driver_number"],
            "sequence": d["sequence"],
            "real_pit_lap": d["real_pit_lap"],
            "predicted_pit_lap": predicted,
            "error_laps": d["real_pit_lap"] - predicted,   # + = we're too early
        })
    return {"meeting_key": meeting_key, "matches": matches}


def _load_cache() -> dict:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    os.makedirs("cache", exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(cache, f, indent=1)


def main():
    cache = _load_cache()
    races = _completed_2026_races()
    print(f"{len(races)} completed 2026 race weekends found")
    for r in races:
        mk = str(r["meeting_key"])
        if mk in cache and cache[mk] is not None:
            continue
        print(f"evaluating {r['name']} ({r['circuit']}, meeting {r['meeting_key']})...")
        result = evaluate_one(r["meeting_key"], r["race_session_key"])
        if result is not None:
            result["circuit"] = r["circuit"]
            result["name"] = r["name"]
        cache[mk] = result
        _save_cache(cache)
        if result:
            for m in result["matches"]:
                print(f"    {''.join(c[0] for c in m['sequence'])}: "
                      f"real={m['real_pit_lap']:2d}  predicted={m['predicted_pit_lap']:2d}  "
                      f"error={m['error_laps']:+d}")

    all_matches = []
    for v in cache.values():
        if v:
            for m in v["matches"]:
                m2 = dict(m)
                m2["circuit"] = v.get("circuit")
                all_matches.append(m2)

    print()
    print(f"=== {len(all_matches)} real one-stop drivers matched across "
          f"{sum(1 for v in cache.values() if v and v['matches'])} races ===")
    if not all_matches:
        return
    errs = [m["error_laps"] for m in all_matches]
    print(f"mean error (real - predicted): {statistics.mean(errs):+.2f} laps")
    print(f"median error:                  {statistics.median(errs):+.2f} laps")
    print(f"stdev:                         {statistics.pstdev(errs):.2f} laps")
    print(f"positive (we're too early):    {sum(1 for e in errs if e > 0)}/{len(errs)}")
    print(f"negative (we're too late):     {sum(1 for e in errs if e < 0)}/{len(errs)}")

    by_seq: dict[tuple, list[int]] = {}
    for m in all_matches:
        by_seq.setdefault(tuple(m["sequence"]), []).append(m["error_laps"])
    print()
    print("by compound sequence:")
    for seq, es in sorted(by_seq.items(), key=lambda kv: -len(kv[1])):
        print(f"  {'->'.join(seq):16s} n={len(es):3d}  mean_error={statistics.mean(es):+.2f}  "
              f"median={statistics.median(es):+.2f}")


if __name__ == "__main__":
    main()
