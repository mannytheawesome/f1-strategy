"""
Barcelona FP1/FP2 live monitor — 2026-06-12.

For each session:
  - Waits for the session window
  - Polls the PRODUCTION app every 30s (exercises the deployed stack)
  - Records full /api/live snapshots to recordings/<session>/ every poll
  - Logs anomalies (no data, stalled laps, server errors)
  - After the session: saves /api/fp_analysis and logs a deg-rate summary

Run detached:  nohup python monitor_barcelona.py > /dev/null 2>&1 &
Everything is written to barcelona_monitor.log + recordings/.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

BASE = "https://f1-strategy-production.up.railway.app"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "barcelona_monitor.log")
REC = os.path.join(HERE, "recordings")

SESSIONS = [
    # (label, session_key, start_utc, end_utc with buffer)
    ("FP1", 11300, "2026-06-12T11:25:00", "2026-06-12T12:45:00"),
    ("FP2", 11301, "2026-06-12T14:55:00", "2026-06-12T16:15:00"),
]

POLL_S = 30


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def check_anomalies(data: dict, label: str, last_state: dict) -> dict:
    """Returns updated last_state; logs anything suspicious."""
    drivers = data.get("drivers", [])
    if not drivers:
        log(f"⚠️  {label}: no drivers in response")
        return last_state

    mode = data.get("session_mode")
    if mode != "FP":
        log(f"⚠️  {label}: session_mode={mode} (expected FP)")

    laps = [d.get("current_lap") or 0 for d in drivers]
    max_lap = max(laps) if laps else 0
    active = sum(1 for d in drivers if (d.get("current_lap") or 0) > 0)

    # Progress heartbeat + stall detection
    if max_lap != last_state.get("max_lap"):
        log(f"{label}: lap {max_lap}, {active}/{len(drivers)} drivers active")
        last_state["max_lap"] = max_lap
        last_state["stalled_polls"] = 0
    else:
        last_state["stalled_polls"] = last_state.get("stalled_polls", 0) + 1
        # 10 polls = 5 min without any new lap mid-session → possible red flag/data stall
        if last_state["stalled_polls"] == 10 and active > 0:
            log(f"ℹ️  {label}: no lap progress for 5 min (red flag or data stall?)")

    # Spot checks on data quality
    for d in drivers[:5]:
        if d.get("compound") not in (None, "SOFT", "MEDIUM", "HARD",
                                     "INTERMEDIATE", "WET", "UNKNOWN", "TEST_UNKNOWN"):
            log(f"⚠️  {label}: {d.get('acronym')} unexpected compound {d.get('compound')}")

    return last_state


def monitor_session(label: str, key: int, start: datetime, end: datetime):
    rec_dir = os.path.join(REC, f"{label}_{key}")
    os.makedirs(rec_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    if now < start:
        wait = (start - now).total_seconds()
        log(f"{label}: waiting {wait/60:.0f} min until session window")
        time.sleep(wait)

    log(f"=== {label} (session {key}) monitoring started ===")
    errors = 0
    last_state: dict = {}

    while datetime.now(timezone.utc) < end:
        try:
            r = requests.get(f"{BASE}/api/live?session_key={key}", timeout=30)
            if r.status_code == 200:
                data = r.json()
                errors = 0
                ts = datetime.now(timezone.utc).strftime("%H%M%S")
                with open(os.path.join(rec_dir, f"live_{ts}.json"), "w") as f:
                    json.dump(data, f)
                last_state = check_anomalies(data, label, last_state)
            else:
                errors += 1
                log(f"⚠️  {label}: HTTP {r.status_code} (consecutive: {errors})")
        except Exception as e:
            errors += 1
            log(f"⚠️  {label}: request failed: {str(e)[:80]} (consecutive: {errors})")

        if errors >= 6:
            log(f"⛔ {label}: 6 consecutive failures — production may be down")
            errors = 0

        time.sleep(POLL_S)

    # Post-session analysis snapshot
    log(f"=== {label} over — collecting analysis ===")
    try:
        r = requests.get(f"{BASE}/api/fp_analysis?session_key={key}", timeout=120)
        if r.status_code == 200:
            analysis = r.json()
            with open(os.path.join(rec_dir, "fp_analysis_final.json"), "w") as f:
                json.dump(analysis, f, indent=1)
            log(f"{label}: analysis saved — {len(analysis.get('drivers', []))} drivers")
            for drv in analysis.get("drivers", [])[:5]:
                best = drv.get("best_lap_overall")
                degs = {k: v for k, v in (drv.get("deg_rates") or {}).items()}
                log(f"  {drv['acronym']:<4} best={best} deg={degs}")
        else:
            log(f"⚠️  {label}: fp_analysis returned HTTP {r.status_code}")
    except Exception as e:
        log(f"⚠️  {label}: fp_analysis failed: {str(e)[:80]}")

    try:
        r = requests.get(f"{BASE}/api/tyre_inventory?session_key={key}", timeout=120)
        if r.status_code == 200:
            with open(os.path.join(rec_dir, "tyre_inventory_final.json"), "w") as f:
                json.dump(r.json(), f, indent=1)
            log(f"{label}: tyre inventory saved")
    except Exception as e:
        log(f"⚠️  {label}: tyre inventory failed: {str(e)[:80]}")


def main():
    log("=" * 56)
    log("Barcelona FP1/FP2 monitor armed")
    log(f"Production: {BASE}")
    log("=" * 56)
    for label, key, start, end in SESSIONS:
        monitor_session(label, key, utc(start), utc(end))
    log("All sessions monitored — done")


if __name__ == "__main__":
    main()
