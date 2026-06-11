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
import statistics

# ── Constants ────────────────────────────────────────────────────────────────

PIT_LOSS        = 22.0   # seconds lost per pit stop (pit lane time loss)
STOP_RISK       = 6.0    # extra penalty per stop: traffic, out-lap, execution risk
SC_LAP_MULT     = 1.35   # median lap time > 35% above session median → SC
MIN_STINT       = 8      # minimum viable stint length
SOFT_SPLASH_MAX = 15     # Soft allowed as final compound only if ≤ this many laps

# RACE data dominates when available — fuel burn-off and track evolution make
# FP deg rates 2-3x higher than what actually materialises in the race
FP_WEIGHTS = {"FP1": 0.3, "FP2": 1.0, "FP3": 0.9, "RACE": 3.0}

COMPOUND_DELTA = {"SOFT": -0.6, "MEDIUM": 0.0, "HARD": +0.4}   # vs fresh Medium
DRY = ["SOFT", "MEDIUM", "HARD"]

STREET_CIRCUITS = {"monaco", "baku", "singapore", "jeddah", "las_vegas", "miami"}
SC_RATE_DEFAULT = 0.0067
SC_RATE_STREET  = 0.0120


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

    events, start, prev = [], sc_laps[0], sc_laps[0]
    for ln in sc_laps[1:]:
        if ln > prev + 2:
            events.append(SCEvent(start, prev, "SC"))
            start = ln
        prev = ln
    events.append(SCEvent(start, prev, "SC"))
    return events


def sc_probability(sc_events: list[SCEvent], current_lap: int,
                   total_laps: int, circuit: str = "") -> float:
    remaining = max(0, total_laps - current_lap)
    if remaining <= 0:
        return 0.0
    rate = SC_RATE_STREET if any(c in circuit.lower() for c in STREET_CIRCUITS) \
           else SC_RATE_DEFAULT
    p_no = (1 - rate) ** remaining
    if sc_events:
        p_no = min(p_no * 1.15, 0.95)
    return round(1 - p_no, 3)


# ── Deg curves from FP data ───────────────────────────────────────────────────

def build_deg_curves(
    fp_data: list[tuple[str, list[dict], list[dict]]]
) -> dict[str, DegCurve]:

    samples: dict[str, list[tuple]] = {}

    for name, laps_raw, stints_raw in fp_data:
        w = FP_WEIGHTS.get(name, 0.5)

        stint_map: dict[tuple, dict] = {}
        for s in stints_raw:
            end = s.get("lap_end") or 9999
            for ln in range(s["lap_start"], end + 1):
                stint_map[(s["driver_number"], ln)] = s

        by_c: dict[str, list[tuple]] = {}
        for lap in laps_raw:
            dur = lap.get("lap_duration")
            if not dur or dur > 200 or dur < 55 or lap.get("is_pit_out_lap"):
                continue
            s = stint_map.get((lap["driver_number"], lap["lap_number"]))
            if not s:
                continue
            c = s.get("compound", "")
            if c not in DRY:
                continue
            age = float(s.get("tyre_age_at_start", 0) + lap["lap_number"] - s["lap_start"])
            by_c.setdefault(c, []).append((age, dur))

        for c, data in by_c.items():
            if len(data) < 5:
                continue
            xs, ys = zip(*data)
            n = len(xs)
            mx, my = sum(xs)/n, sum(ys)/n
            denom = sum((x-mx)**2 for x in xs)
            if denom == 0:
                continue
            slope = sum((x-mx)*(y-my) for x,y in zip(xs,ys)) / denom
            samples.setdefault(c, []).append((slope, my - slope*mx, w, n, name))

    curves: dict[str, DegCurve] = {}
    for c, samps in samples.items():
        tw = sum(s[2] for s in samps)
        if tw == 0:
            continue
        deg  = sum(s[0]*s[2] for s in samps) / tw
        base = sum(s[1]*s[2] for s in samps) / tw
        pts  = sum(s[3] for s in samps)
        conf = "HIGH" if pts >= 20 else "MEDIUM" if pts >= 8 else "LOW"
        curves[c] = DegCurve(c, max(deg, 0.0), base, pts, conf, [s[4] for s in samps])

    # Sanity-check baselines: Soft must be fastest, Hard must be slowest.
    # FP Soft data is often contaminated by track evolution / cool-down laps,
    # making its regression baseline unreliable. If the ordering is wrong,
    # anchor the corrupted compound to Medium ± known compound offset AND
    # floor its deg rate — the same polluted data underestimates wear.
    # Physical reality: deg(SOFT) > deg(MEDIUM) > deg(HARD).
    med = curves.get("MEDIUM")
    sft = curves.get("SOFT")
    hrd = curves.get("HARD")
    if med:
        if sft and sft.baseline > med.baseline:
            # Soft data untrustworthy: anchor baseline and floor deg above Medium's
            fixed_deg = max(sft.deg_rate, med.deg_rate * 1.3)
            curves["SOFT"] = DegCurve("SOFT", fixed_deg,
                                      med.baseline - 0.6, sft.data_points,
                                      sft.confidence + "*", sft.sessions)
        if hrd and hrd.baseline < med.baseline:
            # Hard data untrustworthy: anchor baseline and cap deg below Medium's
            fixed_deg = min(hrd.deg_rate, med.deg_rate * 0.7)
            curves["HARD"] = DegCurve("HARD", fixed_deg,
                                      med.baseline + 0.4, hrd.data_points,
                                      hrd.confidence + "*", hrd.sessions)

    return curves


# ── Driver pace model ─────────────────────────────────────────────────────────

def build_pace_model(
    laps_raw:    list[dict],
    sc_events:   list[SCEvent],
    drivers_raw: dict[int, dict],
    curves:      dict[str, DegCurve],
    stints_raw:  list[dict],
) -> dict[int, DriverPace]:
    """Age-corrected pace: remove tyre-deg component so we compare drivers at equivalent tyre age."""
    sc_laps: set[int] = {ln for ev in sc_events for ln in range(ev.start_lap, ev.end_lap + 2)}

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
        if s:
            c = s.get("compound", "")
            age = s.get("tyre_age_at_start", 0) + (lap["lap_number"] - s["lap_start"])
            curve = curves.get(c)
            if curve:
                age_correction = curve.deg_rate * age
        by_driver.setdefault(lap["driver_number"], []).append(dur - age_correction)

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
) -> DriverStrategy:

    remaining = total_laps - current_lap
    if remaining <= 0:
        return DriverStrategy(0, "", current_lap, current_compound,
                              current_age, [], 0.0, None, "LOW")

    def stint_t(c: str, start_age: int, length: int) -> float:
        return sum(_lap_t(c, start_age + i, pace_delta, curves, field_baseline)
                   for i in range(length))

    best = float("inf")
    best_pits: list[PitPlan] = []

    # 0-stop — only legal if the driver has already used two dry compounds
    if not needs_compound_change:
        t = stint_t(current_compound, current_age, remaining)
        if t < best:
            best, best_pits = t, []

    # Effective cost per stop includes execution/traffic risk beyond pit lane time
    stop_cost = pit_loss + STOP_RISK

    # 1-stop
    for pit in range(MIN_STINT, remaining - MIN_STINT + 1):
        for c2 in DRY:
            if c2 == current_compound and (needs_compound_change or current_age < 5):
                continue
            if _hardness(c2) < _hardness(current_compound) and (remaining - pit) > SOFT_SPLASH_MAX:
                continue
            t = stint_t(current_compound, current_age, pit) + stop_cost + stint_t(c2, 0, remaining - pit)
            if t < best:
                best, best_pits = t, [PitPlan(current_lap + pit, c2)]

    # 2-stop
    for p1 in range(MIN_STINT, remaining - 2*MIN_STINT + 1, 2):
        for p2 in range(MIN_STINT, remaining - p1 - MIN_STINT + 1, 2):
            r3 = remaining - p1 - p2
            if r3 < MIN_STINT:
                continue
            for c2 in DRY:
                for c3 in DRY:
                    if needs_compound_change and c2 == current_compound and c3 == current_compound:
                        continue
                    if _hardness(c3) < _hardness(c2) and r3 > SOFT_SPLASH_MAX:
                        continue
                    t = (stint_t(current_compound, current_age, p1) + stop_cost
                         + stint_t(c2, 0, p2) + stop_cost
                         + stint_t(c3, 0, r3))
                    if t < best:
                        best = t
                        best_pits = [PitPlan(current_lap + p1, c2),
                                     PitPlan(current_lap + p1 + p2, c3)]

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

def simulate_race(
    drivers_sorted: list[dict],
    current_lap:    int,
    total_laps:     int,
    curves:         dict[str, DegCurve],
    pace_model:     dict[int, DriverPace],
    sc_events:      list[SCEvent],
    pit_loss:       float = PIT_LOSS,
    track_position_weight: float = 0.6,
) -> list[DriverForecast]:
    """
    track_position_weight: how much current position (gap) influences the
    final predicted order vs pure pace simulation (0=pure pace, 1=pure position).
    At Monaco ~0.8 (almost impossible to overtake without pit stop).
    On normal circuits ~0.4–0.5.
    """
    if total_laps <= current_lap:
        return []

    baselines = [c.baseline for c in curves.values() if c.baseline > 0]
    field_baseline = statistics.median(baselines) if baselines else 85.0

    # Build cumulative gaps by chaining intervals down the running order.
    # gap_to_leader saturates at '+1 LAP' for lapped drivers, which would give
    # every lapped driver the same gap — interval chaining preserves their
    # true relative spacing.
    active = [d for d in drivers_sorted if not d.get("retired")]
    cumulative_gaps: dict[int, float] = {}
    running = 0.0
    for i, d in enumerate(active):
        if i > 0:
            chained = running + _parse_gap(d.get("interval"), field_baseline)
            direct  = _parse_gap(d.get("gap_to_leader"), field_baseline)
            # direct is exact for unlapped drivers; for lapped drivers it
            # saturates at N×lap_time which acts as a lower bound. The
            # chained interval misses lap boundaries. Take the max of both.
            running = max(chained, direct)
        cumulative_gaps[d["driver_number"]] = running

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

        # Active SC: pit lane loss is roughly halved (field bunched, slow laps).
        # If an SC is running on the current lap, evaluate strategy with the
        # discounted pit loss — makes "pit now under SC" win when it should.
        sc_active = any(ev.start_lap <= current_lap <= ev.end_lap + 1 for ev in sc_events)
        effective_pit_loss = pit_loss * 0.45 if sc_active else pit_loss

        strat = optimize_strategy(current_lap, total_laps, compound, age,
                                  pd, curves, field_baseline, effective_pit_loss,
                                  needs_compound_change=needs_change)
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
        # Position-only estimate: assume everyone runs at the same absolute pace,
        # so the finishing order == the current order, gaps are gap_s.
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
                    sc_events, field_baseline, pit_loss,
                    circuit_street=track_position_weight >= 0.7)

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
    circuit_street: bool = False,
) -> None:
    """
    Perturb each driver's deterministic finish time with:
      1. Pace noise        — gaussian, scaled by their pace_std proxy
      2. SC lottery        — if a random SC falls in the remaining laps,
                             drivers who haven't pitted yet gain ~half the
                             pit loss (cheap stop), others lose nothing
      3. Reliability/error — small chance (~2% per driver) of a big loss

    Mutates forecasts in place with win/podium/points probabilities and
    P5–P95 position range.
    """
    import random

    if not scored:
        return

    remaining = total_laps - current_lap
    sc_rate   = SC_RATE_STREET if circuit_street else SC_RATE_DEFAULT
    p_sc      = 1 - (1 - sc_rate) ** max(0, remaining)

    base_times = {fc.driver_number: ft for ft, fc in scored}
    has_stop_planned = {
        fc.driver_number: len(fc.strategy.pits_remaining) > 0 for _, fc in scored
    }

    # Pace noise: traffic, tyre warm-up, small mistakes, weather drift.
    # ~0.4s/√lap gives ±2s over 25 laps, ±3.5s over 70 — roughly matches
    # how much real race gaps wander lap to lap
    sigma = 0.4 * (remaining ** 0.5)

    finish_counts: dict[int, list[int]] = {fc.driver_number: [] for fc in forecasts}

    for _ in range(n_runs):
        run_times = []
        sc_happens = random.random() < p_sc
        for fc in forecasts:
            t = base_times[fc.driver_number]
            t += random.gauss(0, sigma)
            if sc_happens and has_stop_planned[fc.driver_number]:
                # Free-ish pit stop under SC: refund ~60% of pit loss
                t -= pit_loss * 0.6
            if random.random() < 0.02:
                t += random.uniform(20, 80)   # incident / slow stop / damage
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
