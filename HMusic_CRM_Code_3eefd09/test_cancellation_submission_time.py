"""Submission-time policy tests; no production access or notifications."""
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch
import os
import time
import unittest
from test_parent_cancellation_notifications import load


class SubmissionPolicyTest(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo('America/Los_Angeles')
        self.scope = dict(datetime=datetime, HMUSIC_TIMEZONE=self.zone,
                          hmusic_now=Mock(return_value=datetime(2026, 11, 21, 23, 48, tzinfo=self.zone)))
        for name in ('get_parent_cancel_status', 'hmusic_cancellation_submission_time',
                     'hmusic_cancellation_request_policy'):
            load(name, self.scope)

    def test_no_show_preview_describes_full_tuition_not_free(self):
        self.scope['hmusic_money'] = lambda amount: f'{amount:.2f}'
        load('hmusic_cancellation_charge_preview', self.scope)
        preview = self.scope['hmusic_cancellation_charge_preview']
        self.assertEqual(preview('no_show', 0), '1 lesson credit · 100% tuition; no extra fee')
        self.assertIn('policy waiver available', preview('no_show', 0, True))
        self.assertEqual(preview('last_min_cancel', 15), '$15.00 extra fee')

    def test_early_submission_stays_free_despite_late_review(self):
        policy = self.scope['hmusic_cancellation_request_policy']
        self.assertEqual(policy('2026-11-22', '11:45', '2026-11-21T10:51:00-08:00',
                                'last_min_cancel'), 'excused_24h')
        self.scope['hmusic_now'].assert_not_called()

    def test_legacy_server_utc_timestamp_matches_screenshot(self):
        with patch.dict(os.environ, {'TZ': 'UTC'}):
            time.tzset()
            try:
                policy = self.scope['hmusic_cancellation_request_policy']
                self.assertEqual(policy('2026-11-22', '11:45', '2026-11-21 18:51',
                                        'last_min_cancel'), 'excused_24h')
                shown = self.scope['hmusic_cancellation_submission_time']('2026-11-21 18:51')
                self.assertEqual(shown.strftime('%H:%M %Z'), '10:51 PST')
            finally:
                pass
        time.tzset()

    def test_exact_boundaries_and_actual_late_requests(self):
        policy = self.scope['hmusic_cancellation_request_policy']
        for submitted, expected in (
            ('2026-11-21T11:45:00-08:00', 'excused_24h'),
            ('2026-11-21T11:45:01-08:00', 'last_min_cancel'),
            ('2026-11-22T10:45:00-08:00', 'last_min_cancel'),
            ('2026-11-22T10:45:01-08:00', 'no_show'),
        ):
            with self.subTest(submitted=submitted):
                self.assertEqual(policy('2026-11-22', '11:45', submitted, 'scheduled'), expected)

    def test_daylight_saving_uses_elapsed_hours(self):
        # Fall-back makes these school wall times 24.5 elapsed hours apart.
        self.assertEqual(self.scope['get_parent_cancel_status'](
            '2026-11-01', '11:45', datetime.fromisoformat('2026-10-31T12:15:00-07:00')),
            'excused_24h')

    def test_missing_timestamp_preserves_evidence_not_review_clock(self):
        self.assertEqual(self.scope['hmusic_cancellation_request_policy'](
            '2026-11-22', '11:45', None, 'excused_24h'), 'excused_24h')
        self.scope['hmusic_now'].assert_not_called()

    def test_new_submission_uses_school_clock_by_default(self):
        self.scope['hmusic_now'].return_value = datetime(2026, 11, 21, 10, 51, tzinfo=self.zone)
        self.assertEqual(self.scope['get_parent_cancel_status']('2026-11-22', '11:45'), 'excused_24h')


if __name__ == '__main__':
    unittest.main()
