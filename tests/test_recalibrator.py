"""
Unit tests for data/recalibrator.py's background job wiring. The actual
calibration logic is tested in test_undercut_calibration.py,
test_restart_calibration.py, and test_overtake_calibration.py -- these
just check the loop calls all three and survives any one failing, no
real network/threads. All three calibrations must always be mocked
here: leaving any one real means a full historical OpenF1 backfill runs
inline during the test (confirmed the hard way -- the restart
calibration alone took ~100s for a first, uncached run).
"""
import data.recalibrator as recal


def _mock_all(monkeypatch, calls, *, undercut=None, restart=None, overtake=None):
    monkeypatch.setattr("engine.undercut_calibration.run_incremental_calibration",
                        undercut or (lambda: calls.append("undercut")))
    monkeypatch.setattr("engine.restart_calibration.run_incremental_calibration",
                        restart or (lambda: calls.append("restart")))
    monkeypatch.setattr("engine.overtake_calibration.run_incremental_calibration",
                        overtake or (lambda: calls.append("overtake")))


class TestRecalibrateOnce:
    def test_calls_all_three_run_incremental_calibrations(self, monkeypatch):
        calls = []
        _mock_all(monkeypatch, calls)
        recal._recalibrate_once()
        assert calls == ["undercut", "restart", "overtake"]

    def test_undercut_failure_does_not_block_the_others(self, monkeypatch):
        def boom():
            raise ConnectionError("openf1 down")
        calls = []
        _mock_all(monkeypatch, calls, undercut=boom)
        recal._recalibrate_once()   # must not raise
        assert calls == ["restart", "overtake"]

    def test_restart_failure_does_not_block_the_others(self, monkeypatch):
        def boom():
            raise ConnectionError("openf1 down")
        calls = []
        _mock_all(monkeypatch, calls, restart=boom)
        recal._recalibrate_once()   # must not raise
        assert calls == ["undercut", "overtake"]

    def test_overtake_failure_does_not_block_the_others(self, monkeypatch):
        def boom():
            raise ConnectionError("openf1 down")
        calls = []
        _mock_all(monkeypatch, calls, overtake=boom)
        recal._recalibrate_once()   # must not raise
        assert calls == ["undercut", "restart"]
