"""
Unit tests for data/recalibrator.py's background job wiring. The actual
calibration logic is tested in test_undercut_calibration.py and
test_restart_calibration.py -- these just check the loop calls both and
survives either one failing, no real network/threads. Both calibrations
must always be mocked here: leaving either real means a full historical
OpenF1 backfill runs inline during the test (confirmed the hard way --
the restart calibration alone took ~100s for a first, uncached run).
"""
import data.recalibrator as recal


class TestRecalibrateOnce:
    def test_calls_both_run_incremental_calibrations(self, monkeypatch):
        calls = []
        monkeypatch.setattr("engine.undercut_calibration.run_incremental_calibration",
                            lambda: calls.append("undercut"))
        monkeypatch.setattr("engine.restart_calibration.run_incremental_calibration",
                            lambda: calls.append("restart"))
        recal._recalibrate_once()
        assert calls == ["undercut", "restart"]

    def test_undercut_failure_does_not_block_restart(self, monkeypatch):
        def boom():
            raise ConnectionError("openf1 down")
        calls = []
        monkeypatch.setattr("engine.undercut_calibration.run_incremental_calibration", boom)
        monkeypatch.setattr("engine.restart_calibration.run_incremental_calibration",
                            lambda: calls.append("restart"))
        recal._recalibrate_once()   # must not raise
        assert calls == ["restart"]   # restart still ran despite undercut's failure

    def test_restart_failure_does_not_block_undercut(self, monkeypatch):
        def boom():
            raise ConnectionError("openf1 down")
        calls = []
        monkeypatch.setattr("engine.undercut_calibration.run_incremental_calibration",
                            lambda: calls.append("undercut"))
        monkeypatch.setattr("engine.restart_calibration.run_incremental_calibration", boom)
        recal._recalibrate_once()   # must not raise
        assert calls == ["undercut"]
