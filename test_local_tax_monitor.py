import unittest
from datetime import date
from unittest.mock import Mock

import local_tax_monitor as m


class LocalTaxTests(unittest.TestCase):
    def test_header_date_and_missing_date(self):
        self.assertEqual(m.revision_date('■지방세법시행규칙[별지제43호서식]<개정2026.5.1.>'), m.SINCE)
        with self.assertRaises(ValueError):
            m.revision_date('신고기간2026.5.1.')

    def test_scope_cutoff_and_future_revision(self):
        client = Mock()
        client.histories.return_value = [{'effective_date': '20270101', 'mst': '3'}, {'effective_date': '20260701', 'mst': '2'}]
        client.forms.return_value = {key: {'title': key, 'number': key[:4], 'branch_number': key[5:], 'pdf_url': '/form.pdf', 'hwp_url': '/form.hwp'} for key in m.FORM_KEYS}
        client.forms.return_value['9999:00'] = {'title': 'unrelated'}
        client.pdf_text.return_value = '<개정2026.5.1.>'
        client.hwp_hash.return_value = 'hash'
        result = m.check(client, date(2026, 11, 24))
        self.assertEqual(result['current']['mst'], '2')
        self.assertEqual(result['changed_count'], 11)
        self.assertEqual(client.pdf_text.call_count, 11)
        client.pdf_text.return_value = '<개정2026.4.30.>'
        client.hwp_hash.reset_mock()
        self.assertEqual(m.check(client, date(2026, 11, 24))['changed_count'], 0)
        client.hwp_hash.assert_not_called()

    def test_unreadable_form_requires_review(self):
        client = Mock()
        client.histories.return_value = [{'effective_date': '20260701', 'mst': '2'}]
        client.forms.return_value = {}
        result = m.check(client, date(2026, 11, 24))
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(all(r['status'] == 'review_required' for r in result['forms']))


if __name__ == '__main__':
    unittest.main()
