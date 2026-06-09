"""
Monaco FP1 background monitor — session 11292
Starts at 11:30 UTC, runs for 60 minutes.
Polls every 30s, logs anomalies to fp1_anomalies.log
"""

import time
import requests
import json
from datetime import datetime, timezone

SESSION_KEY = 11292
API_BASE = "http://localhost:8000"
LOG_FILE = "/Users/mannytheawsome/Documents/f1-strategy/fp1_anomalies.log"
POLL_INTERVAL = 30  # seconds

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def check_anomalies(data: dict) -> list[str]:
    anomalies = []
    drivers = data.get("drivers", [])
    if not drivers:
        return ["No driver data returned"]

    laps = [d["current_lap"] for d in drivers if d["current_lap"] > 0]
    if not laps:
        return []  # session not started yet

    max_lap = max(laps)
    log(f"Lap {max_lap} | {len(drivers)} drivers | mode={data.get('session_mode')}")

    for d in drivers:
        name = d["acronym"]
        compound = d.get("compound") or "?"
        age = d.get("tyre_age") or 0
        last_lap = d.get("last_lap_time")
        deg = None

        # Flag 1: unusually long last lap (safety car / incident)
        if last_lap and last_lap > 120:
            anomalies.append(f"⚠️  {name} very slow lap: {last_lap:.1f}s (possible SC/incident)")

        # Flag 2: tyre age > max expected life
        max_life = {"SOFT": 28, "MEDIUM": 42, "HARD": 58}.get(compound, 40)
        if age > max_life:
            anomalies.append(f"⚠️  {name} on {compound} {age}L (past cliff at {max_life}L)")

        # Flag 3: driver on track with 0 laps while others have done laps (possible issue)
        if d["current_lap"] == 0 and max_lap > 3 and not d["retired"]:
            anomalies.append(f"ℹ️  {name} has 0 laps while session is at lap {max_lap}")

    # Flag 4: sudden drop in driver count
    active = [d for d in drivers if not d["retired"] and d["current_lap"] > 0]
    if len(active) < 15 and max_lap < 5:
        anomalies.append(f"⚠️  Only {len(active)} drivers active in early laps (red flag?)")

    return anomalies


def wait_for_session_start():
    log(f"Waiting for Monaco FP1 to start (11:30 UTC)...")
    while True:
        now = datetime.now(timezone.utc)
        if now.hour >= 11 and now.minute >= 30:
            break
        remaining = (11*60 + 30) - (now.hour*60 + now.minute)
        log(f"  {remaining} minutes to go...")
        time.sleep(60)
    log("Session should be starting — beginning monitoring")


def monitor():
    log("=" * 50)
    log("Monaco FP1 Monitor started")
    log(f"Session key: {SESSION_KEY}")
    log("=" * 50)

    wait_for_session_start()

    session_end_hour = 12
    session_end_min  = 35  # 5 min buffer after 12:30

    consecutive_errors = 0

    while True:
        now = datetime.now(timezone.utc)
        # Stop after session ends
        if now.hour > session_end_hour or (now.hour == session_end_hour and now.minute > session_end_min):
            log("Session over — monitor stopping")
            break

        try:
            r = requests.get(f"{API_BASE}/api/live?session_key={SESSION_KEY}", timeout=15)
            if r.status_code == 200:
                data = r.json()
                consecutive_errors = 0
                anomalies = check_anomalies(data)
                for a in anomalies:
                    log(a)
            else:
                consecutive_errors += 1
                log(f"API error {r.status_code} (attempt {consecutive_errors})")
        except Exception as e:
            consecutive_errors += 1
            log(f"Request failed: {e} (attempt {consecutive_errors})")

        if consecutive_errors >= 5:
            log("⛔ 5 consecutive errors — possible server issue")
            consecutive_errors = 0  # reset and keep trying

        time.sleep(POLL_INTERVAL)

    # Final summary
    log("=" * 50)
    log("FINAL SUMMARY")
    try:
        r = requests.get(f"{API_BASE}/api/fp_analysis?session_key={SESSION_KEY}", timeout=30)
        if r.status_code == 200:
            data = r.json()
            log(f"Drivers analysed: {len(data['drivers'])}")
            for drv in data["drivers"][:5]:
                best = drv.get("best_lap_overall")
                deg = drv.get("deg_rates", {})
                log(f"  {drv['acronym']:<5} best={best and round(best,3)} deg={deg}")
    except Exception as e:
        log(f"FP analysis failed: {e}")
    log("=" * 50)


if __name__ == "__main__":
    monitor()
