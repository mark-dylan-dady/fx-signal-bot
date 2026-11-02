
import yfinance as yf
import pandas as pd

SYMBOLS = {
    "AUD/JPY": "AUDJPY=X",
    "EUR/JPY": "EURJPY=X",
}

START = pd.Timestamp("2026-11-01 21:00:00", tz="UTC")
END = pd.Timestamp("2026-11-02 01:00:00", tz="UTC")


def main():
    print("=" * 70)
    print("ORION Yahoo Finance Gap Inspection")
    print("Method: yf.download()")
    print(f"Target: {START} to {END}")
    print("=" * 70)

    for symbol, ticker in SYMBOLS.items():
        print(f"\n--- {symbol} ({ticker}) ---")

        try:
            data = yf.download(
                ticker,
                period="5d",
                interval="5m",
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            if data.empty:
                print("Yahoo Finance returned no data")
                continue

            if getattr(data.columns, "nlevels", 1) > 1:
                data.columns = data.columns.get_level_values(0)

            data.index = pd.to_datetime(data.index, utc=True)

            target = data[
                (data.index >= START) &
                (data.index <= END)
            ]

            print(f"Total rows: {len(data)}")
            print(f"Target rows: {len(target)}")

            if target.empty:
                print("No data found in target period")
                continue

            print("\nTarget period data:")
            print(target[["Open", "High", "Low", "Close"]].to_string())

            print("\nTime gaps:")
            intervals = target.index.to_series().diff()
            gaps = intervals[intervals > pd.Timedelta(minutes=5)]

            if gaps.empty:
                print("No gaps within returned target data")
            else:
                for timestamp, interval in gaps.items():
                    previous = target.index[target.index.get_loc(timestamp) - 1]
                    print(f"Previous: {previous}")
                    print(f"Next:     {timestamp}")
                    print(f"Interval: {interval}")

        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")

    print("\nInspection completed.")


if __name__ == "__main__":
    main()
