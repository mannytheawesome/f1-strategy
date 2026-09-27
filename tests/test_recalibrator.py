"""
Unit tests for data/recalibrator.py's background job wiring. The actual
calibration logic is tested in test_undercut_calibration.py -- these just
check the loop calls it and survives a failure, no real network/threads.
"""
import data.recalibrator as recal


class TestRecalibrateOnce:
    def test_calls_run_incremental_calibration(self, monkeypatch):
        calls = []
        monkeypatch.setattr("engine.undercut_calibration.run_incremental_calibration",
                            lambda: calls.append(1))
        recal._recalibrate_once()
        assert calls == [1]

    def test_exception_is_swallowed_not_raised(self, monkeypatch):
        def boom():
            raise ConnectionError("openf1 down")
        monkeypatch.setattr("engine.undercut_calibration.run_incremental_calibration", boom)
        recal._recalibrate_once()   # must not raise
