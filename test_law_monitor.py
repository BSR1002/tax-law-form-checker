import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import law_monitor as m


class MonitorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'state.json'
        self.old = {name: {'effective_date': '20260101', 'mst': '123'} for name in m.LAWS}
        self.client = Mock()
        self.client.histories.side_effect = lambda name: [self.old[name]]
        self.notify = Mock()

    def run_monitor(self):
        return m.run(self.client, self.path, self.notify)

    def seed(self):
        self.path.write_text(json.dumps(self.old), encoding='utf-8')

    def test_baseline_and_unchanged(self):
        self.assertEqual(self.run_monitor(), 'baseline_initialized')
        before = self.path.stat().st_mtime_ns
        self.assertEqual(self.run_monitor(), 'no_changes')
        self.assertEqual(before, self.path.stat().st_mtime_ns)
        self.notify.assert_not_called()
        self.assertEqual({call[0] for call in self.client.method_calls}, {'histories'})

    def test_date_mst_and_multiple_changes(self):
        for updates in ({'effective_date': '20260201'}, {'mst': '124'}):
            for count in (1, 2):
                with self.subTest(updates=updates, count=count):
                    self.seed()
                    current = {name: dict(value) for name, value in self.old.items()}
                    for name in m.LAWS[:count]:
                        current[name].update(updates)
                    self.client.histories.side_effect = lambda name: [current[name]]
                    self.notify.reset_mock()
                    self.assertEqual(self.run_monitor(), 'changes_notified')
                    self.notify.assert_called_once_with(self.old, current)

    def test_failure_preserves_state(self):
        for failed_index in (0, 1, 2):
            self.seed()
            before = self.path.read_bytes()
            self.client.histories.side_effect = [[self.old[m.LAWS[0]]]] * failed_index + [RuntimeError('secret')]
            with self.assertRaises(RuntimeError):
                self.run_monitor()
            self.assertEqual(before, self.path.read_bytes())
            self.notify.assert_not_called()

    def test_notification_failure_preserves_state(self):
        self.seed()
        before = self.path.read_bytes()
        self.client.histories.side_effect = lambda name: [{'effective_date': '20260201', 'mst': '124'}]
        self.notify.side_effect = RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            self.run_monitor()
        self.assertEqual(before, self.path.read_bytes())

    def test_secret_not_logged(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'LAW_OC': 'private-OC'}), patch.object(m, 'LawClient', side_effect=RuntimeError('private-OC')), contextlib.redirect_stdout(output):
            self.assertEqual(m.main(), 1)
        self.assertNotIn('private-OC', output.getvalue())

    def test_issue_retry_deduplicates_closed_issue(self):
        session = Mock()
        session.get.return_value.json.return_value = []
        current = {name: dict(value, mst='124') for name, value in self.old.items()}
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'token', 'GITHUB_REPOSITORY': 'owner/repo'}), patch.object(m.requests, 'Session', return_value=session):
            m.notify(self.old, current)
            body = session.post.call_args.kwargs['json']['body']
            session.get.return_value.json.return_value = [{'body': body, 'state': 'closed'}]
            m.notify(self.old, current)
        session.post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
