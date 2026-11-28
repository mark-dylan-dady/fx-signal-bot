"""LINE送信なしでGitHub待ち時間・Yahoo取得・シグナル検出時間を測る診断専用スクリプト。

本番の fx_signal.py の main/process_pair は呼び出さない。
LINE APIへの通信、履歴CSVの読み書きは行わない。
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import fx_signal

OUTPUT_RUN = Path("timing_audit_run.csv")
OUTPUT_EVENTS = Path("timing_audit_events.csv")

download_records = []


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    return value.isoformat(timespec="milliseconds")


def iso_jst(value):
    return value.tz_convert("Asia/Tokyo").isoformat() if hasattr(value, "tz_convert") else value.astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
    ).isoformat()


def get_github_run_metadata():
    """GitHub Actionsの作成時刻・開始時刻を取得。取得失敗時も診断自体は続行する。"""
    run_id = os.getenv("GITHUB_RUN_ID", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not (run_id and repository and token):
        return {"GitHubRunCreatedUTC": "", "GitHubRunStartedUTC": "",
                "GitHubQueueWaitSeconds": float("nan"),
                "GitHubStartToScriptSeconds": float("nan"),
                "GitHubMetadataError": "必要なGitHub環境変数がありません"}

    url = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"
    try:
        response = requests.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        created = pd.Timestamp(data["created_at"])
        started = pd.Timestamp(data["run_started_at"])
        script_started = pd.Timestamp(utc_now())
        return {
            "GitHubRunCreatedUTC": created.isoformat(),
            "GitHubRunStartedUTC": started.isoformat(),
            "GitHubQueueWaitSeconds": round((started - created).total_seconds(), 3),
            "GitHubStartToScriptSeconds": round((script_started - started).total_seconds(), 3),
            "GitHubMetadataError": "",
        }
    except Exception as exc:
        return {
            "GitHubRunCreatedUTC": "",
            "GitHubRunStartedUTC": "",
            "GitHubQueueWaitSeconds": float("nan"),
            "GitHubStartToScriptSeconds": float("nan"),
            "GitHubMetadataError": f"{type(exc).__name__}: {exc}",
        }


# Yahooへの各リクエストをラップして、開始・終了時刻と所要時間を記録する。
_original_download = fx_signal.yf.download


def timed_download(*args, **kwargs):
    started_at = utc_now()
    started_clock = time.monotonic()
    try:
        return _original_download(*args, **kwargs)
    finally:
        finished_at = utc_now()
        download_records.append({
            "Pair": args[0] if args else kwargs.get("tickers", ""),
            "Period": kwargs.get("period", ""),
            "Interval": kwargs.get("interval", ""),
            "FetchStartedUTC": iso_utc(started_at),
            "FetchFinishedUTC": iso_utc(finished_at),
            "FetchElapsedSeconds": round(time.monotonic() - started_clock, 3),
        })


fx_signal.yf.download = timed_download


def main():
    run_started = utc_now()
    run_clock = time.monotonic()
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    github_metadata = get_github_run_metadata()
    run_rows = []
    event_rows = []

    for pair in fx_signal.PAIRS:
        pair_started = utc_now()
        pair_clock = time.monotonic()
        fetch_start_index = len(download_records)

        try:
            # build_signalsだけを実行。LINE送信・履歴更新処理は呼び出さない。
            build_started = utc_now()
            build_clock = time.monotonic()
            market, market_jst = fx_signal.build_signals(pair)
            build_finished = utc_now()
            build_elapsed = time.monotonic() - build_clock

            detection_started = utc_now()
            detection_clock = time.monotonic()
            events = fx_signal.find_signal_events(
                market, market_jst, fx_signal.LOOKBACK_HOURS
            )
            detection_finished = utc_now()
            detection_elapsed = time.monotonic() - detection_clock

            detected_at = detection_finished
            for index, signal_type, bar_time in events:
                age_minutes = (
                    pd.Timestamp(detected_at).tz_convert("Asia/Tokyo") - bar_time
                ).total_seconds() / 60
                event_rows.append({
                    "RunID": run_id,
                    "Pair": pair.replace("=X", ""),
                    "SignalBarJST": bar_time.isoformat(),
                    "DetectedAtUTC": iso_utc(detected_at),
                    "DetectedAtJST": iso_jst(detected_at),
                    "SignalType": signal_type,
                    "SignalBarAgeMinutesAtDetection": round(age_minutes, 2),
                    "SignalBarClose": float(market["Close"].iloc[index]),
                })

            pair_error = ""
            event_count = len(events)
        except Exception as exc:
            pair_error = f"{type(exc).__name__}: {exc}"
            event_count = 0
            build_elapsed = float("nan")
            detection_elapsed = float("nan")

        pair_finished = utc_now()
        pair_downloads = download_records[fetch_start_index:]
        run_rows.append({
            "RunID": run_id,
            "Pair": pair.replace("=X", ""),
            "PairStartedUTC": iso_utc(pair_started),
            "PairFinishedUTC": iso_utc(pair_finished),
            "PairElapsedSeconds": round(time.monotonic() - pair_clock, 3),
            "YahooFetchCount": len(pair_downloads),
            "YahooFetchElapsedSecondsTotal": round(
                sum(item["FetchElapsedSeconds"] for item in pair_downloads), 3
            ),
            "BuildSignalsElapsedSeconds": round(build_elapsed, 3),
            "FindEventsElapsedSeconds": round(detection_elapsed, 3),
            "RecentSignalEventsFound": event_count,
            "Error": pair_error,
        })

    run_finished = utc_now()
    run_summary = {
        "RunID": run_id,
        "ScriptStartedUTC": iso_utc(run_started),
        "ScriptFinishedUTC": iso_utc(run_finished),
        "RunElapsedSeconds": round(time.monotonic() - run_clock, 3),
        "PairsProcessed": len(run_rows),
        "SignalsFound": len(event_rows),
        **github_metadata,
        "Note": "Diagnostic only: no LINE API calls and no signal-history CSV access.",
    }

    pd.DataFrame([run_summary]).to_csv(OUTPUT_RUN, index=False)
    pd.DataFrame(run_rows).to_csv("timing_audit_pairs.csv", index=False)
    pd.DataFrame(download_records).to_csv("timing_audit_downloads.csv", index=False)
    pd.DataFrame(event_rows, columns=[
        "RunID", "Pair", "SignalBarJST", "DetectedAtUTC", "DetectedAtJST",
        "SignalType", "SignalBarAgeMinutesAtDetection", "SignalBarClose",
    ]).to_csv(OUTPUT_EVENTS, index=False)

    print("=== Timing audit: diagnostic-only run ===")
    print(pd.DataFrame([run_summary]).to_string(index=False))
    print("\n=== Per-pair timings ===")
    print(pd.DataFrame(run_rows).to_string(index=False))
    print("\n=== Yahoo download timings ===")
    print(pd.DataFrame(download_records).to_string(index=False))
    print("\nLINE送信: なし / 履歴CSVの読み書き: なし")


if __name__ == "__main__":
    main()
