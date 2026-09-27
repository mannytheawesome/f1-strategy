"""
Background job that keeps engine/undercut_shift.py's per-circuit numbers
current without anyone re-running a script by hand.

User asked directly: "automatic recalibration." Before this, the
undercut-shift calibration was a one-off, manually-run script whose
output got hand-copied into a hardcoded dict -- accurate the day it ran,
frozen after that. This thread periodically calls
engine.undercut_calibration.run_incremental_calibration(), which only
ever evaluates races that weren't already in its persisted cache (a
newly-completed race since the last run), then writes the refreshed
per-circuit table to the same persisted location undercut_shift_for()
reads from.

Runs in its own daemon thread for the life of the process (same pattern
as data/warmer.py), started from api/main.py's FastAPI lifespan hook.
Deliberately infrequent (once a day): the underlying calibration touches
every circuit's degradation-curve + strategy-search path, which is not
free, and races complete at most a few times a week -- there's nothing
new to find by checking more often than that.
"""
import threading
import time

RECALIBRATION_INTERVAL_S = 24 * 3600   # once a day is plenty -- races
                                        # complete at most a few times a week


def _recalibrate_once() -> None:
    from engine.undercut_calibration import run_incremental_calibration
    try:
        run_incremental_calibration()
    except Exception:
        pass   # OpenF1 hiccup or similar -- try again on the next tick


def recalibration_loop() -> None:
    while True:
        _recalibrate_once()
        time.sleep(RECALIBRATION_INTERVAL_S)


def start_background_recalibrator() -> None:
    threading.Thread(target=recalibration_loop, daemon=True,
                     name="undercut-recalibrator").start()
