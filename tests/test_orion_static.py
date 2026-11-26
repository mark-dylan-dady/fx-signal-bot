import math
import unittest
from datetime import datetime, timedelta, timezone

from fx_research.detect_market_changes import is_valid_price as detect_price_is_valid
from fx_research.report_pre_alert_market_state import (
    calculate_returns,
    classify_trend,
    classify_volatility,
    is_finite_number,
    is_valid_price,
)
from fx_research.report_market_state_comparison import calculate_statistics
from fx_research.check_data import classify_gap, is_market_open
from fx_research.evaluate_alerts import (
    check_interval_continuity,
    is_valid_price as evaluation_is_valid_price,
)


class OrionPureLogicTests(unittest.TestCase):
    def make_bars(self, count, step=0.00001, recent_step=None):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        price = 150.0
        bars = []
        for index in range(count):
            if recent_step is not None and index >= count - 13:
                price += recent_step
            elif index > 0:
                price += step
            bars.append((start + timedelta(minutes=5 * index), price))
        return bars

    def test_price_validation_rejects_invalid_values(self):
        for value in (None, "bad", 0, -1, float("nan"), float("inf"), -float("inf")):
            self.assertFalse(detect_price_is_valid(value))
            self.assertFalse(is_valid_price(value))
        for value in (0.0001, 1, "150.25"):
            self.assertTrue(detect_price_is_valid(value))
            self.assertTrue(is_valid_price(value))

    def test_finite_number_validation(self):
        self.assertTrue(is_finite_number("1.25"))
        for value in (None, "bad", float("nan"), float("inf")):
            self.assertFalse(is_finite_number(value))

    def test_calculate_returns_skips_time_gaps_and_bad_prices(self):
        bars = self.make_bars(4)
        bars[2] = (bars[2][0] + timedelta(minutes=5), bars[2][1])
        bars[3] = (bars[3][0], float("nan"))
        returns = calculate_returns(bars)
        self.assertEqual(len(returns), 1)
        self.assertTrue(math.isfinite(returns[0]))

    def test_classify_trend_up_and_insufficient_data(self):
        bars = self.make_bars(13, step=0.01)
        self.assertEqual(classify_trend(bars, 60), "UP")
        self.assertEqual(classify_trend(bars[:5], 60), "UNKNOWN")

    def test_classify_volatility_detects_high_recent_movement(self):
        bars = self.make_bars(302, step=0.00001, recent_step=0.01)
        state, ratio = classify_volatility(bars)
        self.assertEqual(state, "HIGH")
        self.assertIsNotNone(ratio)
        self.assertGreater(ratio, 1.5)

    def test_market_hours_and_gap_classification(self):
        friday_open = datetime(2026, 11, 6, 21, 55, tzinfo=timezone.utc)
        friday_closed = datetime(2026, 11, 6, 22, 5, tzinfo=timezone.utc)
        sunday_closed = datetime(2026, 11, 8, 21, 55, tzinfo=timezone.utc)
        sunday_open = datetime(2026, 11, 8, 22, 0, tzinfo=timezone.utc)

        self.assertTrue(is_market_open(friday_open))
        self.assertFalse(is_market_open(friday_closed))
        self.assertFalse(is_market_open(sunday_closed))
        self.assertTrue(is_market_open(sunday_open))

        classification, missing = classify_gap(
            datetime(2026, 11, 6, 21, 40, tzinfo=timezone.utc),
            datetime(2026, 11, 6, 22, 10, tzinfo=timezone.utc),
            timedelta(minutes=30),
        )
        self.assertEqual(classification, "SOURCE_GAP")
        self.assertEqual(missing, 3)

    def test_alert_evaluation_price_and_interval_checks(self):
        self.assertTrue(evaluation_is_valid_price("150.25"))
        for value in (None, "bad", 0, -1, float("nan"), float("inf")):
            self.assertFalse(evaluation_is_valid_price(value))

        alert_time = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)
        target_time = alert_time + timedelta(minutes=10)
        actual = [alert_time + timedelta(minutes=10)]
        missing = check_interval_continuity(alert_time, target_time, actual)
        self.assertEqual(missing, [alert_time + timedelta(minutes=5)])

        complete = [
            alert_time + timedelta(minutes=5),
            alert_time + timedelta(minutes=10),
        ]
        self.assertEqual(
            check_interval_continuity(alert_time, target_time, complete),
            [],
        )

    def test_statistics_for_up_down_unknown_and_empty(self):
        up = calculate_statistics([0.01, -0.002, 0.0], "UP")
        self.assertEqual(up["count"], 3)
        self.assertEqual((up["continuation"], up["reversal"], up["flat"]), (1, 1, 1))

        down = calculate_statistics([-0.01, 0.002], "DOWN")
        self.assertEqual((down["continuation"], down["reversal"]), (1, 1))

        unknown = calculate_statistics([0.01], "UNKNOWN")
        self.assertIsNone(unknown["continuation_rate"])

        empty = calculate_statistics([], "UP")
        self.assertEqual(empty["count"], 0)
        self.assertIsNone(empty["average"])


if __name__ == "__main__":
    unittest.main()
