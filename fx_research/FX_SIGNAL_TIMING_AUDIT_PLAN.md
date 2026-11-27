# FX Signal Timing Audit Plan

## Purpose

Identify where the apparent delay occurs without changing the production bot or sending additional LINE messages.

This document is a design note only. It does not change `fx_signal.py`, `.github/workflows/main.yml`, LINE behavior, or the production schedule.

## Timing points to record

All timestamps should be stored in UTC ISO-8601 with timezone information. Also store the corresponding Asia/Tokyo timestamp for easy reading.

| Field | Meaning |
|---|---|
| `workflow_run_id` | GitHub Actions run ID (`GITHUB_RUN_ID`) |
| `workflow_started_at` | Workflow start time (`GITHUB_RUN_STARTED_AT`, if available; otherwise record first-step time) |
| `data_fetch_started_at` | Immediately before requesting Yahoo 5-minute data |
| `data_fetch_finished_at` | Immediately after Yahoo data request completes |
| `signal_bar_time` | Timestamp of the completed 5-minute candle that generated the signal |
| `signal_detected_at` | Wall-clock time when the program identifies that signal |
| `line_request_started_at` | Immediately before the LINE Push API request |
| `line_response_received_at` | Immediately after the LINE API response arrives |
| `line_http_status` | HTTP response status; do not store access tokens or response secrets |
| `elapsed_fetch_seconds` | Data-fetch duration measured with a monotonic clock |
| `elapsed_line_seconds` | LINE API request duration measured with a monotonic clock |

## Derived delay measurements

- **Bar-close-to-detection** = `signal_detected_at - signal_bar_time`
- **Workflow-start-to-detection** = `signal_detected_at - workflow_started_at`
- **Detection-to-LINE-response** = `line_response_received_at - signal_detected_at`
- **Fetch duration** = `data_fetch_finished_at - data_fetch_started_at`

The first measurement includes the wait until the next workflow execution and the time needed to download and analyze data. Comparing the other measurements helps separate those causes.

## Important limitation: LINE delivery vs. LINE API response

A successful LINE Push API response confirms that LINE accepted the request; it does **not** tell us the exact time the message appeared on the user's phone. Actual handset arrival time would require a separate user-observed receipt timestamp or another supported delivery measurement. We must not label API response time as phone arrival time.

## Safe rollout sequence

1. Review this timing plan on the isolated `fx-signal-audit` branch.
2. Add instrumentation in a separate change and test it without sending LINE messages.
3. Inspect the recorded timestamps and confirm no secrets or personal data are written to the log.
4. Only after explicit approval, consider a minimal production change to collect real scheduled-run timings.
5. Keep `.github/workflows/main.yml` and production behavior unchanged until that approval.

## Data handling

- Record one row per detected signal, plus a run-level record when useful.
- Keep timestamps timezone-aware; do not compare naive local timestamps.
- Use a monotonic clock for elapsed durations, because wall-clock adjustments can distort duration calculations.
- Never write LINE access tokens, user IDs, or full authorization headers to artifacts.
- Preserve the original signal candle timestamp and original Entry/TP/SL for later comparison.
