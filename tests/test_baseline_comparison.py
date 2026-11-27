import unittest
from datetime import datetime, timedelta, timezone

from fx_research.compare_baseline_methods import (
    compare_baseline_methods,
    summarize_comparison,
)


class BaselineComparisonTests(unittest.TestCase):
    def test_compares_full_288_returns_with_previous_24_hours(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        returns = []
        for index in range(288):
            value = 0.02 if index < 144 else 0.01
            returns.append((
                start + timedelta(minutes=10 * index),
                value,
                "UP",
            ))
        returns.append((
            start + timedelta(minutes=10 * 288),
            0.04,
            "UP",
        ))

        results = compare_baseline_methods(returns)
        latest = results[-1]

        self.assertEqual(latest["a_sample_count"], 288)
        self.assertAlmostEqual(latest["a_baseline_pct"], 0.015)
        self.assertAlmostEqual(latest["a_coverage_hours"], 48.0)
        self.assertEqual(latest["b_sample_count"], 144)
        self.assertAlmostEqual(latest["b_baseline_pct"], 0.01)
        self.assertFalse(latest["a_alert"])
        self.assertTrue(latest["b_alert"])

        summary = summarize_comparison(results)
        self.assertGreater(summary["both_available_count"], 0)
        self.assertGreater(summary["disagreement_count"], 0)

    def test_a_requires_all_288_but_b_requires_30_samples(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        returns = [
            (
                start + timedelta(minutes=5 * index),
                0.01,
                "UP",
            )
            for index in range(40)
        ]
        results = compare_baseline_methods(returns)
        latest = results[-1]

        self.assertIsNone(latest["a_alert"])
        self.assertEqual(latest["a_sample_count"], 39)
        self.assertTrue(latest["b_alert"])
        self.assertEqual(latest["b_sample_count"], 39)

    def test_time_method_is_unavailable_below_30_samples(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        returns = [
            (
                start + timedelta(minutes=5 * index),
                0.01,
                "UP",
            )
            for index in range(20)
        ]
        results = compare_baseline_methods(returns)
        latest = results[-1]

        self.assertIsNone(latest["a_alert"])
        self.assertIsNone(latest["b_alert"])
        self.assertEqual(latest["b_sample_count"], 19)


if __name__ == "__main__":
    unittest.main()
