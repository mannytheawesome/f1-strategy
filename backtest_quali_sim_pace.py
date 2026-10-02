"""
Backtest for quali_sim_pace / quali_team_pace -- the "Qualifying simulation
pace" chart added to the pre-race briefing, built entirely from FP hotlap
stints (1-2 timed laps) so it's a genuine pre-qualifying PREDICTION, never
reading the real Qualifying session itself (see engine.prerace._quali_sim_pace).

Ground truth is the real Qualifying classification, which build_prerace_data
already fetches into pack["grid"] for any completed weekend -- no separate
real-result fetch needed, unlike backtest_prerace_projection.py (which has
to pull session_result for the race session specifically).

Metrics:
  - pole_team_hit / pole_driver_hit: does the model's #1-ranked team/driver
    match who actually took pole?
  - team_spearman / driver_spearman: rank correlation between the predicted
    order and the real grid order, over entrants present in both.

Run: python3 backtest_quali_sim_pace.py
Results cached to cache/backtest_quali_sim_results.json so a partial/
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

RESULTS_FILE = "cache/backtest_quali_sim_results.json"
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
        quali = next((s for s in sessions if s.get("session_type") == "Qualifying"), None)
        if not quali or not quali.get("date_end"):
            continue
        end = datetime.datetime.fromisoformat(quali["date_end"].replace("Z", "+00:00"))
        if end < now:
            out.append({"meeting_key": m["meeting_key"], "name": m["meeting_name"]})
    return out


def _load_cache() -> dict:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    os.makedirs("cache", exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(cache, f, indent=1)


def _spearman(pairs: list[tuple[int, int]]) -> float | None:
    """pairs of (predicted_rank, real_rank), both 1-indexed, no ties (ranks
    come from a stable sort in both our prediction and the real grid)."""
    n = len(pairs)
    if n < 2:
        return None
    d2_sum = sum((a - b) ** 2 for a, b in pairs)
    return round(1 - (6 * d2_sum) / (n * (n ** 2 - 1)), 3)


def evaluate_one(meeting_key: int) -> dict | None:
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

    quali_rows = pack.get("quali_sim_pace")
    team_rows = pack.get("quali_team_pace")
    grid = pack.get("grid")
    if not quali_rows or not team_rows or not grid:
        return None  # no hotlap data this weekend, or grid wasn't from quali

    # Real driver grid order (position 1 = pole), and each team's best
    # (lowest) grid position among its two cars -- same "quicker car
    # represents the team" convention _team_pace itself uses.
    real_driver_pos = {g["acronym"]: g["position"] for g in grid if g.get("position")}
    if not real_driver_pos:
        return None
    team_by_acronym = {g["acronym"]: g["team"] for g in grid if g.get("team")}
    real_team_best_pos: dict[str, int] = {}
    for acr, pos in real_driver_pos.items():
        team = team_by_acronym.get(acr)
        if not team:
            continue
        if team not in real_team_best_pos or pos < real_team_best_pos[team]:
            real_team_best_pos[team] = pos
    real_team_order = sorted(real_team_best_pos, key=lambda t: real_team_best_pos[t])
    real_team_rank = {t: i + 1 for i, t in enumerate(real_team_order)}

    real_pole_acronym = min(real_driver_pos, key=lambda a: real_driver_pos[a])
    real_pole_team = team_by_acronym.get(real_pole_acronym)

    predicted_pole_driver = quali_rows[0]["acronym"]  # already sorted by pace_delta
    predicted_pole_team = next((t["team"] for t in team_rows if not t["no_data"]), None)

    driver_pairs = [(r["pace_rank"], real_driver_pos[r["acronym"]])
                     for r in quali_rows if r["acronym"] in real_driver_pos]
    ranked_teams = [t for t in team_rows if not t["no_data"]]
    team_pairs = [(i + 1, real_team_rank[t["team"]])
                  for i, t in enumerate(ranked_teams) if t["team"] in real_team_rank]

    return {
        "meeting_key": meeting_key,
        "predicted_pole_driver": predicted_pole_driver,
        "real_pole_driver": real_pole_acronym,
        "pole_driver_hit": predicted_pole_driver == real_pole_acronym,
        "predicted_pole_team": predicted_pole_team,
        "real_pole_team": real_pole_team,
        "pole_team_hit": predicted_pole_team == real_pole_team,
        "driver_spearman": _spearman(driver_pairs),
        "driver_n": len(driver_pairs),
        "team_spearman": _spearman(team_pairs),
        "team_n": len(team_pairs),
    }


def main():
    cache = _load_cache()
    races = _completed_2026_races()
    print(f"{len(races)} completed 2026 qualifying sessions found")
    for r in races:
        mk = str(r["meeting_key"])
        if mk in cache and cache[mk] is not None:
            continue
        print(f"evaluating {r['name']} (meeting {r['meeting_key']})...")
        result = evaluate_one(r["meeting_key"])
        cache[mk] = result
        _save_cache(cache)
        if result:
            hit = "POLE TEAM HIT" if result["pole_team_hit"] else (
                f"missed (predicted {result['predicted_pole_team']}, "
                f"real pole {result['real_pole_team']})")
            print(f"  {hit} | driver rho={result['driver_spearman']} (n={result['driver_n']}) "
                  f"| team rho={result['team_spearman']} (n={result['team_n']})")
        else:
            print("  skipped (no hotlap data this weekend, or grid wasn't from qualifying)")

    valid = [v for v in cache.values() if v is not None]
    print()
    print(f"=== {len(valid)} races evaluated ===")
    if not valid:
        return
    pole_team_rate = sum(1 for v in valid if v["pole_team_hit"]) / len(valid)
    pole_driver_rate = sum(1 for v in valid if v["pole_driver_hit"]) / len(valid)
    team_rhos = [v["team_spearman"] for v in valid if v["team_spearman"] is not None]
    driver_rhos = [v["driver_spearman"] for v in valid if v["driver_spearman"] is not None]
    print(f"pole team hit rate:   {pole_team_rate:.0%}  ({sum(1 for v in valid if v['pole_team_hit'])}/{len(valid)})")
    print(f"pole driver hit rate: {pole_driver_rate:.0%}  ({sum(1 for v in valid if v['pole_driver_hit'])}/{len(valid)})")
    print(f"avg team rank rho:    {statistics.mean(team_rhos):.3f}" if team_rhos else "avg team rank rho:    n/a")
    print(f"avg driver rank rho:  {statistics.mean(driver_rhos):.3f}" if driver_rhos else "avg driver rank rho:  n/a")


if __name__ == "__main__":
    main()
