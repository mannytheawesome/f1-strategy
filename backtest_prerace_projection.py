"""
Backtest for the LAP-0 PRE-RACE projection specifically -- the win/podium
probability table shown on the "Race Briefings" page before a race starts,
built from build_prerace_data()'s `projection` field (FP + qualifying data
only, no in-race laps).

Built 2026-09-13 after a user-reported Madrid GP miss (actual winner given
~0% win probability, predicted P6; a driver who actually finished P10 was
given the #2 win-probability slot). Investigating that led to a much bigger
finding: backtest_full.py's EVAL_FRACTIONS = [0.25, 0.50, 0.75] means EVERY
accuracy number ever reported for this project (the 84.8% winner-hit
figure, etc.) only evaluates predictions made AFTER the race has already
started, using real in-race lap/position/gap data. The lap-0, FP/quali-only
projection this script tests had never been backtested at all before this.

Run: python3 backtest_prerace_projection.py
Results cached to cache/backtest_prerace_results.json so a partial/
interrupted run doesn't lose completed races.
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
from data.live import _get
from engine.prerace import build_prerace_data

RESULTS_FILE = "cache/backtest_prerace_results.json"
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
                        "race_session_key": race["session_key"]})
    return out


def _real_result(race_session_key: int) -> dict[int, int]:
    """{driver_number: finishing_position} for classified finishers."""
    results = _get("session_result", session_key=race_session_key)
    return {r["driver_number"]: r["position"] for r in results if r.get("position")}


def _load_cache() -> dict:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    os.makedirs("cache", exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(cache, f, indent=1)


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
    if not pack or not pack.get("projection"):
        return None

    forecasts = pack["projection"]["forecasts"]
    if not forecasts:
        return None

    try:
        real = _real_result(race_session_key)
    except Exception as e:
        print(f"  meeting {meeting_key}: couldn't fetch real result ({e})")
        return None
    if not real:
        return None

    actual_winner = min(real, key=lambda n: real[n])
    actual_podium = {n for n, p in real.items() if p <= 3}

    by_num = {f["driver_number"]: f for f in forecasts}
    predicted_winner = max(forecasts, key=lambda f: f["win_probability"])["driver_number"]
    predicted_podium = {f["driver_number"] for f in
                        sorted(forecasts, key=lambda f: -f["podium_probability"])[:3]}

    # MAE only over drivers we both predicted AND who classified in the race.
    errs = [abs(by_num[n]["predicted_position"] - real[n])
            for n in real if n in by_num]

    win_brier = statistics.mean(
        (f["win_probability"] - (1.0 if f["driver_number"] == actual_winner else 0.0)) ** 2
        for f in forecasts)
    podium_brier = statistics.mean(
        (f["podium_probability"] - (1.0 if f["driver_number"] in actual_podium else 0.0)) ** 2
        for f in forecasts)

    return {
        "meeting_key": meeting_key,
        "predicted_winner_acronym": by_num[predicted_winner]["acronym"],
        "predicted_winner_win_pct": round(by_num[predicted_winner]["win_probability"] * 100, 1),
        "actual_winner_acronym": next((f["acronym"] for f in forecasts
                                       if f["driver_number"] == actual_winner), "?"),
        "actual_winner_predicted_win_pct": round(by_num.get(actual_winner, {}).get("win_probability", 0.0) * 100, 1)
                                           if actual_winner in by_num else None,
        "winner_hit": predicted_winner == actual_winner,
        "podium_hit_count": len(predicted_podium & actual_podium),
        "mae": round(statistics.mean(errs), 2) if errs else None,
        "n_compared": len(errs),
        "win_brier": round(win_brier, 4),
        "podium_brier": round(podium_brier, 4),
    }


def main():
    cache = _load_cache()
    races = _completed_2026_races()
    print(f"{len(races)} completed 2026 race weekends found")
    for r in races:
        mk = str(r["meeting_key"])
        if mk in cache and cache[mk] is not None:
            continue
        print(f"evaluating {r['name']} (meeting {r['meeting_key']})...")
        result = evaluate_one(r["meeting_key"], r["race_session_key"])
        cache[mk] = result
        _save_cache(cache)
        if result:
            hit = "WINNER HIT" if result["winner_hit"] else (
                f"missed (predicted {result['predicted_winner_acronym']} "
                f"@{result['predicted_winner_win_pct']}%, actual "
                f"{result['actual_winner_acronym']} was given "
                f"{result['actual_winner_predicted_win_pct']}%)")
            print(f"  {hit} | podium {result['podium_hit_count']}/3 | MAE {result['mae']}")

    valid = [v for v in cache.values() if v is not None]
    print()
    print(f"=== {len(valid)} races evaluated ===")
    if not valid:
        return
    winner_rate = sum(1 for v in valid if v["winner_hit"]) / len(valid)
    avg_podium_hits = statistics.mean(v["podium_hit_count"] for v in valid)
    avg_mae = statistics.mean(v["mae"] for v in valid if v["mae"] is not None)
    avg_win_brier = statistics.mean(v["win_brier"] for v in valid)
    avg_podium_brier = statistics.mean(v["podium_brier"] for v in valid)
    print(f"winner-hit rate:        {winner_rate:.0%}  ({sum(1 for v in valid if v['winner_hit'])}/{len(valid)})")
    print(f"avg podium hits (of 3): {avg_podium_hits:.2f}")
    print(f"avg position MAE:       {avg_mae:.2f}")
    print(f"avg win Brier:          {avg_win_brier:.4f}  (lower is better; 0.25 = coin-flip-grade)")
    print(f"avg podium Brier:       {avg_podium_brier:.4f}")


if __name__ == "__main__":
    main()
