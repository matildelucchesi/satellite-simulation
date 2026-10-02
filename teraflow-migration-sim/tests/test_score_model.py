import unittest

from src.score_model import CandidateMetrics, score_candidates


class ScoreModelTests(unittest.TestCase):
    def test_weights_and_utilities_produce_ordered_scores(self):
        rows = score_candidates([
            CandidateMetrics(10, 10, 8, 10, 1800, 900, .70, .65, .75, 900),
            CandidateMetrics(11, 30, 5, 10, 300, 900, .60, .55, .70, 1200),
        ])
        self.assertEqual(rows[0]["satellite_id"], 10)
        self.assertGreater(rows[0]["score"], rows[1]["score"])
        self.assertAlmostEqual(sum((.35, .30, .20, .15)), 1.0)

    def test_reserve_violation_excludes_candidate(self):
        rows = score_candidates([
            CandidateMetrics(10, 10, 8, 10, 1800, 900, .19, .70, .70, 900),
            CandidateMetrics(11, 30, 5, 10, 300, 900, .60, .55, .70, 1200),
        ])
        self.assertEqual([r["satellite_id"] for r in rows], [11])

    def test_equal_latency_is_defined_and_ties_are_deterministic(self):
        rows = score_candidates([
            CandidateMetrics(12, 10, 5, 10, 900, 900, .60, .60, .60, 1000),
            CandidateMetrics(11, 10, 5, 10, 900, 900, .60, .60, .60, 1000),
        ])
        self.assertEqual([r["satellite_id"] for r in rows], [11, 12])
        self.assertEqual(rows[0]["utilities"]["latency"], 1.0)


if __name__ == "__main__":
    unittest.main()
