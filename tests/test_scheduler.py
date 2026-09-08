import tempfile
import unittest
from pathlib import Path

from backend.engine import Engine
from backend.market import FixtureMarket


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.now_ref = [1800000000]
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3", clock=lambda: self.now_ref[0],
                             market=FixtureMarket())

    def test_upsert_and_list_schedule(self):
        s = self.engine.upsert_schedule({
            "report_type": "daily",
            "local_time": "09:00",
            "timezone": "Africa/Kampala",
            "enabled": True,
        })
        self.assertIn("id", s)
        schedules = self.engine.list_schedules()
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0]["report_type"], "daily")

    def test_schedule_can_be_paused(self):
        s = self.engine.upsert_schedule({
            "report_type": "daily",
            "local_time": "09:00",
            "timezone": "Africa/Kampala",
            "enabled": True,
        })
        self.engine.pause_schedule(s["id"])
        paused = self.engine.list_schedules()[0]
        self.assertFalse(paused["enabled"])

    def test_run_due_schedules_generates_report(self):
        s = self.engine.upsert_schedule({
            "report_type": "daily",
            "local_time": "12:00",
            "timezone": "Africa/Kampala",
            "enabled": True,
        })
        # Advance clock past the 12:00 Kampala target.
        self.now_ref[0] += 4000
        result = self.engine.run_due_schedules()
        self.assertIsInstance(result, list)
        self.assertIsNotNone(self.engine.list_schedules()[0]["last_run"])


if __name__ == "__main__":
    unittest.main()
