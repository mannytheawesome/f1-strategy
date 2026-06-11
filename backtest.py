"""
Backtest the prediction model against completed races.

For each race, runs /api/predict at 25%, 50%, and 75% race distance and
compares predicted finishing order against the actual classification.

Metrics:
  - winner_hit:   predicted P1 == actual P1
  - podium_hits:  size of intersection of predicted vs actual top 3
  - top10_hits:   intersection of predicted vs actual top 10
  - mae:          mean |predicted_pos - actual_pos| over drivers who finished
                  (retirements after the prediction lap are excluded — they
                  are not predictable from pace/strategy data)

Usage:
  python backtest.py
"""

import requests
import sys
import time

API = "http://127.0.0.1:8001"


def get_json(url: str, timeout: int = 300, retries: int = 4):
    """GET with retry/backoff — OpenF1 rate-limits aggressively."""
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            data = r.json()
            if isinstance(data, dict) and data.get("detail"):
                raise ValueError(data["detail"][:80])
            return data
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(10 * (attempt + 1))

RACES = [
    ("Australia", 11234),
    ("China",     11245),
    ("Japan",     11253),
    ("Miami",     11280),
    ("Canada",    11291),
]

EVAL_FRACTIONS = [0.25, 0.50, 0.75]


def get_actual_result(session_key: int) -> tuple[dict[int, int], dict[int, int]]:
    """Returns ({driver_number: final_position}, {driver_number: laps_completed})."""
    pos_raw = get_json(f"https://api.openf1.org/v1/position?session_key={session_key}")
    final: dict[int, int] = {}
    for p in pos_raw:
        final[p["driver_number"]] = p["position"]

    laps_raw = get_json(f"https://api.openf1.org/v1/laps?session_key={session_key}")
    laps_done: dict[int, int] = {}
    for l in laps_raw:
        n = l["driver_number"]
        laps_done[n] = max(laps_done.get(n, 0), l["lap_number"])

    return final, laps_done


def evaluate_race(name: str, session_key: int) -> list[dict]:
    actual, laps_done = get_actual_result(session_key)
    total_laps = max(laps_done.values())
    finishers = {n for n, l in laps_done.items() if l >= total_laps - 2}

    results = []
    for frac in EVAL_FRACTIONS:
        eval_lap = int(total_laps * frac)
        try:
            data = get_json(
                f"{API}/api/predict?session_key={session_key}&lap={eval_lap}")
        except Exception as e:
            print(f"  {name} lap {eval_lap}: FAILED {e}")
            continue

        forecasts = data.get("forecasts", [])
        if not forecasts:
            print(f"  {name} lap {eval_lap}: no forecasts")
            continue

        pred = {f["driver_number"]: f["predicted_position"] for f in forecasts}

        # Drivers still classified as finishers at race end AND predicted
        comparable = [n for n in pred if n in finishers and n in actual]
        # Re-rank both sides over the comparable set so retirements between
        # eval lap and flag don't shift everyone's error
        pred_rank = {n: r for r, n in enumerate(
            sorted(comparable, key=lambda n: pred[n]), 1)}
        act_rank = {n: r for r, n in enumerate(
            sorted(comparable, key=lambda n: actual[n]), 1)}

        errors = [abs(pred_rank[n] - act_rank[n]) for n in comparable]
        mae = sum(errors) / len(errors) if errors else None

        pred_order = sorted(pred, key=lambda n: pred[n])
        act_order = sorted(actual, key=lambda n: actual[n])

        winner_hit = pred_order[0] == act_order[0]
        podium_hits = len(set(pred_order[:3]) & set(act_order[:3]))
        top10_hits = len(set(pred_order[:10]) & set(act_order[:10]))

        results.append({
            "race": name, "lap": eval_lap, "total": total_laps,
            "winner": winner_hit, "podium": podium_hits,
            "top10": top10_hits, "mae": mae,
            "n_compared": len(comparable),
        })
        wflag = "✓" if winner_hit else "✗"
        print(f"  {name:<10} lap {eval_lap:>2}/{total_laps}: winner {wflag}  "
              f"podium {podium_hits}/3  top10 {top10_hits}/10  "
              f"MAE {mae:.2f} (n={len(comparable)})")
    return results


def main():
    all_results = []
    for name, key in RACES:
        print(f"\n{name} (session {key}):")
        all_results.extend(evaluate_race(name, key))

    if not all_results:
        print("No results")
        return

    print("\n" + "=" * 60)
    print("SUMMARY")
    n = len(all_results)
    print(f"  Winner hit rate: {sum(r['winner'] for r in all_results)}/{n}")
    print(f"  Avg podium hits: {sum(r['podium'] for r in all_results)/n:.2f}/3")
    print(f"  Avg top10 hits:  {sum(r['top10'] for r in all_results)/n:.2f}/10")
    maes = [r["mae"] for r in all_results if r["mae"] is not None]
    print(f"  Avg MAE:         {sum(maes)/len(maes):.2f} positions")

    print("\nBy race distance:")
    for frac, lbl in [(0.25, '25%'), (0.50, '50%'), (0.75, '75%')]:
        subset = [r for r in all_results
                  if abs(r["lap"] / r["total"] - frac) < 0.1]
        if subset:
            m = sum(r["mae"] for r in subset) / len(subset)
            w = sum(r["winner"] for r in subset)
            print(f"  {lbl}: winner {w}/{len(subset)}, MAE {m:.2f}")


if __name__ == "__main__":
    main()
