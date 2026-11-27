"""DB-free comparison of valid-return and clock-time baselines."""

import math
from statistics import median
from datetime import timedelta


def compare_baseline_methods(
    returns,
    baseline_returns=288,
    recent_hours=24,
    min_time_samples=30,
    multiplier=3.0,
):
    """Compare 288-prior-return and prior-24-hour baselines.

    Each input item is (timestamp, absolute_change_pct, direction).
    Method A is available only with a full baseline_returns sample.
    Method B is available with at least min_time_samples in the
    half-open interval [candidate_time - recent_hours, candidate_time).
    Only candidates in the most recent recent_hours are evaluated.
    """
    if baseline_returns < 1:
        raise ValueError("baseline_returns must be positive")
    if recent_hours <= 0:
        raise ValueError("recent_hours must be positive")
    if min_time_samples < 1:
        raise ValueError("min_time_samples must be positive")
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("multiplier must be a positive finite number")

    clean_returns = []
    for timestamp, change_pct, direction in returns:
        try:
            value = float(change_pct)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value) and value >= 0:
            clean_returns.append((timestamp, value, direction))

    clean_returns.sort(key=lambda item: item[0])
    if not clean_returns:
        return []

    latest_time = clean_returns[-1][0]
    recent_cutoff = latest_time - timedelta(hours=recent_hours)
    results = []

    for index, (timestamp, change_pct, direction) in enumerate(clean_returns):
        if timestamp < recent_cutoff:
            continue

        history = clean_returns[:index]
        a_history = history[-baseline_returns:]
        a_baseline = None
        a_ratio = None
        a_alert = None
        a_coverage_hours = None

        if len(a_history) == baseline_returns:
            a_baseline = median(item[1] for item in a_history)
            if a_baseline > 0:
                a_ratio = change_pct / a_baseline
                a_alert = a_ratio >= multiplier
            a_coverage_hours = (
                timestamp - a_history[0][0]
            ).total_seconds() / 3600

        time_cutoff = timestamp - timedelta(hours=recent_hours)
        b_history = [
            item for item in history
            if item[0] >= time_cutoff
        ]
        b_baseline = None
        b_ratio = None
        b_alert = None

        if len(b_history) >= min_time_samples:
            b_baseline = median(item[1] for item in b_history)
            if b_baseline > 0:
                b_ratio = change_pct / b_baseline
                b_alert = b_ratio >= multiplier

        results.append({
            "timestamp": timestamp,
            "change_pct": change_pct,
            "direction": direction,
            "a_sample_count": len(a_history),
            "a_baseline_pct": a_baseline,
            "a_ratio": a_ratio,
            "a_alert": a_alert,
            "a_coverage_hours": a_coverage_hours,
            "b_sample_count": len(b_history),
            "b_baseline_pct": b_baseline,
            "b_ratio": b_ratio,
            "b_alert": b_alert,
        })

    return results


def summarize_comparison(results):
    """Return counts and disagreements, including only comparable alerts."""
    a_available = [item for item in results if item["a_alert"] is not None]
    b_available = [item for item in results if item["b_alert"] is not None]
    both_available = [
        item for item in results
        if item["a_alert"] is not None and item["b_alert"] is not None
    ]

    return {
        "candidate_count": len(results),
        "a_available_count": len(a_available),
        "b_available_count": len(b_available),
        "both_available_count": len(both_available),
        "a_alert_count": sum(item["a_alert"] is True for item in a_available),
        "b_alert_count": sum(item["b_alert"] is True for item in b_available),
        "disagreement_count": sum(
            item["a_alert"] != item["b_alert"]
            for item in both_available
        ),
        "disagreements": [
            item["timestamp"]
            for item in both_available
            if item["a_alert"] != item["b_alert"]
        ],
    }
