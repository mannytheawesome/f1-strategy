"""
Spa (Belgian GP) weekend monitor — 2026-07-17 to 2026-07-19.
Standard weekend: FP1/FP2/FP3 -> Quali -> Race.

Sessions:
  FP1:   11327  Fri 11:30 UTC
  FP2:   11328  Fri 15:00 UTC
  FP3:   11329  Sat 10:30 UTC
  Quali: 11330  Sat 14:00 UTC
  Race:  11334  Sun 13:00 UTC

Total laps: 44 (Spa — longest lap of the year, ~1:44 target)
Weather risk high: Ardennes rain can flip any session.

Run:  nohup python monitor_spa.py >> spa_monitor.log 2>&1 &
"""

import json, os, time
from datetime import datetime, timezone
import requests

from mqtt_monitor import MQTTSessionMonitor

BASE = "https://f1-strategy-production.up.railway.app"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG  = os.path.join(HERE, "spa_monitor.log")
REC  = os.path.join(HERE, "recordings")

SESSIONS = [
    # (label, session_key, start_utc, end_utc, total_laps)
    ("FP1",   11327, "2026-07-17T11:25:00", "2026-07-17T12:45:00", 0),
    ("FP2",   11328, "2026-07-17T14:55:00", "2026-07-17T16:15:00", 0),
    ("FP3",   11329, "2026-07-18T10:25:00", "2026-07-18T11:45:00", 0),
    ("QUALI", 11330, "2026-07-18T13:55:00", "2026-07-18T15:30:00", 0),
    ("RACE",  11334, "2026-07-19T12:55:00", "2026-07-19T16:00:00", 44),
]

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def save_analysis(label: str, key: int, total_laps: int, rec_dir: str):
    log(f"=== {label} over — collecting analysis ===")

    if label in ("FP1", "FP2", "FP3", "SQ"):
        url = f"{BASE}/api/fp_analysis?session_key={key}"
    elif label == "QUALI":
        url = f"{BASE}/api/quali_analysis?session_key={key}"
    elif label in ("SPRINT", "RACE"):
        url = f"{BASE}/api/predict?session_key={key}"
    else:
        url = f"{BASE}/api/live?session_key={key}"

    try:
        r = requests.get(url, timeout=120)
        if r.status_code == 200:
            data = r.json()
            with open(os.path.join(rec_dir, "analysis_final.json"), "w") as f:
                json.dump(data, f, indent=1)
            log(f"{label}: analysis saved")

            if label in ("FP1", "FP2", "FP3", "SQ"):
                cfs = data.get("compound_field_summary", {})
                for c, v in cfs.items():
                    log(f"  {c}: race_pace={v.get('median_race_pace')} deg={v.get('median_deg_rate')}")
                w = data.get("weather", {})
                if w:
                    log(f"  weather: track={w.get('track_temp_avg')}°C air={w.get('air_temp_avg')}°C rain={w.get('rainfall')}")

            if label in ("SPRINT", "RACE"):
                forecasts = data.get("forecasts", [])[:5]
                for f in forecasts:
                    log(f"  P{f.get('predicted_position')} {f.get('acronym')} win={f.get('win_probability', 0):.0%}")
                log(f"  SC source: {data.get('sc_source')} | pit_loss: {data.get('pit_loss_used')}s")
        else:
            log(f"⚠️  {label}: HTTP {r.status_code}")
    except Exception as e:
        log(f"⚠️  {label}: failed: {str(e)[:80]}")

    # Pre-race strategy after FP1
    if label == "FP1":
        try:
            r = requests.get(f"{BASE}/api/pre_race_strategy?session_key={key}&total_laps=44", timeout=60)
            if r.status_code == 200:
                strats = r.json().get("strategies", [])[:3]
                log("  Pre-race strategy candidates (from FP1 data):")
                for s in strats:
                    log(f"    {'-'.join(s['compound_sequence'])} stops={s['stops']} laps={s['stint_lengths']}")
                with open(os.path.join(rec_dir, "pre_race_strategy.json"), "w") as f:
                    json.dump(r.json(), f, indent=1)
        except Exception as e:
            log(f"⚠️  pre_race_strategy failed: {str(e)[:80]}")

    # Tyre inventory after FP/SQ
    if label in ("FP1", "FP2", "FP3", "SQ", "QUALI"):
        try:
            r = requests.get(f"{BASE}/api/tyre_inventory?session_key={key}", timeout=60)
            if r.status_code == 200:
                with open(os.path.join(rec_dir, "tyre_inventory_final.json"), "w") as f:
                    json.dump(r.json(), f, indent=1)
                log(f"{label}: tyre inventory saved")
        except Exception as e:
            log(f"⚠️  tyre inventory failed: {str(e)[:80]}")


def monitor_session(label: str, key: int, start: datetime, end: datetime, total_laps: int):
    rec_dir = os.path.join(REC, f"{label}_{key}")
    os.makedirs(rec_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    if now < start:
        log(f"{label}: waiting {(start - now).total_seconds()/60:.0f} min until session start")
        # Chunked wait that re-checks the wall clock: a single long time.sleep
        # does not advance while the Mac is asleep, which made the monitor
        # oversleep entire sessions. Worst-case wake-up drift is now ~60s.
        while True:
            now = datetime.now(timezone.utc)
            if now >= start:
                break
            time.sleep(min(60, (start - now).total_seconds()))

    log(f"=== {label} (session {key}) monitoring started (MQTT) ===")
    monitor = MQTTSessionMonitor(key, rec_dir, log_fn=log)
    monitor.run_until(end)
    log(f"{label}: MQTT stream ended, {monitor.message_count} total messages received")

    save_analysis(label, key, total_laps, rec_dir)


def main():
    log("=" * 56)
    log("Spa (Belgian GP) weekend monitor armed")
    log("FP1 → FP2 → FP3 → Quali → Race")
    log(f"Production: {BASE}")
    log("=" * 56)
    for label, key, start, end, total_laps in SESSIONS:
        monitor_session(label, key, utc(start), utc(end), total_laps)
    log("All Spa sessions monitored — done")


if __name__ == "__main__":
    main()
