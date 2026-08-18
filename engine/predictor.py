"""
Race Predictor — lap-by-lap simulation engine.

Architecture:
  1. DegCurve / build_deg_curves — combine FP1/2/3 into reliable compound curves
  2. DriverPace / build_pace_model — per-driver age-corrected pace delta
  3. optimize_strategy — DP over pit_lap × compound to minimise race time
  4. simulate_race — run all drivers simultaneously, produce ranked forecasts
  5. calc_undercut — quantify time delta of pitting now vs staying one more lap
  6. detect_sc / sc_probability — safety car detection and forward probability

Outputs (via /api/predict):
  - Per-driver: predicted finish, optimal remaining strategy, undercut analysis
  - Race-wide: SC events, SC probability remaining, deg curves used
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import itertools
import statistics

# ── Constants ────────────────────────────────────────────────────────────────

PIT_LOSS        = 22.0   # seconds lost per pit stop (pit lane time loss)
STOP_RISK       = 6.0    # extra penalty per stop: traffic, out-lap, execution risk
SC_LAP_MULT     = 1.35   # median lap time > 35% above session median → SC
MIN_STINT       = 8      # minimum viable stint length
SOFT_SPLASH_MAX = 15     # Soft allowed as final compound only if ≤ this many laps
# DNF_RATE_DEFAULT (below, next to its SC counterparts) replaced the old flat
# 0.04 here — that understated measured risk by >3x.

# Fuel correction: cars improve ~0.035s/lap as fuel burns off (100kg load, ~0.3kg/km).
# Applied to RACE laps before deg regression so the slope reflects tyre wear, not
# fuel-lightening — without this, M/H deg rates come out near-zero on long stints.
FUEL_RATE = 0.035        # s/lap improvement from fuel burn-off

# RACE data dominates when available — fuel burn-off and track evolution make
# FP deg rates 2-3x higher than what actually materialises in the race
FP_WEIGHTS = {"FP1": 0.3, "FP2": 1.0, "FP3": 0.9, "RACE": 3.0}

# Degradation is fitted per stint. A stint needs this many clean laps to give a
# trustworthy slope, and laps slower than this ratio of the stint median are
# treated as traffic/mistakes rather than wear.
# Practice stints interleave push laps with much slower cool-down laps, so a
# lap only counts as representative running if it is within this ratio of the
# stint's own best lap. The strict pass is what a genuine long run looks like;
# the loose pass is a fallback for compounds with no long run at all.
DEG_LONGRUN = (1.02, 8)    # (max ratio to stint best, min clean laps)
DEG_FALLBACK = (1.05, 5)

# Wear relative to MEDIUM, measured from races where both compounds had a
# genuine long run (SOFT 1.78 direct, 1.75 from clean-curve medians — two
# independent estimates agreeing). Used to price a compound nobody ran long.
DEG_RATIO = {"SOFT": 1.75, "MEDIUM": 1.0, "HARD": 0.6}
# Floor for a compound with NO long run at all. Deliberately the p75 of measured
# rates, not the median: a compound nobody could run long is self-selecting
# evidence that it wears hard here, so assuming median wear systematically
# flatters it. Using the median had the optimiser recommending SOFT in 86% of
# races against the 27% teams actually ran it in.
DEG_UNMEASURED = {"SOFT": 0.24, "MEDIUM": 0.13, "HARD": 0.07}
# Last resort when NOTHING was measured at an event.
DEG_PRIOR = {"SOFT": 0.12, "MEDIUM": 0.07, "HARD": 0.04}

COMPOUND_DELTA = {"SOFT": -0.6, "MEDIUM": 0.0, "HARD": +0.4}   # vs fresh Medium
DRY = ["SOFT", "MEDIUM", "HARD"]

from engine.circuits import STREET_CIRCUITS
# Share of the green-flag pit loss still paid when stopping under a
# neutralisation (measured vs rivals who stayed out, 2023-2026).
SC_PIT_FACTOR  = 0.78   # full safety car  (n=177)
VSC_PIT_FACTOR = 0.69   # virtual safety car (n=71)

SC_RATE_DEFAULT = 0.0067
SC_RATE_STREET  = 0.0120

# Per-circuit SC rates (events per lap) from 2018-2025 historical data.
# Circuits not listed fall back to SC_RATE_DEFAULT or SC_RATE_STREET.
#
# Keys are matched as substrings of OpenF1's circuit_short_name (lowercased) —
# see _circuit_rate below. Four entries never actually matched the real
# values ("red_bull_ring" / "albert_park" / "bahrain" / "Catalunya" vs the
# true "Spielberg" / "Melbourne" / "Sakhir" & "Kuala Lumpur" / "catalunya"),
# so Melbourne, Bahrain and Catalunya silently fell back to SC_RATE_DEFAULT
# for as long as this table has existed. Fixed 2026-08-11; "kuala lumpur" is
# a second key for Bahrain because OpenF1 mislabels some Sakhir sessions that
# way, not a real Malaysia entry.
SC_RATE_CIRCUIT: dict[str, float] = {
    "spielberg":        0.0105,   # Austria — gravel traps, fast lap = frequent SC
    "silverstone":      0.0080,   # Britain — high speed, above-average
    "spa":              0.0090,   # Belgium — long lap, Eau Rouge incidents
    "monza":            0.0080,   # Italy — slipstream battles, high speed
    "suzuka":           0.0075,   # Japan — one-lap incidents, tight first sector
    "interlagos":       0.0090,   # Brazil — unpredictable weather, Senna S
    "melbourne":        0.0085,   # Australia — street-ish, first race incidents
    "sakhir":           0.0060,   # Bahrain — clean, low SC rate
    "kuala lumpur":     0.0060,   # Bahrain, mislabeled by OpenF1 on some sessions
    "catalunya":        0.0055,   # Spain — low SC rate historically
    "hungaroring":      0.0060,   # Hungary — low SC rate, easy to defend
    "zandvoort":        0.0085,   # Netherlands — barriers close, VSC common
}

# SC/VSC deployments cluster hard at race starts (Lap-1/Turn-1 incidents,
# multi-car pileups) rather than spreading evenly across the race. Measured by
# running detect_sc() on the FULL race laps (not just laps-to-now) for all 81
# cached races 2023-2026: events in the opening 5% of race distance land at
# 4.44 events/race/unit-distance vs 0.66 for the rest of the race — a ~5.2x
# spike. 18 events fell in that opening window against ~3.5 expected under a
# flat rate, too large a gap to be sampling noise. The other five buckets
# checked across the remaining 95% of the race (5-15%, 15-30%, 30-50%, 50-70%,
# 70-85%, 85-100%) were flat/noisy with no trend (0.56-0.74, ~9 events each) —
# finer-grained shaping there would hit the same overfitting wall the
# per-circuit DNF table did on this sample size. Two buckets only.
#
# SC_RATE_CIRCUIT/STREET/DEFAULT above still set each circuit's overall
# expected SC count per race; these two constants only reshape WHEN within the
# race that risk lands. SC_REST_MULT is derived, not independently fit, so the
# reshape provably cannot change the total expected event count per race (it
# integrates to 1 over the full race) — it can't silently invalidate the
# already-tuned per-circuit rates, only correct their timing.
SC_OPENING_WINDOW_FRAC = 0.05    # first ~2-4 laps depending on race distance
SC_OPENING_MULT        = 5.2     # hazard multiplier inside the opening window
SC_REST_MULT = (1 - SC_OPENING_WINDOW_FRAC * SC_OPENING_MULT) / (1 - SC_OPENING_WINDOW_FRAC)


def _sc_p_no(rate: float, current_lap: int, total_laps: int,
             window_end: Optional[int] = None) -> float:
    """P(no SC/VSC) over laps (current_lap, window_end], using the measured
    opening-lap hazard spike instead of a flat per-lap rate applied uniformly.

    total_laps is the REAL race distance — it fixes where the opening-window
    boundary falls and must never be a truncated lookahead length. window_end
    (default total_laps) lets a caller ask about a shorter window ("SC risk in
    the next 12 laps") while still shaping hazard off the real race distance,
    e.g. laps 2-3 of a 70-lap race stay inside the opening spike even when the
    caller only wants a 12-lap-deep answer.
    """
    if total_laps <= 0:
        return 1.0
    end = total_laps if window_end is None else min(window_end, total_laps)
    opening_end = max(1, round(total_laps * SC_OPENING_WINDOW_FRAC))
    p_no = 1.0
    for lap in range(max(1, current_lap + 1), end + 1):
        mult = SC_OPENING_MULT if lap <= opening_end else SC_REST_MULT
        p_no *= 1 - min(0.99, rate * mult)
    return p_no

# DNF rate (retired or disqualified, per driver-start), measured from OpenF1
# session_result across the 81-race 2023-2026 backtest cache — see CLAUDE.md.
# The old flat 0.04 used everywhere understated true risk by >3x. A per-circuit
# table (Melbourne 0.235 down to Monza 0.050) was tried and measurably WORSENED
# win-probability Brier score (0.0148 -> 0.0153) despite improving nothing
# else — each circuit only has 3-4 races (60-82 driver-starts) in the cache,
# too thin to estimate a real per-circuit rate from; the table was mostly
# fitting noise. Flat field-wide default only.
DNF_RATE_DEFAULT = 0.129


def _circuit_rate(table: dict[str, float], default: float, circuit: str) -> float:
    """Substring-match circuit against a per-circuit rate table, case-
    insensitively, falling back to `default` if nothing matches."""
    cl = (circuit or "").lower()
    return next((v for k, v in table.items() if k in cl or cl in k), default)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class DegCurve:
    compound:    str
    deg_rate:    float    # s per lap of tyre age
    baseline:    float    # predicted lap time at tyre age 0
    data_points: int
    confidence:  str      # HIGH / MEDIUM / LOW
    sessions:    list[str]

    def lap_time(self, age: int) -> float:
        return self.baseline + self.deg_rate * age


@dataclass
class DriverPace:
    driver_number: int
    acronym:       str
    pace_median:   float   # median age-corrected lap time
    pace_std:      float
    pace_delta:    float   # vs field median (negative = faster than average)
    laps_counted:  int


@dataclass
class SCEvent:
    start_lap: int
    end_lap:   int
    type:      str   # SC | VSC


@dataclass
class PitPlan:
    lap:      int
    compound: str
    tyre_age: int = 0   # age of the set being fitted (0 = new, >0 = used/scrubbed)


@dataclass
class DriverStrategy:
    driver_number:       int
    acronym:             str
    current_lap:         int
    current_compound:    str
    current_age:         int
    pits_remaining:      list[PitPlan]
    total_time_from_now: float
    laps_until_must_pit: Optional[int]
    confidence:          str


@dataclass
class UndercutResult:
    driver:         str
    target:         str
    gap_to_target:  float
    time_gain:      float    # net seconds gained by pitting now vs waiting
    viable:         bool     # True if driver emerges ahead
    recommendation: str


@dataclass
class DriverForecast:
    driver_number:      int
    acronym:            str
    current_position:   int
    predicted_position: int
    predicted_gap:      float
    confidence:         str
    strategy:           DriverStrategy
    undercut:           Optional[UndercutResult]
    # Monte Carlo outputs (filled by run_monte_carlo)
    win_probability:    float = 0.0
    podium_probability: float = 0.0
    points_probability: float = 0.0
    position_range:     tuple[int, int] = (0, 0)   # P5-P95 of simulated finishes
    mean_finish:        float = 0.0                # expected finishing position


# ── SC detection ─────────────────────────────────────────────────────────────

def detect_sc(laps_raw: list[dict]) -> list[SCEvent]:
    by_lap: dict[int, list[float]] = {}
    for l in laps_raw:
        t = l.get("lap_duration")
        if t and 55 < t < 600:
            by_lap.setdefault(l["lap_number"], []).append(t)
    if not by_lap:
        return []

    all_times = [t for ts in by_lap.values() for t in ts]
    threshold = statistics.median(all_times) * SC_LAP_MULT

    sc_laps = sorted(
        ln for ln, ts in by_lap.items()
        if len(ts) >= 5 and statistics.median(ts) > threshold
    )
    if not sc_laps:
        return []

    # Severity classifies the neutralisation: a full SC drags the field to
    # ~150%+ of green pace, a VSC delta is a milder ~135-145%
    race_median = statistics.median(all_times)

    def classify(start: int, end: int) -> str:
        ev_times = [t for ln in range(start, end + 1) for t in by_lap.get(ln, [])]
        if not ev_times:
            return "SC"
        return "SC" if statistics.median(ev_times) > race_median * 1.5 else "VSC"

    events, start, prev = [], sc_laps[0], sc_laps[0]
    for ln in sc_laps[1:]:
        if ln > prev + 2:
            events.append(SCEvent(start, prev, classify(start, prev)))
            start = ln
        prev = ln
    events.append(SCEvent(start, prev, classify(start, prev)))
    return events


def sc_probability(sc_events: list[SCEvent], current_lap: int,
                   total_laps: int, circuit: str = "",
                   window_laps: Optional[int] = None) -> float:
    """window_laps: look only at the next N laps from current_lap instead of
    all the way to total_laps (e.g. an early-race window), while still shaping
    hazard off the REAL total_laps so the opening-lap spike lands correctly —
    total_laps must stay the genuine race distance, never a truncated one."""
    remaining = max(0, total_laps - current_lap)
    if remaining <= 0:
        return 0.0
    cl = circuit.lower()
    if any(c in cl for c in STREET_CIRCUITS):
        rate = SC_RATE_STREET
    else:
        rate = _circuit_rate(SC_RATE_CIRCUIT, SC_RATE_DEFAULT, circuit)
    window_end = total_laps if window_laps is None else current_lap + window_laps
    p_no = _sc_p_no(rate, current_lap, total_laps, window_end=window_end)
    if sc_events:
        p_no = min(p_no * 1.15, 0.95)
    return round(1 - p_no, 3)


# ── Deg curves from FP data ───────────────────────────────────────────────────

def _stint_deg_samples(laps_raw, stints_raw, weight, session_name,
                       ratio=DEG_LONGRUN[0], min_laps=DEG_LONGRUN[1]):
    """Per-stint degradation slopes, grouped by compound.

    One stint is one car on one fuel programme, so a slope fitted INSIDE it
    measures tyre wear. Pooling every driver's laps together (as this used to)
    mixes low-fuel qualifying simulations on fresh tyres with high-fuel long runs
    on old ones and reads that difference as degradation — which is why practice
    deg saturated the 0.30 s/lap clamp on most weekends.
    """
    by_driver: dict[int, dict[int, float]] = {}
    for lap in laps_raw:
        dur = lap.get("lap_duration")
        if not dur or dur > 200 or dur < 55 or lap.get("is_pit_out_lap"):
            continue
        by_driver.setdefault(lap["driver_number"], {})[lap["lap_number"]] = dur

    out: dict[str, list[tuple]] = {}
    for st in stints_raw:
        c = st.get("compound", "")
        if c not in DRY or st.get("lap_start") is None:
            continue
        laps = by_driver.get(st["driver_number"], {})
        lo, hi = st["lap_start"], (st.get("lap_end") or st["lap_start"])
        # Drop the in-lap: a stint's final lap ends in the pit lane.
        pts = [(ln, laps[ln]) for ln in range(lo, hi) if ln in laps]
        if len(pts) < min_laps:
            continue
        # Keep only representative running: cool-down laps, traffic and mistakes
        # are all one-sided and slow, so measure against the stint's best lap.
        ref = min(d for _, d in pts)
        pts = [(ln, d) for ln, d in pts if d <= ref * ratio]
        if len(pts) < min_laps:
            continue

        age0 = st.get("tyre_age_at_start") or 0
        xs = [float(age0 + ln - lo) for ln, _ in pts]
        # Fuel burn-off makes later laps faster; add it back so the slope is wear
        # only. This applies to practice long runs too, not just the race.
        ys = [d + FUEL_RATE * ln for ln, d in pts]
        n = len(xs)
        mx = sum(xs) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            continue
        my = sum(ys) / n
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
        # Baseline: lap time at age 0 in this stint's own fuel state (raw, so it
        # stays comparable with the compound-offset sanity check further down).
        raw_med = statistics.median(d for _, d in pts)
        base = raw_med - slope * statistics.median(xs)
        out.setdefault(c, []).append((slope, base, weight, n, session_name))
    return out


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Median of values under sample weights — robust to one wild stint in a way
    the old weighted mean was not."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def build_deg_curves(
    fp_data: list[tuple[str, list[dict], list[dict]]]
) -> dict[str, DegCurve]:

    # Strict pass = genuine long runs, the only data wear can be read from.
    strict: dict[str, list[tuple]] = {}
    for name, laps_raw, stints_raw in fp_data:
        w = FP_WEIGHTS.get(name, 0.5)
        for c, rows in _stint_deg_samples(laps_raw, stints_raw, w, name).items():
            strict.setdefault(c, []).extend(rows)

    # Loose pass = whatever running exists (qualifying simulations, short runs).
    # Good enough to place a compound's fresh-lap BASELINE, useless for wear.
    loose: dict[str, list[tuple]] = {}
    for name, laps_raw, stints_raw in fp_data:
        w = FP_WEIGHTS.get(name, 0.5)
        for c, rows in _stint_deg_samples(laps_raw, stints_raw, w, name,
                                          ratio=DEG_FALLBACK[0],
                                          min_laps=DEG_FALLBACK[1]).items():
            loose.setdefault(c, []).extend(rows)

    samples = {c: rows for c, rows in strict.items()}
    for c, rows in loose.items():
        samples.setdefault(c, rows)

    curves: dict[str, DegCurve] = {}
    for c, samps in samples.items():
        tw = sum(s[2] for s in samps)
        if tw == 0:
            continue
        # Median over stints, not a mean: a single traffic-wrecked run should
        # not drag the whole compound's deg rate up.
        deg  = _weighted_median([(s[0], s[2]) for s in samps])
        base = _weighted_median([(s[1], s[2]) for s in samps])
        pts  = sum(s[3] for s in samps)
        conf = "HIGH" if pts >= 20 else "MEDIUM" if pts >= 8 else "LOW"
        curves[c] = DegCurve(c, max(deg, 0.0), base, pts, conf, [s[4] for s in samps])

    # A compound with no long run (SOFT is usually only ever run on a
    # qualifying simulation) has no wear signal at all. Fitting the loose data
    # anyway produced a garbage slope that then pinned to MAX_DEG — 19 of 20
    # saturated fits in the 2023-2026 cache had ZERO long-run stints behind
    # them. Estimate those from a compound that WAS measured at this event
    # instead, using the measured cross-compound ratios, and fall back to the
    # global prior only if nothing was measured.
    measured = {c: cur.deg_rate for c, cur in curves.items() if strict.get(c)}
    if measured:
        ref = "MEDIUM" if "MEDIUM" in measured else next(iter(measured))
        for c, cur in list(curves.items()):
            if c in measured or c not in DEG_RATIO:
                continue
            est = measured[ref] * (DEG_RATIO[c] / DEG_RATIO[ref])
            # The ratio itself is measured only where the compound DID get a
            # long run, so it under-states wear for one that never did.
            est = max(est, DEG_UNMEASURED.get(c, 0.0))
            curves[c] = DegCurve(c, est, cur.baseline, cur.data_points,
                                 cur.confidence.rstrip("*") + "*", cur.sessions)
    else:
        for c, cur in list(curves.items()):
            if c in DEG_PRIOR:
                curves[c] = DegCurve(c, DEG_PRIOR[c], cur.baseline,
                                     cur.data_points,
                                     cur.confidence.rstrip("*") + "*", cur.sessions)

    # Sanity-check against physical reality. FP data is frequently polluted
    # (track evolution, wet running, traffic, fuel loads), which corrupts
    # both baselines and deg rates. Clamp to plausible bands anchored on
    # the Medium compound:
    #   - baseline offset vs Medium: SOFT ≈ -0.6s, HARD ≈ +0.4s (±1.0s band)
    #   - deg rate: physical minimum floor → 0.30 s/lap cap, SOFT ≥ MED ≥ HARD
    # Minimum floors prevent fuel-dominated regression zeroing out deg and
    # making Hard/Medium look identical to the strategy optimizer.
    EXPECTED_OFFSET = {"SOFT": -0.6, "MEDIUM": 0.0, "HARD": +0.4}
    OFFSET_TOLERANCE = 1.0
    MAX_DEG = 0.30
    MIN_DEG = {"SOFT": 0.06, "MEDIUM": 0.025, "HARD": 0.010}

    med = curves.get("MEDIUM")
    if med:
        for c in ("SOFT", "HARD"):
            cur = curves.get(c)
            if not cur:
                continue
            offset = cur.baseline - med.baseline
            expected = EXPECTED_OFFSET[c]
            if abs(offset - expected) > OFFSET_TOLERANCE:
                curves[c] = DegCurve(c, cur.deg_rate,
                                     med.baseline + expected, cur.data_points,
                                     cur.confidence.rstrip("*") + "*", cur.sessions)

    # Deg rate caps, floors, and monotonicity (SOFT wears fastest)
    for c, cur in list(curves.items()):
        floored = max(cur.deg_rate, MIN_DEG.get(c, 0.0))
        capped  = min(floored, MAX_DEG)
        if capped != cur.deg_rate:
            curves[c] = DegCurve(c, capped, cur.baseline, cur.data_points,
                                 cur.confidence.rstrip("*") + "*", cur.sessions)
    med = curves.get("MEDIUM")
    sft = curves.get("SOFT")
    hrd = curves.get("HARD")
    if med and sft and sft.deg_rate < med.deg_rate:
        curves["SOFT"] = DegCurve("SOFT", med.deg_rate * 1.3, sft.baseline,
                                  sft.data_points,
                                  sft.confidence.rstrip("*") + "*", sft.sessions)
    if med and hrd and hrd.deg_rate > med.deg_rate:
        curves["HARD"] = DegCurve("HARD", med.deg_rate * 0.7, hrd.baseline,
                                  hrd.data_points,
                                  hrd.confidence.rstrip("*") + "*", hrd.sessions)

    return curves


# ── Driver pace model ─────────────────────────────────────────────────────────

def build_pace_model(
    laps_raw:    list[dict],
    sc_events:   list[SCEvent],
    drivers_raw: dict[int, dict],
    curves:      dict[str, DegCurve],
    stints_raw:  list[dict],
    quali_times: dict[int, float] | None = None,
    exclude_laps: set[int] | None = None,
) -> dict[int, DriverPace]:
    """
    Age- and fuel-corrected pace delta per driver.
    If quali_times (driver_number → best Q lap) is supplied it is blended in
    as a prior — weighted equivalent to 10 race laps — so that early in the
    race, when few clean laps are available, the model relies on qualifying
    pace rather than noisy heavy-fuel data.
    exclude_laps: extra lap numbers to drop from the sample (e.g. laps run
    under a track-wide yellow, which are slow through no fault of the tyre).
    """
    sc_laps: set[int] = {ln for ev in sc_events for ln in range(ev.start_lap, ev.end_lap + 2)}
    if exclude_laps:
        sc_laps |= exclude_laps

    stint_map: dict[tuple, dict] = {}
    for s in stints_raw:
        end = s.get("lap_end") or 9999
        for ln in range(s["lap_start"], end + 1):
            stint_map[(s["driver_number"], ln)] = s

    by_driver: dict[int, list[float]] = {}
    for lap in laps_raw:
        dur = lap.get("lap_duration")
        if not dur or lap.get("is_pit_out_lap") or lap["lap_number"] in sc_laps:
            continue
        if not (55 < dur < 200):
            continue
        s = stint_map.get((lap["driver_number"], lap["lap_number"]))
        age_correction = 0.0
        fuel_correction = FUEL_RATE * lap["lap_number"]
        if s:
            c = s.get("compound", "")
            age = s.get("tyre_age_at_start", 0) + (lap["lap_number"] - s["lap_start"])
            curve = curves.get(c)
            if curve:
                age_correction = curve.deg_rate * age
        # Subtract both tyre-age and fuel contributions so we're comparing
        # drivers at equivalent tyre age AND equivalent fuel load.
        by_driver.setdefault(lap["driver_number"], []).append(
            dur - age_correction - fuel_correction)

    result: dict[int, DriverPace] = {}
    medians = []
    for num, times in by_driver.items():
        if len(times) < 3:
            continue
        ts = sorted(times)
        trim = max(1, len(ts) // 10)
        clean = ts[trim:-trim] if len(ts) > 2*trim else ts
        med = statistics.median(clean)
        medians.append(med)
        result[num] = DriverPace(
            driver_number=num,
            acronym=drivers_raw.get(num, {}).get("name_acronym", str(num)),
            pace_median=med,
            pace_std=statistics.stdev(clean) if len(clean) > 1 else 0.0,
            pace_delta=0.0,
            laps_counted=len(clean),
        )

    if medians:
        fm = statistics.median(medians)
        for p in result.values():
            p.pace_delta = round(p.pace_median - fm, 3)

    # Blend qualifying pace as a prior (equivalent to QUALI_PRIOR_LAPS race laps).
    # Qualifying is low-fuel, one-lap pace, so we scale the relative deltas to
    # race pace rather than using absolute times.
    QUALI_PRIOR_LAPS = 10
    if quali_times and len(quali_times) >= 5:
        q_vals = [v for v in quali_times.values() if v and v > 0]
        q_median = statistics.median(q_vals) if q_vals else 0
        r_median = fm if medians else 0
        if q_median > 0 and r_median > 0:
            scale = r_median / q_median
            all_nums = set(result) | set(quali_times)
            for num in all_nums:
                q_t = quali_times.get(num)
                q_delta_scaled = (q_t - q_median) * scale if q_t else 0.0
                if num in result:
                    p = result[num]
                    r_w = p.laps_counted
                    blended = (p.pace_delta * r_w + q_delta_scaled * QUALI_PRIOR_LAPS) / (r_w + QUALI_PRIOR_LAPS)
                    p.pace_delta = round(blended, 3)
                else:
                    # driver has quali time but no clean race laps yet
                    acro = drivers_raw.get(num, {}).get("name_acronym", str(num))
                    result[num] = DriverPace(
                        driver_number=num, acronym=acro,
                        pace_median=r_median + q_delta_scaled,
                        pace_std=0.3,
                        pace_delta=round(q_delta_scaled, 3),
                        laps_counted=0,
                    )

    return result


# ── Lap time prediction ───────────────────────────────────────────────────────

def _lap_t(compound: str, age: int, pace_delta: float,
           curves: dict[str, DegCurve], field_baseline: float) -> float:
    curve = curves.get(compound)
    if curve and curve.baseline > 0:
        return curve.baseline + curve.deg_rate * age + pace_delta
    return field_baseline + COMPOUND_DELTA.get(compound, 0) + 0.03 * age + pace_delta


def _hardness(compound: str) -> int:
    return {"SOFT": 0, "MEDIUM": 1, "HARD": 2}.get(compound, 1)


# Tyres wear faster on a heavy car. The fitted deg_rate is a race-average, so
# the coupling is CENTRED: full tank wears ~15% over the average, empty tank
# ~15% under (with 0.3 coupling). Race totals stay calibrated to the backtest;
# only stint ORDER becomes price-relevant — a soft sprint on fumes is now
# cheaper than the same laps on full tanks, matching how teams actually use it.
FUEL_WEAR_COUPLING = 0.3

# Tyre cliff: real degradation is roughly linear up to a compound's usable
# life, then accelerates as the tyre "falls off". A purely linear model
# underprices long stints, which on high-deg tracks (Barcelona, ~0.25s/lap)
# biases the optimizer to too few stops. Past MAX_LIFE we add a quadratic
# penalty so a 35-lap medium on a 20-lap tyre is correctly punished and the
# DP finds the 2-3 stop plans teams actually run. On low-deg tracks the cliff
# is never reached within a stint, so nothing changes there.
CLIFF_ACCEL = 0.045   # s/lap added per lap-squared beyond the cliff


def _cliff_life(compound: str, deg_rate: float) -> int:
    """Usable life before the cliff, in laps of tyre age. Bounded by the
    per-compound MAX_LIFE and (for high-deg surfaces) by where linear rise
    alone reaches the cliff threshold — whichever is sooner."""
    from engine.degradation import CLIFF_SECONDS, MAX_LIFE
    hard_cap = MAX_LIFE.get(compound, 40)
    if deg_rate and deg_rate > 0:
        linear_cap = CLIFF_SECONDS.get(compound, 2.0) / deg_rate + 6
        return int(min(hard_cap, linear_cap))
    return hard_cap


def _stint_lap_times(compound: str, start_age: int, length: int, abs_start: int,
                     total_laps: int, pace_delta: float,
                     curves: dict[str, DegCurve], field_baseline: float) -> list[float]:
    """Per-lap modelled lap times for one stint. _stint_time is just the sum of
    this; exposing the series lets callers draw a lap-by-lap race trace without
    changing any of the tuned strategy maths."""
    curve = curves.get(compound)
    deg = curve.deg_rate if (curve and curve.baseline > 0) else 0.03
    base = (curve.baseline if (curve and curve.baseline > 0)
            else field_baseline + COMPOUND_DELTA.get(compound, 0))
    cliff = _cliff_life(compound, deg)
    out = []
    for i in range(length):
        age = start_age + i
        fuel_frac = max(0.0, 1.0 - (abs_start + i) / max(1, total_laps))
        wear = 1.0 + FUEL_WEAR_COUPLING * (fuel_frac - 0.5)
        lap_t = base + deg * age * wear + pace_delta
        if age > cliff:
            over = age - cliff
            lap_t += CLIFF_ACCEL * over * over   # superlinear fall-off
        out.append(lap_t)
    return out


def _stint_time(compound: str, start_age: int, length: int, abs_start: int,
                total_laps: int, pace_delta: float,
                curves: dict[str, DegCurve], field_baseline: float) -> float:
    return sum(_stint_lap_times(compound, start_age, length, abs_start,
                                total_laps, pace_delta, curves, field_baseline))


def strategy_lap_trace(strategy, current_lap: int, total_laps: int,
                       curves: dict[str, DegCurve], field_baseline: float,
                       pace_delta: float, pit_loss: float) -> list[dict]:
    """Cumulative modelled race time per lap, from current_lap to the flag, for
    a given pit plan — the raw material for a race trace. Pit loss lands as a
    step at each stop lap. Purely derived from the existing lap model, so it
    changes no prediction behaviour."""
    trace: list[dict] = []
    cum = 0.0
    lap = current_lap
    compound = strategy.current_compound
    age = strategy.current_age
    stops = sorted(strategy.pits_remaining, key=lambda p: p.lap)
    boundaries = [p.lap for p in stops] + [total_laps]
    for idx, end_lap in enumerate(boundaries):
        length = max(0, end_lap - lap)
        if length:
            for i, t in enumerate(_stint_lap_times(compound, age, length, lap,
                                                   total_laps, pace_delta,
                                                   curves, field_baseline), 1):
                cum += t
                trace.append({"lap": lap + i, "cumulative": round(cum, 2),
                              "compound": compound})
        lap = end_lap
        if idx < len(stops):
            cum += pit_loss            # the stop shows as a step in the trace
            compound = stops[idx].compound
            age = 0
    return trace


# ── Strategy duel (1-stop vs 2-stop head-to-head "knife") ─────────────────────

def _stint_partitions(total_laps: int, n_stints: int, min_stint: int,
                      step: int = 1):
    """Yield every way to split `total_laps` into `n_stints` stint lengths, each
    at least `min_stint`. `step` coarsens the search for speed on long races."""
    if n_stints == 1:
        if total_laps >= min_stint:
            yield [total_laps]
        return
    # leave room for the remaining stints' minimums
    hi = total_laps - min_stint * (n_stints - 1)
    for first in range(min_stint, hi + 1, step):
        for rest in _stint_partitions(total_laps - first, n_stints - 1,
                                      min_stint, step):
            yield [first] + rest


def _best_fixed_plan(n_stops: int, curves: dict[str, DegCurve],
                     field_baseline: float, pit_loss: float, total_laps: int,
                     pace_delta: float = 0.0) -> Optional[dict]:
    """Cheapest `n_stops`-stop plan (start compound + pit compounds + pit laps)
    under the tuned lap model. Enforces the F1 two-compound rule and MIN_STINT.
    Brute force over compound sequences × stint-length partitions — a few tens of
    thousands of cheap evaluations, fine for an on-demand call."""
    n_stints = n_stops + 1
    # Coarsen the partition search on long races so a 2-stopper stays quick.
    step = 1 if total_laps <= 45 or n_stints <= 2 else 2
    best: Optional[dict] = None
    for seq in itertools.product(DRY, repeat=n_stints):
        if len(set(seq)) < 2:          # must run at least two dry compounds
            continue
        for lengths in _stint_partitions(total_laps, n_stints, MIN_STINT, step):
            t = pit_loss * n_stops
            abs_start = 0
            for compound, length in zip(seq, lengths):
                t += _stint_time(compound, 0, length, abs_start, total_laps,
                                 pace_delta, curves, field_baseline)
                abs_start += length
            if best is None or t < best["total_time"]:
                pit_laps = list(itertools.accumulate(lengths[:-1]))
                best = {
                    "stops":         n_stops,
                    "compounds":     list(seq),
                    "pit_laps":      pit_laps,
                    "stint_lengths": list(lengths),
                    "total_time":    round(t, 2),
                }
    return best


def _plan_to_strategy(plan: dict) -> DriverStrategy:
    return DriverStrategy(
        driver_number=0, acronym="", current_lap=0,
        current_compound=plan["compounds"][0], current_age=0,
        pits_remaining=[PitPlan(lap, comp) for lap, comp
                        in zip(plan["pit_laps"], plan["compounds"][1:])],
        total_time_from_now=plan["total_time"], laps_until_must_pit=None,
        confidence="")


def strategy_duel(curves: dict[str, DegCurve], field_baseline: float,
                  pit_loss: float, total_laps: int,
                  pace_delta: float = 0.0) -> Optional[dict]:
    """Head-to-head "knife": the optimal 1-stop vs the optimal 2-stop, priced on
    the same tyre model. Returns a lap-by-lap trace of how far the 1-stopper is
    ahead on corrected time (positive = 1-stop ahead, i.e. the 2-stopper has spent
    more time), the two plans, and the gap at the flag. This is the data behind an
    RSS-style divergence chart. Returns None if a plan can't be built (e.g. a race
    too short for two stops)."""
    one = _best_fixed_plan(1, curves, field_baseline, pit_loss, total_laps, pace_delta)
    two = _best_fixed_plan(2, curves, field_baseline, pit_loss, total_laps, pace_delta)
    if one is None or two is None:
        return None

    def cum_by_lap(plan: dict) -> dict[int, float]:
        return {p["lap"]: p["cumulative"] for p in strategy_lap_trace(
            _plan_to_strategy(plan), 0, total_laps, curves, field_baseline,
            pace_delta, pit_loss)}

    c1, c2 = cum_by_lap(one), cum_by_lap(two)
    laps = sorted(set(c1) & set(c2))
    # 2-stop cumulative time minus 1-stop: >0 means the 2-stopper is slower here,
    # so the 1-stopper is ahead — matching the "1-stopper ahead (s)" axis.
    trace = [{"lap": l, "one_stop_ahead": round(c2[l] - c1[l], 2)} for l in laps]
    flag_gap = trace[-1]["one_stop_ahead"] if trace else 0.0
    keep = ("compounds", "pit_laps", "stint_lengths", "total_time")
    return {
        "total_laps": total_laps,
        "pit_loss":   round(pit_loss, 2),
        "one_stop":   {k: one[k] for k in keep},
        "two_stop":   {k: two[k] for k in keep},
        "pit_laps":   {"one_stop": one["pit_laps"], "two_stop": two["pit_laps"]},
        "trace":      trace,
        "flag_gap":   flag_gap,
        "verdict":    "one_stop" if flag_gap > 0 else "two_stop" if flag_gap < 0 else "tie",
    }


# ── Strategy optimizer (DP) ───────────────────────────────────────────────────

def optimize_strategy(
    current_lap:      int,
    total_laps:       int,
    current_compound: str,
    current_age:      int,
    pace_delta:       float,
    curves:           dict[str, DegCurve],
    field_baseline:   float,
    pit_loss:         float = PIT_LOSS,
    needs_compound_change: bool = False,   # F1 rule: must use 2 dry compounds
    force_stops:      int | None = None,   # constrain to exactly N stops
    forbid_repeat_compound: bool = False,  # no pitting onto the same compound back-to-back
    available:        dict[str, int] | None = None,  # new sets left per compound
) -> DriverStrategy:

    remaining = total_laps - current_lap
    if remaining <= 0:
        return DriverStrategy(0, "", current_lap, current_compound,
                              current_age, [], 0.0, None, "LOW")

    def stint_t(c: str, start_age: int, length: int, abs_start: int) -> float:
        return _stint_time(c, start_age, length, abs_start, total_laps,
                           pace_delta, curves, field_baseline)

    def allow(n: int) -> bool:
        return force_stops is None or force_stops == n

    def in_stock(*fitted: str) -> bool:
        """A plan can only fit tyres the driver still has.

        Pure lap-time optimisation happily recommends three Softs at a track
        where the field has none left after qualifying; this is what keeps the
        search inside the garage's actual stock.
        """
        if not available:
            return True
        need: dict[str, int] = {}
        for c in fitted:
            need[c] = need.get(c, 0) + 1
        return all(available.get(c, 0) >= n for c, n in need.items())

    best = float("inf")
    best_pits: list[PitPlan] = []

    # 0-stop — only legal if the driver has already used two dry compounds
    if not needs_compound_change and allow(0):
        t = stint_t(current_compound, current_age, remaining, current_lap)
        if t < best:
            best, best_pits = t, []

    # Effective cost per stop includes execution/traffic risk beyond pit lane time
    stop_cost = pit_loss + STOP_RISK

    # 1-stop
    for pit in range(MIN_STINT, remaining - MIN_STINT + 1) if allow(1) else []:
        for c2 in DRY:
            if c2 == current_compound and (needs_compound_change or forbid_repeat_compound or current_age < 5):
                continue
            if _hardness(c2) < _hardness(current_compound) and (remaining - pit) > SOFT_SPLASH_MAX:
                continue
            if not in_stock(c2):
                continue
            t = (stint_t(current_compound, current_age, pit, current_lap)
                 + stop_cost + stint_t(c2, 0, remaining - pit, current_lap + pit))
            if t < best:
                best, best_pits = t, [PitPlan(current_lap + pit, c2)]

    # 2-stop
    for p1 in (range(MIN_STINT, remaining - 2*MIN_STINT + 1, 2) if allow(2) else []):
        for p2 in range(MIN_STINT, remaining - p1 - MIN_STINT + 1, 2):
            r3 = remaining - p1 - p2
            if r3 < MIN_STINT:
                continue
            for c2 in DRY:
                for c3 in DRY:
                    if needs_compound_change and c2 == current_compound and c3 == current_compound:
                        continue
                    if forbid_repeat_compound and (c2 == current_compound or c3 == c2):
                        continue
                    if _hardness(c3) < _hardness(c2) and r3 > SOFT_SPLASH_MAX:
                        continue
                    if not in_stock(c2, c3):
                        continue
                    t = (stint_t(current_compound, current_age, p1, current_lap) + stop_cost
                         + stint_t(c2, 0, p2, current_lap + p1) + stop_cost
                         + stint_t(c3, 0, r3, current_lap + p1 + p2))
                    if t < best:
                        best = t
                        best_pits = [PitPlan(current_lap + p1, c2),
                                     PitPlan(current_lap + p1 + p2, c3)]

    # 3-stop — only worth searching on longer, high-deg races. Coarse step (3)
    # keeps the quadruple loop tractable; the cliff penalty is what makes these
    # plans win when a 2-stop would drag a tyre well past its life.
    if remaining >= 4 * MIN_STINT and allow(3):
        step = 3
        for p1 in range(MIN_STINT, remaining - 3 * MIN_STINT + 1, step):
            for p2 in range(MIN_STINT, remaining - p1 - 2 * MIN_STINT + 1, step):
                for p3 in range(MIN_STINT, remaining - p1 - p2 - MIN_STINT + 1, step):
                    r4 = remaining - p1 - p2 - p3
                    if r4 < MIN_STINT:
                        continue
                    # sensible compound families only: don't brute all 27 — the
                    # start compound is fixed, then run harder-then-splash logic
                    for c2 in DRY:
                        for c3 in DRY:
                            for c4 in DRY:
                                seq = [current_compound, c2, c3, c4]
                                if needs_compound_change and len(set(seq)) < 2:
                                    continue
                                if forbid_repeat_compound and any(
                                        seq[j] == seq[j - 1] for j in range(1, 4)):
                                    continue
                                # no mid-race downgrade to a softer tyre unless
                                # that stint is short enough to be a late splash
                                seq_lens = [p2, p3, r4]
                                bad = any(
                                    _hardness(seq[j]) < _hardness(seq[j - 1])
                                    and seq_lens[j - 1] > SOFT_SPLASH_MAX
                                    for j in range(1, 4))
                                if bad:
                                    continue
                                if not in_stock(c2, c3, c4):
                                    continue
                                t = (stint_t(current_compound, current_age, p1, current_lap) + stop_cost
                                     + stint_t(c2, 0, p2, current_lap + p1) + stop_cost
                                     + stint_t(c3, 0, p3, current_lap + p1 + p2) + stop_cost
                                     + stint_t(c4, 0, r4, current_lap + p1 + p2 + p3))
                                if t < best:
                                    best = t
                                    best_pits = [PitPlan(current_lap + p1, c2),
                                                 PitPlan(current_lap + p1 + p2, c3),
                                                 PitPlan(current_lap + p1 + p2 + p3, c4)]

    # Fallback: compound change still required but no legal plan found
    # (too few laps left for MIN_STINT windows) — force a late splash stop
    if best == float("inf"):
        # Prefer a compound still in stock. If the garage genuinely has no new
        # set of another compound the driver still has to satisfy the
        # two-compound rule, and does it on a scrubbed set — our inventory only
        # counts NEW sets, so fall back to any different compound.
        alt = next((c for c in ("MEDIUM", "HARD", "SOFT")
                    if c != current_compound and (available or {}).get(c, 0) >= 1),
                   None)
        if alt is None:
            alt = "SOFT" if current_compound != "SOFT" else "MEDIUM"
        splash = min(3, max(1, remaining - 1))
        pit_at = remaining - splash
        t = (stint_t(current_compound, current_age, pit_at, current_lap) + stop_cost
             + stint_t(alt, 0, splash, current_lap + pit_at))
        best = t
        best_pits = [PitPlan(current_lap + pit_at, alt)]

    # Tyre cliff
    must_pit = None
    curve = curves.get(current_compound)
    if curve and curve.deg_rate > 0:
        try:
            from engine.degradation import CLIFF_SECONDS, MAX_LIFE
            delta = CLIFF_SECONDS.get(current_compound, 2.0)
            cliff = min(int(delta / curve.deg_rate), MAX_LIFE.get(current_compound, 40))
            laps_to_cliff = max(0, cliff - current_age)
            if laps_to_cliff < remaining:
                must_pit = laps_to_cliff
        except ImportError:
            pass

    return DriverStrategy(
        driver_number=0,
        acronym="",
        current_lap=current_lap,
        current_compound=current_compound,
        current_age=current_age,
        pits_remaining=best_pits,
        total_time_from_now=round(best, 2),
        laps_until_must_pit=must_pit,
        confidence="HIGH" if curves else "LOW",
    )


def evaluate_prescribed_strategy(
    current_lap:      int,
    total_laps:       int,
    current_compound: str,
    current_age:      int,
    pace_delta:       float,
    curves:           dict[str, DegCurve],
    field_baseline:   float,
    pits:             list[PitPlan],
    pit_loss:         float = PIT_LOSS,
) -> DriverStrategy:
    """
    Cost a FIXED pit plan with the same lap-time model the optimizer uses,
    so prescribed (user-edited or historical) strategies are comparable to
    optimizer output. Pit laps outside (current_lap, total_laps) are dropped.
    """
    remaining = total_laps - current_lap
    if remaining <= 0:
        return DriverStrategy(0, "", current_lap, current_compound,
                              current_age, [], 0.0, None, "LOW")

    def stint_t(c: str, start_age: int, length: int, abs_start: int) -> float:
        return _stint_time(c, start_age, length, abs_start, total_laps,
                           pace_delta, curves, field_baseline)

    plan = sorted((p for p in pits if current_lap < p.lap < total_laps),
                  key=lambda p: p.lap)
    stop_cost = pit_loss + STOP_RISK

    total = 0.0
    lap, compound, age = current_lap, current_compound, current_age
    for p in plan:
        stint_len = p.lap - lap
        total += stint_t(compound, age, stint_len, lap) + stop_cost
        lap, compound, age = p.lap, p.compound, p.tyre_age  # used sets start older
    total += stint_t(compound, age, total_laps - lap, lap)

    return DriverStrategy(
        driver_number=0,
        acronym="",
        current_lap=current_lap,
        current_compound=current_compound,
        current_age=current_age,
        pits_remaining=plan,
        total_time_from_now=round(total, 2),
        laps_until_must_pit=None,
        confidence="HIGH" if curves else "LOW",
    )


# ── Undercut calculator ───────────────────────────────────────────────────────

def calc_undercut(
    driver:         dict,
    driver_ahead:   dict,
    curves:         dict[str, DegCurve],
    pace_model:     dict[int, DriverPace],
    field_baseline: float,
    pit_loss:       float = PIT_LOSS,
    horizon:        int   = 5,
) -> UndercutResult:
    """
    Net gain of pitting THIS lap vs one more lap, simulated over `horizon` laps.
    Positive time_gain = pitting now is beneficial.
    """
    num  = driver["driver_number"]
    numa = driver_ahead["driver_number"]
    gap  = _parse_gap(driver.get("interval"), field_baseline)

    c_d, c_a   = driver.get("compound", "MEDIUM"), driver_ahead.get("compound", "MEDIUM")
    age_d, age_a = driver.get("tyre_age", 0) or 0, driver_ahead.get("tyre_age", 0) or 0
    pd_d = (pace_model.get(num)  or DriverPace(num,  "", 0, 0, 0, 0)).pace_delta
    pd_a = (pace_model.get(numa) or DriverPace(numa, "", 0, 0, 0, 0)).pace_delta

    fresh = "MEDIUM" if c_d == "HARD" else "SOFT"

    # Scenario A: pit now
    t_A_d = pit_loss + sum(_lap_t(fresh, i, pd_d, curves, field_baseline) for i in range(horizon))
    t_A_a = sum(_lap_t(c_a, age_a + i, pd_a, curves, field_baseline) for i in range(horizon))
    gap_A = (gap if isinstance(gap, (int, float)) else 0.0) + t_A_d - t_A_a

    # Scenario B: one more lap then pit
    t_B_d = (_lap_t(c_d, age_d, pd_d, curves, field_baseline) + pit_loss
             + sum(_lap_t(fresh, i, pd_d, curves, field_baseline) for i in range(horizon - 1)))
    t_B_a = sum(_lap_t(c_a, age_a + i, pd_a, curves, field_baseline) for i in range(horizon))
    gap_B = (gap if isinstance(gap, (int, float)) else 0.0) + t_B_d - t_B_a

    time_gain = round(gap_B - gap_A, 2)
    viable    = gap_A < 0

    if viable:
        rec = f"PIT NOW — emerge {abs(gap_A):.1f}s ahead of {driver_ahead.get('acronym')}"
    elif time_gain > 0:
        rec = f"PIT SOON — {time_gain:.1f}s net gain vs waiting ({gap_A:+.1f}s after)"
    else:
        rec = "STAY OUT — undercut not advantageous"

    return UndercutResult(
        driver=driver.get("acronym", ""),
        target=driver_ahead.get("acronym", ""),
        gap_to_target=round(gap if isinstance(gap, (int, float)) else 0, 2),
        time_gain=time_gain,
        viable=viable,
        recommendation=rec,
    )


def _parse_gap(gap, lap_time_estimate: float) -> float:
    """
    Parse gap_to_leader in its various formats:
      numeric        → as-is
      'LEADER'       → 0
      '+3.131'       → 3.131
      '+1 LAP'       → 1 × lap_time_estimate
      '+2 LAPS'      → 2 × lap_time_estimate
      None / other   → 0
    """
    if isinstance(gap, (int, float)):
        return float(gap)
    if not isinstance(gap, str):
        return 0.0
    g = gap.strip().upper()
    if g in ("LEADER", "", "—", "-"):
        return 0.0
    if "LAP" in g:
        try:
            n = int(g.replace("+", "").split()[0])
        except (ValueError, IndexError):
            n = 1
        return n * lap_time_estimate
    try:
        return float(g.replace("+", ""))
    except ValueError:
        return 0.0


# ── Full race simulation ──────────────────────────────────────────────────────

def _cumulative_gaps(active_drivers: list[dict], field_baseline: float) -> dict[int, float]:
    """Chain intervals down the running order into gaps-to-leader (seconds).

    gap_to_leader saturates at '+1 LAP' for lapped drivers, which would give
    every lapped driver the same gap — chaining the per-driver interval preserves
    their true relative spacing. direct is exact for unlapped drivers; for lapped
    drivers it saturates at N×lap_time, acting as a lower bound. The chained
    interval misses lap boundaries, so we take the max of both.
    """
    gaps: dict[int, float] = {}
    running = 0.0
    for i, d in enumerate(active_drivers):
        if i > 0:
            chained = running + _parse_gap(d.get("interval"), field_baseline)
            direct  = _parse_gap(d.get("gap_to_leader"), field_baseline)
            running = max(chained, direct)
        gaps[d["driver_number"]] = running
    return gaps


def _neutralised_pit_loss(sc_events: list[SCEvent], current_lap: int,
                          pit_loss: float) -> tuple[Optional[SCEvent], float]:
    """Discount the pit-lane time loss while a neutralisation is active.

    Measured over 2023-2026: taking the stop under a neutralisation costs 0.78x
    the green-flag loss under a full SC (n=177) and 0.69x under a VSC (n=71),
    against rivals who stayed out. The old figures (0.45x SC / 0.65x VSC) priced
    a full safety car as a far bigger windfall than it actually is — in practice
    a bunched field and a busy pit lane eat most of the theoretical saving.
    """
    active_ev = next((ev for ev in sc_events
                      if ev.start_lap <= current_lap <= ev.end_lap + 1), None)
    if active_ev is None:
        return None, pit_loss
    if active_ev.type == "VSC":
        return active_ev, pit_loss * VSC_PIT_FACTOR
    return active_ev, pit_loss * SC_PIT_FACTOR


def simulate_race(
    drivers_sorted: list[dict],
    current_lap:    int,
    total_laps:     int,
    curves:         dict[str, DegCurve],
    pace_model:     dict[int, DriverPace],
    sc_events:      list[SCEvent],
    pit_loss:       float = PIT_LOSS,
    track_position_weight: float = 0.5,  # 0.85 street / 0.5 normal — tuned on 81-race backtest
    prescribed_strategies: dict[int, list[PitPlan]] | None = None,
    inventory: dict[int, dict[str, int]] | None = None,  # per-driver sets left
    circuit:        str = "",   # feeds the Monte Carlo SC/DNF rate lookups
) -> list[DriverForecast]:
    """
    track_position_weight: how much current position (gap) influences the
    final predicted order vs pure pace simulation (0=pure pace, 1=pure position).
    At Monaco ~0.8 (almost impossible to overtake without pit stop).
    On normal circuits ~0.4–0.5.

    inventory: {driver_number: {compound: new sets left}}. A driver can only be
    planned onto tyres they still hold — one who spent their Softs in Q3 cannot
    be sent back out on them, while a team-mate who saved a set can.

    prescribed_strategies: drivers listed here run the given fixed pit plan
    (costed via evaluate_prescribed_strategy) instead of the DP optimizer —
    used for counterfactual/what-if simulation against known stint histories.

    circuit: raw circuit_short_name, used only by the Monte Carlo pass to look
    up the per-circuit SC rate (SC_RATE_CIRCUIT). Optional and separate from
    track_position_weight/pit_loss, which callers already pre-resolve from
    circuit themselves.
    """
    if total_laps <= current_lap:
        return []

    baselines = [c.baseline for c in curves.values() if c.baseline > 0]
    field_baseline = statistics.median(baselines) if baselines else 85.0

    # Cumulative gaps by chaining intervals down the running order.
    active = [d for d in drivers_sorted if not d.get("retired")]
    cumulative_gaps = _cumulative_gaps(active, field_baseline)

    # Neutralisation state is the same for every driver this lap — compute once.
    active_ev, effective_pit_loss = _neutralised_pit_loss(sc_events, current_lap, pit_loss)
    sc_active = active_ev is not None

    scored: list[tuple[float, DriverForecast]] = []

    for driver in drivers_sorted:
        if driver.get("retired"):
            continue

        num      = driver["driver_number"]
        acronym  = driver.get("acronym", str(num))
        compound = driver.get("compound") or "MEDIUM"
        age      = driver.get("tyre_age") or 0
        pos      = driver.get("position") or 99

        gap_s = cumulative_gaps.get(num, 0.0)

        pace = pace_model.get(num)
        pd   = pace.pace_delta if pace else 0.0
        conf = ("HIGH" if pace and pace.laps_counted >= 10
                else "MEDIUM" if pace and pace.laps_counted >= 5
                else "LOW")

        # F1 rule: must use ≥2 dry compounds — if driver has only used one,
        # a pit stop is mandatory before the end
        compounds_used = driver.get("compounds_used") or [compound]
        dry_used = {c for c in compounds_used if c in DRY}
        needs_change = len(dry_used) < 2

        if prescribed_strategies is not None and num in prescribed_strategies:
            strat = evaluate_prescribed_strategy(
                current_lap, total_laps, compound, age, pd, curves,
                field_baseline, prescribed_strategies[num], effective_pit_loss)
            strat.driver_number = num
            strat.acronym = acronym
        else:
            strat = optimize_strategy(current_lap, total_laps, compound, age,
                                      pd, curves, field_baseline, effective_pit_loss,
                                      needs_compound_change=needs_change,
                                      available=(inventory or {}).get(num))
            strat.driver_number = num
            strat.acronym = acronym

            # If SC is active and a stop is still needed, recommend taking it NOW
            if sc_active and strat.pits_remaining:
                first = strat.pits_remaining[0]
                if first.lap > current_lap + 1:
                    strat.pits_remaining[0] = PitPlan(current_lap + 1, first.compound)

        # Blend current gap (track position) with simulated pace advantage.
        # Pure pace sim overpredicts overtaking — especially at Monaco.
        # track_position_weight=0.6 means 60% current gap, 40% pace simulation.
        pace_finish_time = gap_s + strat.total_time_from_now
        # Position-only estimate: assume current order holds, gaps stay as-is.
        # (Adding pit-stop debt here was tried and made backtests worse —
        # the optimizer's planned-stop count is too noisy to anchor on.)
        position_finish_time = gap_s
        finish_time = (track_position_weight * position_finish_time
                       + (1 - track_position_weight) * pace_finish_time)

        # Undercut vs driver immediately ahead
        driver_ahead = next(
            (d for d in drivers_sorted
             if not d.get("retired") and (d.get("position") or 99) == pos - 1),
            None
        )
        undercut = None
        if driver_ahead:
            ivl = _parse_gap(driver.get("interval"), field_baseline)
            if 0 < abs(ivl) < 6.0:
                undercut = calc_undercut(driver, driver_ahead, curves,
                                         pace_model, field_baseline, pit_loss)

        scored.append((finish_time, DriverForecast(
            driver_number=num,
            acronym=acronym,
            current_position=pos,
            predicted_position=0,
            predicted_gap=0.0,
            confidence=conf,
            strategy=strat,
            undercut=undercut,
        )))

    scored.sort(key=lambda x: x[0])
    winner = scored[0][0] if scored else 0.0
    for rank, (ft, fc) in enumerate(scored, 1):
        fc.predicted_position = rank
        fc.predicted_gap = round(ft - winner, 2)

    forecasts = [fc for _, fc in scored]

    # Monte Carlo pass adds probability distributions
    run_monte_carlo(forecasts, scored, current_lap, total_laps,
                    sc_events, field_baseline, pit_loss, circuit=circuit)

    return forecasts


# ── Monte Carlo simulation ────────────────────────────────────────────────────

def run_monte_carlo(
    forecasts:      list[DriverForecast],
    scored:         list[tuple[float, DriverForecast]],
    current_lap:    int,
    total_laps:     int,
    sc_events:      list[SCEvent],
    field_baseline: float,
    pit_loss:       float,
    n_runs:         int = 500,
    circuit:        str = "",
) -> None:
    """
    Perturb each driver's deterministic finish time with:
      1. Pace noise        — gaussian, scaled by their pace_std proxy
      2. SC lottery        — if a random SC falls in the remaining laps,
                             drivers who haven't pitted yet gain ~half the
                             pit loss (cheap stop), others lose nothing
      3. Minor incident      — flat ~2% chance per driver of a smaller time
                             loss (traffic, slow stop, light damage)
      4. DNF                — chance from the measured field-wide rate
                             (DNF_RATE_DEFAULT), scaled by how much race
                             distance remains

    Mutates forecasts in place with win/podium/points probabilities and
    P5–P95 position range.
    """
    import random
    from engine.circuits import is_street_circuit

    if not scored:
        return

    remaining = total_laps - current_lap
    sc_rate  = (SC_RATE_STREET if is_street_circuit(circuit)
               else _circuit_rate(SC_RATE_CIRCUIT, SC_RATE_DEFAULT, circuit))
    dnf_rate = DNF_RATE_DEFAULT
    p_sc     = 1 - _sc_p_no(sc_rate, current_lap, total_laps)
    # dnf_rate is measured as a whole-race probability; scale it down by how
    # much of the race is left so a driver 2 laps from the flag doesn't carry
    # the same DNF odds as one on the formation lap.
    p_dnf    = 1 - (1 - dnf_rate) ** (max(0, remaining) / max(1, total_laps))

    base_times = {fc.driver_number: ft for ft, fc in scored}
    has_stop_planned = {
        fc.driver_number: len(fc.strategy.pits_remaining) > 0 for _, fc in scored
    }

    # Pace noise: traffic, tyre warm-up, small mistakes, weather drift.
    # ~0.4s/√lap gives ±2s over 25 laps, ±3.5s over 70 — roughly matches
    # how much real race gaps wander lap to lap
    sigma = 0.4 * (remaining ** 0.5)

    finish_counts: dict[int, list[int]] = {fc.driver_number: [] for fc in forecasts}

    active_count = len(forecasts)

    for _ in range(n_runs):
        run_times = []
        sc_happens = random.random() < p_sc
        dnf_count = 0
        for fc in forecasts:
            t = base_times[fc.driver_number]
            t += random.gauss(0, sigma)
            if sc_happens and has_stop_planned[fc.driver_number]:
                # Free-ish pit stop under SC: refund ~60% of pit loss
                t -= pit_loss * 0.6
            if random.random() < 0.02:
                t += random.uniform(20, 80)   # incident / slow stop / damage
            if random.random() < p_dnf:
                # Mechanical failure / crash — place behind all finishers
                t += 1000 + dnf_count
                dnf_count += 1
            run_times.append((t, fc.driver_number))
        run_times.sort()
        for rank, (_, num) in enumerate(run_times, 1):
            finish_counts[num].append(rank)

    for fc in forecasts:
        positions = sorted(finish_counts[fc.driver_number])
        if not positions:
            continue
        n = len(positions)
        fc.win_probability    = round(sum(1 for p in positions if p == 1) / n, 3)
        fc.podium_probability = round(sum(1 for p in positions if p <= 3) / n, 3)
        fc.points_probability = round(sum(1 for p in positions if p <= 10) / n, 3)
        fc.position_range     = (positions[int(n * 0.05)], positions[int(n * 0.95) - 1])
        fc.mean_finish        = round(sum(positions) / n, 2)


# ── Serialisation ─────────────────────────────────────────────────────────────

def forecast_to_dict(fc: DriverForecast) -> dict:
    s, u = fc.strategy, fc.undercut
    return {
        "driver_number":      fc.driver_number,
        "acronym":            fc.acronym,
        "current_position":   fc.current_position,
        "predicted_position": fc.predicted_position,
        "predicted_gap":      fc.predicted_gap,
        "confidence":         fc.confidence,
        "strategy": {
            "current_compound":    s.current_compound,
            "current_age":         s.current_age,
            "pits_remaining":      [{"lap": p.lap, "compound": p.compound}
                                    for p in s.pits_remaining],
            "stop_count":          len(s.pits_remaining),
            "laps_until_must_pit": s.laps_until_must_pit,
        },
        "undercut": {
            "target":         u.target,
            "gap_to_target":  u.gap_to_target,
            "time_gain":      u.time_gain,
            "viable":         u.viable,
            "recommendation": u.recommendation,
        } if u else None,
        "win_probability":    fc.win_probability,
        "podium_probability": fc.podium_probability,
        "points_probability": fc.points_probability,
        "position_range":     list(fc.position_range),
        "mean_finish":        fc.mean_finish,
    }


def curves_to_dict(curves: dict[str, DegCurve]) -> dict:
    return {
        c: {
            "deg_rate":    round(d.deg_rate, 4),
            "baseline":    round(d.baseline, 3),
            "confidence":  d.confidence,
            "sessions":    d.sessions,
            "data_points": d.data_points,
        }
        for c, d in curves.items()
    }
