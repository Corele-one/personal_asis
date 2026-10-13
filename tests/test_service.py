import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.service import daemon, install


class ServiceTests(unittest.TestCase):
    def test_install_recovers_from_transient_bootstrap_failure(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            home = base / "runtime"
            home.mkdir()
            (home / "sources.yaml").write_text(json.dumps({"node_id": "mac", "sources": [
                {"id": "test", "root": str(base / "source"), "policy": "private"}]}))
            responses = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 5),
                         subprocess.CompletedProcess([], 0)]
            with patch("personal_asis.service.sys.platform", "darwin"), \
                 patch("personal_asis.service.Path.home", return_value=base), \
                 patch("personal_asis.service.subprocess.run", side_effect=responses) as run, \
                 patch("personal_asis.service.time.sleep"):
                result = install(home)
            self.assertTrue(Path(result["plist"]).exists())
            self.assertEqual(run.call_count, 3)

    def run_loop(self, interval=21600, sleep_jump=0, reports=None):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            (home / "sources.yaml").write_text(json.dumps({"node_id": "mac", "sources": [
                {"id": "test", "root": name, "policy": "private"}]}))
            handlers = {}
            clock = {"wall": 1000, "mono": 0, "sleeps": 0}
            events = []
            reports = reports or [{"sources": [{"status": "ready"}]}] * 2
            times = []
            def emit(event):
                events.append(event)
                times.append(clock["mono"])
                if len(events) == 2:
                    handlers[signal.SIGTERM]()
            def sleep(_):
                clock["wall"] += 1 + (sleep_jump if clock["sleeps"] == 0 else 0)
                clock["mono"] += 1
                clock["sleeps"] += 1
                if clock["sleeps"] > 300:
                    self.fail("daemon did not reconcile on schedule")
            with patch("personal_asis.service.signal.signal", side_effect=lambda sig, cb: handlers.update({sig: cb})), \
                 patch("personal_asis.service.time.time", side_effect=lambda: clock["wall"]), \
                 patch("personal_asis.service.time.monotonic", side_effect=lambda: clock["mono"]), \
                 patch("personal_asis.service.time.sleep", side_effect=sleep), \
                 patch("personal_asis.service.Index") as index:
                index.return_value.__enter__.return_value.reconcile.side_effect = reports
                daemon(home, emit, interval=interval, tick=30)
            return events, times

    def test_startup_and_interval_reconciliation(self):
        events, times = self.run_loop(interval=60)
        self.assertEqual(times, [0, 60])
        self.assertTrue(all(e["event"] == "reconcile" for e in events))

    def test_sleep_wake_reconciles_before_six_hour_deadline(self):
        _, times = self.run_loop(sleep_jump=3600)
        self.assertEqual(times, [0, 30])

    def test_unavailable_source_retries_after_one_minute(self):
        _, times = self.run_loop(reports=[{"sources": [{"status": "unavailable_or_unreadable"}]},
                                         {"sources": [{"status": "ready"}]}])
        self.assertEqual(times, [0, 60])


if __name__ == "__main__":
    unittest.main()
