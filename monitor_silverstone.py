"""
Silverstone Sprint Weekend monitor — 2026-07-03 to 2026-07-05.
Sprint weekend: only FP1 before Sprint Qualifying → different tyre strategy logic.

Sessions:
  FP1:              11316  Fri 11:30 UTC  (already started!)
  Sprint Qualifying:11317  Fri 15:30 UTC
  Sprint:           11321  Sat 11:00 UTC
  Qualifying:       11322  Sat 15:00 UTC
  Race:             11326  Sun 14:00 UTC

Total laps: 52 (Silverstone — long lap, ~1:27 target)
SC probability: higher than average (Silverstone = 0.0080/lap)

Run:  nohup python monitor_silverstone.py >> silverstone_monitor.log 2>&1 &
"""

import json, os, time
from datetime import datetime, timezone
import requests

from mqtt_monitor import MQTTSessionMonitor

BASE = "https://f1-strategy-production.up.railway.app"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG  = os.path.join(HERE, "silverstone_monitor.log")
REC  = os.path.join(HERE, "recordings")

SESSIONS = [
    # (label, session_key, start_utc, end_utc, total_laps)
    ("FP1",    11316, "2026-07-03T11:25:00", "2026-07-03T12:45:00", 0),
    ("SQ",     11317, "2026-07-03T15:25:00", "2026-07-03T16:45:00", 0),
    ("SPRINT", 11321, "2026-07-04T10:55:00", "2026-07-04T12:00:00", 17),
    ("QUALI",  11322, "2026-07-04T14:55:00", "2026-07-04T16:30:00", 0),
    ("RACE",   11326, "2026-07-05T13:55:00", "2026-07-05T17:00:00", 52),
]

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def save_analysis(label: str, key: int, total_laps: int, rec_dir: str):
    log(f"=== {label} over — collecting analysis ===")

    if label in ("FP1", "SQ"):
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

            if label in ("FP1", "SQ"):
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
            r = requests.get(f"{BASE}/api/pre_race_strategy?session_key={key}&total_laps=52", timeout=60)
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
    if label in ("FP1", "SQ", "QUALI"):
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
        wait = (start - now).total_seconds()
        log(f"{label}: waiting {wait/60:.0f} min until session start")
        time.sleep(wait)

    log(f"=== {label} (session {key}) monitoring started (MQTT) ===")
    monitor = MQTTSessionMonitor(key, rec_dir, log_fn=log)
    monitor.run_until(end)
    log(f"{label}: MQTT stream ended, {monitor.message_count} total messages received")

    save_analysis(label, key, total_laps, rec_dir)


def main():
    log("=" * 56)
    log("Silverstone SPRINT WEEKEND monitor armed")
    log("FP1 → Sprint Quali → Sprint → Quali → Race")
    log(f"Production: {BASE}")
    log("=" * 56)
    for label, key, start, end, total_laps in SESSIONS:
        monitor_session(label, key, utc(start), utc(end), total_laps)
    log("All Silverstone sessions monitored — done")


if __name__ == "__main__":
    main()
