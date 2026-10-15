import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import dashboard_monitor as d


class DashboardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = Path(temp.name) / "baseline.json"
        self.feed = Path(temp.name) / "public/monitoring.json"
        self.old = {name: {"effective_date": "20260101", "mst": "123"} for name in d.LAWS}
        self.sleep = Mock()
        self.env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "2"}

    def execute(self, monitor):
        return d.execute(monitor, self.state, self.feed, self.sleep, self.env)

    def load(self):
        return json.loads(self.feed.read_text(encoding="utf-8"))

    def test_bootstrap_does_not_invent_checks(self):
        feed = d.initial_feed(self.old)
        self.assertIsNone(feed["last_checked_at"])
        self.assertIsNone(feed["last_success_at"])
        self.assertEqual(feed["runs"], [])
        self.assertTrue(all(row["status"] == "unverified" for row in feed["laws"]))

    def test_baseline_then_no_change(self):
        def first():
            d.atomic_json(self.state, self.old)
            return "baseline_initialized"
        self.assertEqual(self.execute(first), 0)
        self.assertEqual(self.load()["changes"], [])
        self.assertTrue(all(row["status"] == "baseline_initialized" for row in self.load()["laws"]))
        self.env["GITHUB_RUN_ID"] = "43"
        self.assertEqual(self.execute(lambda: "no_changes"), 0)
        feed = self.load()
        self.assertEqual(len(feed["runs"]), 2)
        self.assertEqual(feed["latest_run"]["changed_count"], 0)
        self.assertTrue(all(row["status"] == "unchanged" for row in feed["laws"]))

    def test_changes_and_failure_preserve_last_good_data(self):
        d.atomic_json(self.state, self.old)
        new = {name: dict(value) for name, value in self.old.items()}
        new[d.LAWS[0]]["mst"] = "124"
        def changed():
            d.atomic_json(self.state, new)
            return "changes_notified"
        self.execute(changed)
        good = self.load()
        self.assertEqual(good["latest_run"]["changed_count"], 1)
        self.assertEqual(good["changes"][0]["previous"], self.old[d.LAWS[0]])
        self.env["GITHUB_RUN_ID"] = "43"
        monitor = Mock(side_effect=RuntimeError("LAW_OC=private-secret https://private.invalid"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(self.execute(monitor), 1)
        failed = self.load()
        self.assertEqual(monitor.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertEqual(failed["last_success_at"], good["last_success_at"])
        self.assertEqual(failed["changes"], good["changes"])
        self.assertIsNone(failed["latest_run"]["changed_count"])
        self.assertEqual(failed["laws"][0]["mst"], "124")
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8")), new)
        self.assertNotIn("private-secret", json.dumps(failed) + output.getvalue())

    def test_retry_success_stops_early_and_sets_output(self):
        d.atomic_json(self.state, self.old)
        output = self.state.with_name("output.txt")
        self.env["GITHUB_OUTPUT"] = str(output)
        monitor = Mock(side_effect=[RuntimeError("secret"), "no_changes"])
        self.assertEqual(self.execute(monitor), 0)
        self.assertEqual(self.load()["latest_run"]["attempts"], 2)
        self.sleep.assert_called_once_with(180)
        self.assertEqual(output.read_text(), "result=success\n")

    def test_failure_without_baseline_and_history_retention(self):
        self.execute(Mock(side_effect=RuntimeError("secret")))
        feed = self.load()
        self.assertIsNone(feed["last_success_at"])
        self.assertTrue(all(row["mst"] is None for row in feed["laws"]))
        feed["runs"].append({"id": "ancient", "checked_at": "2000-01-01T00:00:00+00:00"})
        feed["changes"].append({"id": "ancient:1", "detected_at": "2000-01-01T00:00:00+00:00"})
        result = d.update_feed(feed, None, None, "failed", 3, d.timestamp(), "new", None)
        self.assertFalse(any(row["id"] == "ancient" for row in result["runs"]))
        self.assertEqual(result["changes"], [])

    def test_invalid_feed_is_not_overwritten(self):
        self.feed.parent.mkdir()
        self.feed.write_text('{"schema_version":99}')
        monitor = Mock()
        with self.assertRaises(ValueError):
            self.execute(monitor)
        monitor.assert_not_called()
        self.assertEqual(self.feed.read_text(), '{"schema_version":99}')


if __name__ == "__main__":
    unittest.main()
