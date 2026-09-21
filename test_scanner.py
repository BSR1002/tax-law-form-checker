import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scanner

OLD = {"mst": "1", "effective_date": "20260102"}
NEW = {"mst": "2", "effective_date": "20260320"}


def form(number, hwp="same", pdf="same"):
    return {"number": number, "branch_number": "00", "title": "서식",
            "effective_date": "", "hwp_url": hwp, "pdf_url": pdf}


class FakeClient:
    def __init__(self, old, new):
        self.data = {"1": old, "2": new}
        self.calls = []

    def histories(self, name):
        self.calls.append("histories")
        return [NEW, OLD]

    def forms(self, rev):
        self.calls.append("forms:" + rev["mst"])
        return copy.deepcopy(self.data[rev["mst"]])

    def hwp_hash(self, f):
        self.calls.append("hwp:" + f["hwp_url"])
        if f["hwp_url"] == "FAIL":
            raise ValueError("bad file")
        return f["hwp_url"]

    def pdf_hash(self, f):
        self.calls.append("pdf:" + f["pdf_url"])
        if f["pdf_url"] == "FAIL":
            raise ValueError("unreadable")
        return hashlib.sha256(scanner.compact(f["pdf_url"]).encode("utf-8")).hexdigest()

    def pdf_text(self, f):
        self.calls.append("text:" + f["pdf_url"])
        return scanner.compact(f["pdf_url"])


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "scan_results.json"
        self.state = Path(self.temp.name) / "scan_state.json"

    def run_scan(self, client, mode="MANUAL"):
        return scanner.run(client, "법인세법 시행규칙", mode, self.output, self.state,
                           NEW, OLD, progress=None)

    def test_all_forms_and_pdf_only_for_changed_hwp(self):
        old = {str(i): form(str(i)) for i in range(1, 6)}
        new = copy.deepcopy(old)
        new["2"]["hwp_url"] = "different"
        new["3"].update(hwp_url="changed", pdf_url="text changed")
        del new["5"]
        new["6"] = form("6")
        client = FakeClient(old, new)
        result = self.run_scan(client)
        self.assertEqual([f["number"] for f in result["changed_forms"]], ["3"])
        self.assertEqual(result["unchanged_count"], 3)
        self.assertEqual(len(result["new_forms"]), 1)
        self.assertEqual(len(result["deleted_forms"]), 1)
        self.assertEqual(sum(c.startswith("pdf:") for c in client.calls), 4)
        self.assertEqual(sum(c.startswith("hwp:") for c in client.calls), 9)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), result)
        self.assertFalse(self.state.exists())

    def test_auto_baseline_and_skip(self):
        client = FakeClient({}, {"1": form("1")})
        result = self.run_scan(client, "AUTO")
        self.assertEqual(result["status"], "baseline_initialized")
        self.assertEqual(result["new_forms"], [])
        self.assertEqual(result["baseline_count"], 1)
        client.calls.clear()
        result = self.run_scan(client, "AUTO")
        self.assertEqual(result["status"], "no_new_revision")
        self.assertEqual(client.calls, ["histories"])

    def test_auto_reuses_old_hash_and_preserves_state_on_failure(self):
        old = {"1": form("1")}
        state = {"schema_version": 1, "law_name": "법인세법 시행규칙",
                 "current": OLD, "forms": copy.deepcopy(old)}
        state["forms"]["1"]["hwp_sha256"] = "same"
        scanner.atomic_json(self.state, state)
        before = self.state.read_bytes()
        client = FakeClient(old, {"1": form("1", "changed", "FAIL"), "2": form("2", "new")})
        result = self.run_scan(client, "AUTO")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.state.read_bytes(), before)
        self.assertNotIn("forms:1", client.calls)
        self.assertNotIn("hwp:same", client.calls)
        self.assertEqual(len(result["new_forms"]), 1)

    def test_failures_are_not_unchanged(self):
        result = self.run_scan(FakeClient({"1": form("1")}, {"1": form("1", "FAIL")}))
        self.assertEqual(result["unchanged_count"], 0)
        self.assertEqual(len(result["review_required_forms"]), 1)

    def test_successful_auto_advances_state_and_reuses_pdf_hash(self):
        old = {"1": form("1")}
        old["1"].update(hwp_sha256="old", pdf_text_sha256=hashlib.sha256(b"cached").hexdigest())
        scanner.atomic_json(self.state, {"schema_version": 1, "law_name": "법인세법 시행규칙",
                                        "current": OLD, "forms": old})
        client = FakeClient(old, {"1": form("1", "new", "cached")})
        result = self.run_scan(client, "AUTO")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual([c for c in client.calls if c.startswith("pdf:")], ["pdf:cached"])
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["current"], NEW)

    def test_manual_validation(self):
        for current, previous in [(NEW, NEW), (OLD, NEW), (None, OLD)]:
            with self.assertRaises(ValueError):
                scanner.run(None, "law", "MANUAL", self.output, self.state, current, previous)

    def test_other_law_state_rejected(self):
        scanner.atomic_json(self.state, {"schema_version": 1, "law_name": "other"})
        with self.assertRaises(ValueError):
            self.run_scan(FakeClient({}, {}), "AUTO")

    def test_duplicate_keys_rejected_and_singleton_supported(self):
        client = scanner.LawClient("test")
        unit = {"별표구분": "서식", "별표번호": "3", "별표가지번호": "0"}
        client.api = Mock(return_value={"법령": {"기본정보": {}, "별표": {"별표단위": unit}}})
        self.assertIn("0003:00", client.forms(NEW))
        client.api.return_value["법령"]["별표"]["별표단위"] = [unit, unit]
        with self.assertRaises(ValueError):
            client.forms(NEW)

    def test_search_exact_name_and_pagination(self):
        client = scanner.LawClient("test")
        row = {"법령명한글": "법인세법 시행규칙", "법령일련번호": "1", "시행일자": "20260102"}
        other = dict(row, 법령명한글="다른 법령", 법령일련번호="9")
        client.api = Mock(side_effect=[
            {"LawSearch": {"totalCnt": "101", "law": [row, other]}},
            {"LawSearch": {"totalCnt": "101", "law": dict(row, 법령일련번호="2", 시행일자="20260320")}}])
        self.assertEqual(client.histories("법인세법 시행규칙"), [NEW, OLD])
        self.assertEqual(client.api.call_count, 2)

    def test_bad_download_is_not_hashed(self):
        client = scanner.LawClient("test")
        client.session = Mock()
        client.session.get.return_value.content = b"<html>Error</html>"
        with self.assertRaises(ValueError):
            client.hwp_hash(form("1"))

    def test_pdf_whitespace_and_unreadable(self):
        client = scanner.LawClient("test")
        client.download = Mock(return_value=b"%PDF-test")
        with patch.object(scanner, "PdfReader") as reader:
            page = Mock()
            reader.return_value.pages = [page]
            page.extract_text.return_value = "가 나\n1"
            first = client.pdf_hash(form("1"))
            client.pdf_text_cache.clear()
            page.extract_text.return_value = "가나1"
            self.assertEqual(first, client.pdf_hash(form("1")))
            page.extract_text.return_value = ""
            client.pdf_text_cache.clear()
            with self.assertRaises(ValueError):
                client.pdf_hash(form("1"))

    def test_failed_atomic_write_preserves_existing_file(self):
        scanner.atomic_json(self.output, {"old": True})
        before = self.output.read_bytes()
        with patch.object(scanner.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                scanner.atomic_json(self.output, {"new": True})
        self.assertEqual(before, self.output.read_bytes())
        self.assertEqual(list(self.output.parent.glob("*.tmp")), [])

    def test_detail_changes_saved_and_unchanged_forms_skipped(self):
        client = FakeClient({"1": form("1", "old", "항목④"), "2": form("2")},
                            {"1": form("1", "new", "항목⑤"), "2": form("2")})
        result = self.run_scan(client)
        detail = result["changed_forms"][0]["comparison"]
        self.assertEqual(detail["change_count"], 1)
        self.assertEqual((detail["changes"][0]["old"], detail["changes"][0]["new"]), ("④", "⑤"))
        saved = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(saved["detail_change_count"], 1)
        self.assertEqual([c for c in client.calls if c.startswith("text:")], ["text:항목④", "text:항목⑤"])

    def test_comparator_failure_preserves_auto_state_and_continues(self):
        old = {"1": form("1", "old", "A"), "2": form("2", "old", "C")}
        for f in old.values():
            f["hwp_sha256"] = "old"
        scanner.atomic_json(self.state, {"schema_version": 1, "law_name": "법인세법 시행규칙",
                                        "current": OLD, "forms": old})
        before = self.state.read_bytes()
        client = FakeClient(old, {"1": form("1", "new", "B"), "2": form("2", "new", "D")})
        original = scanner.compare_texts
        def compare(a, b, name):
            if a == "A":
                raise ValueError("comparison error")
            return original(a, b, name)
        with patch.object(scanner, "compare_texts", side_effect=compare):
            result = self.run_scan(client, "AUTO")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["review_required_forms"][0]["failed_stage"], "comparator")
        self.assertEqual(len(result["changed_forms"]), 1)
        self.assertEqual(before, self.state.read_bytes())

    def test_pdf_cache_reused_between_hash_and_comparator(self):
        client = scanner.LawClient("test")
        client.download = Mock(return_value=b"%PDF-test")
        with patch.object(scanner, "PdfReader") as reader:
            page = Mock()
            page.extract_text.return_value = "text"
            reader.return_value.pages = [page]
            client.pdf_hash(form("1"))
            self.assertEqual(client.pdf_text(form("1")), "text")
        self.assertEqual(client.download.call_count, 1)

    def test_stale_previous_pdf_hash_requires_review(self):
        old = {"1": form("1", "old", "modified source")}
        old["1"].update(hwp_sha256="old", pdf_text_sha256=hashlib.sha256(b"original").hexdigest())
        scanner.atomic_json(self.state, {"schema_version": 1, "law_name": "법인세법 시행규칙",
                                        "current": OLD, "forms": old})
        result = self.run_scan(FakeClient(old, {"1": form("1", "new", "new text")}), "AUTO")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["review_required_forms"][0]["failed_stage"], "comparator")


    def test_http_error_is_not_retried(self):
        client = scanner.LawClient("test")
        client.session = Mock()
        client.session.get.return_value.raise_for_status.side_effect = scanner.requests.HTTPError("429")
        with self.assertRaises(scanner.requests.HTTPError):
            client.hwp_hash(form("1"))
        self.assertEqual(client.session.get.call_count, 1)

    def test_current_failure_skips_previous_download_and_cached_hash_reused(self):
        old = {"1": form("1", "skip"), "2": form("2", "cached")}
        old["2"]["hwp_sha256"] = "same"
        client = FakeClient(old, {"1": form("1", "FAIL"), "2": form("2")})
        result, _ = scanner.scan(client, "law", "MANUAL", NEW, OLD, progress=None)
        self.assertNotIn("hwp:skip", client.calls)
        self.assertNotIn("hwp:cached", client.calls)
        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual(result["status"], "partial")

    def test_empty_forms(self):
        result, state = scanner.scan(FakeClient({}, {}), "law", "MANUAL", NEW, OLD, progress=None)
        self.assertEqual(result["current_count"], 0)
        self.assertEqual(state["forms"], {})

if __name__ == "__main__":
    unittest.main()
