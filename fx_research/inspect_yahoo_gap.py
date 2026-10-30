
import yfinance as yf
import pandas as pd

SYMBOLS = {
    "AUD/JPY": "AUDJPY=X",
    "EUR/JPY": "EURJPY=X",
}

START = pd.Timestamp("2026-10-23 20:00:00", tz="UTC")
END = pd.Timestamp("2026-10-26 01:00:00", tz="UTC")

for pair, ticker in SYMBOLS.items():
    print(f"\n--- {pair} ({ticker}) ---")

    try:
        data = yf.Ticker(ticker).history(
            period="60d",
            interval="5m",
            auto_adjust=False,
            prepost=True,
        )

        if data.empty:
            print("Yahoo Financeからデータを取得できませんでした")
            continue

        data.index = pd.to_datetime(data.index, utc=True)

        # 調査対象期間だけを抽出
        target = data.loc[
            (data.index >= START) & (data.index <= END)
        ]

        print(f"取得した全データ本数: {len(data)}")
        print(f"調査対象期間のデータ本数: {len(target)}")

        if target.empty:
            print("調査対象期間のデータはありません")
            continue

        print("\n取得データ:")
        for timestamp, row in target.iterrows():
            print(
                f"{timestamp} | "
                f"Open={row['Open']} "
                f"High={row['High']} "
                f"Low={row['Low']} "
                f"Close={row['Close']}"
            )

    except Exception as e:
        print(f"取得エラー: {e}")
