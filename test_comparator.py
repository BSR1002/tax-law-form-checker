import unittest
from comparator import compare_texts


class ComparatorTests(unittest.TestCase):
    def test_insert_delete_replace_and_short_changes(self):
        for old, new, kind in [("가나", "가다나", "insert"), ("가다나", "가나", "delete"),
                               ("번호④", "번호⑤", "replace")]:
            with self.subTest(kind=kind):
                result = compare_texts(old, new)
                self.assertEqual(result["change_count"], 1)
                self.assertEqual(result["changes"][0]["type"], kind)

    def test_whitespace_only_is_equal(self):
        self.assertEqual(compare_texts("가 나\n1", "가나1")["changes"], [])

    def test_header_exclusion_is_auditable(self):
        result = compare_texts("■법인세법본문", "본문", "법인세법")
        self.assertEqual(result["change_count"], 0)
        self.assertEqual(result["excluded_changes"][0]["reason"], "law_header_removed")

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            compare_texts(" ", "가")

    def test_repeated_text_keeps_number_changes(self):
        result = compare_texts("가" * 250 + "④끝", "가" * 250 + "⑤끝")
        self.assertEqual(result["changes"][0]["old"], "④")
        self.assertEqual(result["changes"][0]["new"], "⑤")


if __name__ == "__main__":
    unittest.main()
