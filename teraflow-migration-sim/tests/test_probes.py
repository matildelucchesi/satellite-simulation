import unittest
from src.probes import ping_observations, summarize_ping


class ProbeTests(unittest.TestCase):
    def test_late_reply_supersedes_pending_but_not_real_loss(self):
        rows = ping_observations('[1.0] no answer yet for icmp_seq=1\n'
                                 '[1.1] 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.12 ms\n'
                                 '[1.2] no answer yet for icmp_seq=2\n')
        summary = summarize_ping(rows)
        self.assertEqual(summary['lost_probes'], 1)
        self.assertEqual(summary['loss_fraction'], .5)

    def test_sequence_gap_prevents_false_recovery(self):
        rows = [{'sequence': 1, 'unix_s': 1., 'success': False, 'rtt_ms': None}]
        rows += [{'sequence': seq, 'unix_s': float(seq), 'success': True, 'rtt_ms': 1.}
                 for seq in (2, 3, 5, 6, 7)]
        summary = summarize_ping(rows, stable_successes=3, baseline_path_available=True)
        self.assertEqual(summary['stable_recovery_unix_s'], 7.)
        self.assertEqual(summary['longest_consecutive_successes'], 3)
        self.assertEqual(summary['time_to_stable_recovery_s'], 6.)
        self.assertIsNone(summarize_ping(rows, stable_successes=3,
                         baseline_path_available=False)['time_to_stable_recovery_s'])

    def test_empty_observation_is_not_continuity(self):
        summary = summarize_ping([])
        self.assertFalse(summary['continuous_during_observation'])
        self.assertIsNone(summary['loss_fraction'])
