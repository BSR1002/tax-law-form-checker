import copy
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

import scanner
import ui_service
from test_scanner import FakeClient, NEW, OLD, form

APP = str(Path(__file__).with_name("streamlit_app.py"))
LAW = "법인세법 시행규칙"
OTHER = "조세특례제한법 시행규칙"
SECRET = "sentinel-private-oc"


def fake_client():
    client = FakeClient({"1": form("1", "old", "항목④"), "2": form("2")},
                        {"1": form("1", "new", "항목⑤"), "3": form("3")})
    client.session = Mock()
    return client


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = fake_client()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"LAW_OC": SECRET}).start()
        self.dotenv = patch.object(ui_service, "load_dotenv").start()
        self.factory = patch.object(ui_service, "LawClient", return_value=self.client).start()

    def test_histories_uses_exact_entered_name_and_closes_session(self):
        self.client.histories = Mock(return_value=[NEW, OLD])
        self.assertEqual(ui_service.lookup_histories("  " + OTHER + "  "), [NEW, OLD])
        self.client.histories.assert_called_once_with(OTHER)
        self.factory.assert_called_once_with(SECRET)
        self.client.session.close.assert_called_once()
        self.assertFalse(self.dotenv.call_args.kwargs["override"])

    def test_scanner_comparator_integration_for_multiple_laws_no_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "scan_results.json"
            state = Path(folder) / "scan_state.json"
            output.write_text("saved result")
            state.write_text("saved state")
            cwd = os.getcwd()
            try:
                os.chdir(folder)
                with patch.object(scanner, "atomic_json", side_effect=AssertionError("file write")):
                    for name in [LAW, OTHER, "부가가치세법 시행규칙"]:
                        result = ui_service.run_manual(name, NEW, OLD)
                        self.assertEqual(result["law_name"], name)
                        self.assertEqual(result["mode"], "MANUAL")
                        self.assertEqual(result["detail_change_count"], 1)
                        self.assertEqual(len(result["new_forms"]), 1)
                        self.assertEqual(len(result["deleted_forms"]), 1)
                self.assertEqual(output.read_text(), "saved result")
                self.assertEqual(state.read_text(), "saved state")
                self.assertEqual(len(list(Path(folder).iterdir())), 2)
            finally:
                os.chdir(cwd)

    def test_invalid_versions_rejected_before_api(self):
        for current, previous in [(NEW, NEW), (OLD, NEW), (None, OLD),
                                  (dict(NEW, mst="../key"), OLD),
                                  (dict(NEW, effective_date="20261399"), OLD)]:
            with self.subTest(current=current):
                with self.assertRaises(ValueError):
                    ui_service.run_manual(LAW, current, previous)
        self.factory.assert_not_called()

    def test_same_date_different_mst_allowed(self):
        ui_service.validate_versions(NEW, dict(NEW, mst="3"))
        self.assertNotEqual(ui_service.version_label(NEW), ui_service.version_label(dict(NEW, mst="3")))

    def test_blank_law_and_missing_key(self):
        with self.assertRaises(ValueError):
            ui_service.lookup_histories("  ")
        with patch.dict(os.environ, {"LAW_OC": ""}):
            with self.assertRaises(ValueError):
                ui_service.lookup_histories(LAW)
        self.factory.assert_not_called()

    def test_close_on_failure(self):
        self.client.histories = Mock(side_effect=RuntimeError("unavailable"))
        with self.assertRaises(RuntimeError):
            ui_service.lookup_histories(LAW)
        self.client.session.close.assert_called_once()

    def test_current_and_historical_query_paginated(self):
        client = scanner.LawClient("fake")
        self.addCleanup(client.session.close)
        row = {"법령명한글": OTHER, "법령일련번호": "1", "시행일자": "20260102"}
        client.api = Mock(side_effect=[
            {"LawSearch": {"totalCnt": "101", "law": [row, dict(row, 법령명한글=LAW)]}},
            {"LawSearch": {"totalCnt": "101", "law": dict(row, 법령일련번호="2", 시행일자="20260320")}},
        ])
        self.assertEqual(client.histories(OTHER), [NEW, OLD])
        for call in client.api.call_args_list:
            self.assertEqual(call.kwargs["nw"], "1,3")
            self.assertEqual(call.kwargs["query"], OTHER)


class UITests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"LAW_OC": SECRET}).start()
        patch.object(ui_service, "load_dotenv").start()
        self.client = fake_client()
        patch.object(ui_service, "LawClient", return_value=self.client).start()
        self.app = AppTest.from_file(APP, default_timeout=20)

    def manual(self):
        self.app.run()
        self.app.radio(key="result_source").set_value("법령·버전 선택 후 실행").run()
        return self.app

    def lookup(self):
        app = self.manual()
        app.button(key="lookup").click().run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_saved_ui_four_tabs_and_no_api(self):
        data = ui_service.run_manual(LAW, NEW, OLD)
        self.client.calls.clear()
        with patch.object(Path, "read_text", return_value=json.dumps(data)):
            app = self.app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.tabs), 4)
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(self.client.calls, [])

    def test_missing_saved_result_still_allows_manual(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.app.run()
        self.assertTrue(self.app.warning)
        self.app.radio(key="result_source").set_value("법령·버전 선택 후 실행").run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(self.app.button(key="lookup"))

    def test_corrupt_saved_result(self):
        with patch.object(Path, "read_text", return_value="not json"):
            self.app.run()
        self.assertTrue(self.app.error)
        self.assertFalse(self.app.exception)

    def test_lookup_select_run_renders_existing_tabs_and_table(self):
        app = self.lookup()
        self.assertIn("MST 2", app.selectbox(key="current_version").options[0])
        app.button(key="run_scan").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 4)
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.session_state["manual_result"]["current"], NEW)
        self.assertEqual(app.session_state["manual_result"]["previous"], OLD)
        app.text_input(key="changed_search").set_value("존재하지않는서식").run()
        self.assertEqual(len(app.dataframe), 0)

    def test_law_change_clears_versions_and_previous_result(self):
        app = self.lookup()
        app.button(key="run_scan").click().run()
        app.text_input(key="law_name").set_value(OTHER).run()
        self.assertNotIn("manual_result", app.session_state)
        self.assertEqual(len(app.selectbox), 0)
        app.button(key="lookup").click().run()
        app.button(key="run_scan").click().run()
        self.assertEqual(app.session_state["manual_result"]["law_name"], OTHER)

    def test_same_or_reversed_versions_disable_run_and_clear_result(self):
        app = self.lookup()
        app.button(key="run_scan").click().run()
        app.selectbox(key="current_version").set_value(1).run()
        self.assertTrue(app.button(key="run_scan").disabled)
        self.assertNotIn("manual_result", app.session_state)
        app.selectbox(key="previous_version").set_value(0).run()
        self.assertTrue(app.button(key="run_scan").disabled)

    def test_insufficient_or_empty_histories(self):
        for revisions in [[NEW], []]:
            with self.subTest(revisions=revisions):
                with patch.object(ui_service, "lookup_histories", return_value=revisions):
                    self.manual().button(key="lookup").click().run()
                self.assertTrue(self.app.warning)
                self.assertFalse(self.app.selectbox)

    def test_failed_refresh_clears_stale_selection_without_secret_output(self):
        app = self.lookup()
        app.button(key="run_scan").click().run()
        captured = StringIO()
        with patch.object(ui_service, "lookup_histories", side_effect=RuntimeError("https://law.go.kr?OC=" + SECRET)):
            with redirect_stdout(captured), redirect_stderr(captured):
                app.button(key="lookup").click().run()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)
        self.assertFalse(app.selectbox)
        self.assertNotIn("manual_result", app.session_state)
        self.assertNotIn(SECRET, captured.getvalue() + str(app))

    def test_scan_failure_has_no_secret_or_stale_result(self):
        app = self.lookup()
        app.button(key="run_scan").click().run()
        captured = StringIO()
        with patch.object(ui_service, "run_manual", side_effect=RuntimeError("OC=" + SECRET)):
            with redirect_stdout(captured), redirect_stderr(captured):
                app.button(key="run_scan").click().run()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)
        self.assertNotIn("manual_result", app.session_state)
        self.assertNotIn(SECRET, captured.getvalue() + str(app))

    def test_partial_result_visible_in_review_tab(self):
        self.client.data["2"]["1"]["hwp_url"] = "FAIL"
        app = self.lookup()
        app.button(key="run_scan").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["manual_result"]["status"], "partial")
        self.assertEqual(app.tabs[3].label, "확인 필요 1")
        self.assertTrue(app.warning)

    def test_independent_sessions(self):
        app = self.lookup()
        app.button(key="run_scan").click().run()
        another = AppTest.from_file(APP).run()
        another.radio(key="result_source").set_value("법령·버전 선택 후 실행").run()
        self.assertNotIn("manual_result", another.session_state)
        self.assertNotIn("histories", another.session_state)
        self.assertIn("manual_result", app.session_state)


if __name__ == "__main__":
    unittest.main()
