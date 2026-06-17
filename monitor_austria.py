"""
Austria FP1/FP2/FP3/Quali/Race live monitor — 2026-06-26 to 2026-06-28.
Red Bull Ring: short lap (~71 laps), high rear tyre deg, good overtaking,
above-average SC probability. Normal circuit (tpw=0.6).

Sessions:
  FP1:   11308  Fri 11:30 UTC
  FP2:   11309  Fri 15:00 UTC
  FP3:   11310  Sat 10:30 UTC
  Quali: 11311  Sat 14:00 UTC
  Race:  11315  Sun 13:00 UTC

Run detached:  nohup python monitor_austria.py > /dev/null 2>&1 &
All output goes to austria_monitor.log + recordings/.
"""

import json, os, time
from datetime import datetime, timezone
import requests

BASE = "https://f1-strategy-production.up.railway.app"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG  = os.path.join(HERE, "austria_monitor.log")
REC  = os.path.join(HERE, "recordings")

SESSIONS = [
    # (label, session_key, start_utc, end_utc with buffer)
    # OpenF1 free tier blocks data until ~30 min after session end.
    # With paid OPENF1_API_KEY, end_utc can be the actual end time.
    ("FP1",   11308, "2026-06-26T11:25:00", "2026-06-26T12:45:00"),
    ("FP2",   11309, "2026-06-26T14:55:00", "2026-06-26T16:10:00"),
    ("FP3",   11310, "2026-06-27T10:25:00", "2026-06-27T11:45:00"),
    ("QUALI", 11311, "2026-06-27T13:55:00", "2026-06-27T16:00:00"),
    ("RACE",  11315, "2026-06-28T12:55:00", "2026-06-28T16:00:00"),
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
    drivers = data.get("drivers", [])
    if not drivers:
        log(f"⚠️  {label}: no drivers in response")
        return last_state

    mode = data.get("session_mode")
    expected = "FP" if label.startswith("FP") else ("QUALI" if label == "QUALI" else "RACE")
    if mode != expected:
        log(f"⚠️  {label}: session_mode={mode} (expected {expected})")

    laps = [d.get("current_lap") or 0 for d in drivers]
    max_lap = max(laps) if laps else 0
    active  = sum(1 for d in drivers if (d.get("current_lap") or 0) > 0)

    if max_lap != last_state.get("max_lap"):
        log(f"{label}: lap {max_lap}, {active}/{len(drivers)} drivers active")
        last_state["max_lap"] = max_lap
        last_state["stalled_polls"] = 0
    else:
        last_state["stalled_polls"] = last_state.get("stalled_polls", 0) + 1
        if last_state["stalled_polls"] == 10 and active > 0:
            log(f"ℹ️  {label}: no lap progress for 5 min")

    for d in drivers[:5]:
        if d.get("compound") not in (None, "SOFT", "MEDIUM", "HARD",
                                     "INTERMEDIATE", "WET", "UNKNOWN", "TEST_UNKNOWN"):
            log(f"⚠️  {label}: {d.get('acronym')} unexpected compound {d.get('compound')}")
    return last_state


def save_analysis(label: str, key: int, rec_dir: str):
    """Collect post-session analysis snapshots."""
    log(f"=== {label} over — collecting analysis ===")

    if label.startswith("FP"):
        endpoint = f"{BASE}/api/fp_analysis?session_key={key}"
    elif label == "QUALI":
        endpoint = f"{BASE}/api/quali_analysis?session_key={key}"
    else:
        endpoint = f"{BASE}/api/live?session_key={key}"

    try:
        r = requests.get(endpoint, timeout=120)
        if r.status_code == 200:
            analysis = r.json()
            fname = "analysis_final.json"
            with open(os.path.join(rec_dir, fname), "w") as f:
                json.dump(analysis, f, indent=1)
            log(f"{label}: analysis saved")

            if label.startswith("FP"):
                for drv in analysis.get("drivers", [])[:5]:
                    best = drv.get("best_lap_overall")
                    degs = drv.get("deg_rates", {})
                    log(f"  {drv['acronym']:<4} best={best} deg={degs}")
        else:
            log(f"⚠️  {label}: analysis HTTP {r.status_code}")
    except Exception as e:
        log(f"⚠️  {label}: analysis failed: {str(e)[:80]}")

    if label.startswith("FP") or label == "QUALI":
        try:
            r = requests.get(f"{BASE}/api/tyre_inventory?session_key={key}", timeout=60)
            if r.status_code == 200:
                with open(os.path.join(rec_dir, "tyre_inventory_final.json"), "w") as f:
                    json.dump(r.json(), f, indent=1)
                log(f"{label}: tyre inventory saved")
        except Exception as e:
            log(f"⚠️  {label}: tyre inventory failed: {str(e)[:80]}")


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

    save_analysis(label, key, rec_dir)


def main():
    log("=" * 56)
    log("Austria FP1/FP2/FP3/Quali/Race monitor armed")
    log(f"Production: {BASE}")
    log("=" * 56)
    for label, key, start, end in SESSIONS:
        monitor_session(label, key, utc(start), utc(end))
    log("All Austria sessions monitored — done")


if __name__ == "__main__":
    main()
