"""
One-off measurement: how much do real SC/VSC rate and DNF rate actually
elevate in wet races vs dry ones? Needed before wiring a weather forecast
into run_monte_carlo's SC/DNF modelling -- this project's standing rule is
to measure a scaling constant from real data (see SC_OPENING_MULT, the
DNF_RATE fix, etc.) rather than guess one.

"Wet" = any weather sample during the race session has rainfall=True.
Reuses backtest_full.py's resumable disk cache (same fetch()/enumerate_
weekends()) so this doesn't re-download anything already collected.

Run: python3 measure_wet_weather_rates.py
"""
import sys
sys.path.insert(0, ".")
import ssl
import certifi
import urllib.request

# This machine's python.org build has no system CA bundle wired into the
# default SSL context (a local dev-environment gap, not a code issue) --
# backtest_full.fetch uses raw urllib, which fails with
# CERTIFICATE_VERIFY_FAILED on any live (non-cached) call without this.
# Supplies the same CA bundle `requests` already uses elsewhere in this
# project (certifi) rather than disabling verification.
_ssl_context = ssl.create_default_context(cafile=certifi.where())
urllib.request.urlopen = (lambda _orig: lambda *a, **k: _orig(*a, **{**k, "context": _ssl_context}))(urllib.request.urlopen)

import statistics
from backtest_full import fetch, enumerate_weekends
from engine.predictor import detect_sc

weekends = enumerate_weekends()
print(f"{len(weekends)} weekends found")

wet_races = []
dry_races = []

for w in weekends:
    race_key = w["race_key"]
    try:
        weather = fetch("weather", session_key=race_key)
        results = fetch("session_result", session_key=race_key)
        laps = fetch("laps", session_key=race_key)
    except Exception as e:
        print(f"  {w['circuit']} {w['year']}: skipped ({e})")
        continue
    if not weather or not results or not laps:
        continue

    is_wet = any(s.get("rainfall") for s in weather)
    n_entries = len(results)
    if n_entries == 0:
        continue
    n_dnf = sum(1 for r in results if r.get("dnf") or r.get("dsq"))
    dnf_rate = n_dnf / n_entries

    try:
        sc_events = detect_sc(laps)
        n_sc = len(sc_events)
    except Exception:
        n_sc = None

    row = {"circuit": w["circuit"], "year": w["year"], "dnf_rate": dnf_rate,
           "n_sc": n_sc, "n_entries": n_entries}
    (wet_races if is_wet else dry_races).append(row)
    tag = "WET" if is_wet else "dry"
    print(f"  {tag}  {w['circuit']:<20} {w['year']}  dnf_rate={dnf_rate:.3f}  sc_events={n_sc}")

print()
print(f"=== {len(wet_races)} wet races, {len(dry_races)} dry races ===")


def summarize(label, rows):
    if not rows:
        print(f"{label}: no races")
        return
    dnf = statistics.mean(r["dnf_rate"] for r in rows)
    sc_vals = [r["n_sc"] for r in rows if r["n_sc"] is not None]
    sc = statistics.mean(sc_vals) if sc_vals else None
    print(f"{label}: n={len(rows)}  mean DNF rate={dnf:.3f}  mean SC/VSC events per race={sc}")


summarize("DRY", dry_races)
summarize("WET", wet_races)

if dry_races and wet_races:
    dry_dnf = statistics.mean(r["dnf_rate"] for r in dry_races)
    wet_dnf = statistics.mean(r["dnf_rate"] for r in wet_races)
    dry_sc = statistics.mean(r["n_sc"] for r in dry_races if r["n_sc"] is not None)
    wet_sc = statistics.mean(r["n_sc"] for r in wet_races if r["n_sc"] is not None)
    print()
    print(f"DNF rate multiplier (wet/dry): {wet_dnf / dry_dnf:.2f}x")
    print(f"SC/VSC event multiplier (wet/dry): {wet_sc / dry_sc:.2f}x")
