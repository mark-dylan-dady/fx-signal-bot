
import pandas as pd
import yfinance as yf


THRESHOLD = 0.01  # pips未満の変化は停止扱い


def load_duka(filename):
    df = pd.read_csv(filename)
    df["Datetime"] = pd.to_datetime(
        df["timestamp"], unit="ms", utc=True
    )
    return df.set_index("Datetime")


def analyze(date):
    print(f"\n===== {date} EUR/USD 停止時間の分析 =====")

    base = "download/eurusd-m1"

    bid = load_duka(f"{base}-bid-{date}-2145-2215.csv")
    ask = load_duka(f"{base}-ask-{date}-2145-2215.csv")

    yahoo = yf.download(
        "EURUSD=X",
        start=date,
        end=(pd.Timestamp(date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1m",
        auto_adjust=False,
        progress=False
    )

    if isinstance(yahoo.columns, pd.MultiIndex):
        yahoo.columns = yahoo.columns.get_level_values(0)

    yahoo.index = pd.to_datetime(yahoo.index, utc=True)

    data = pd.DataFrame({
        "Yahoo": yahoo["Close"],
        "Mid": (bid["close"] + ask["close"]) / 2
    }).dropna().sort_index()

    data["Yahoo変化"] = data["Yahoo"].diff() / 0.0001
    data["Mid変化"] = data["Mid"].diff() / 0.0001

    flat = data["Yahoo変化"].abs() < THRESHOLD

    runs = []
    current = []

    for timestamp, is_flat in flat.items():
        if is_flat:
            current.append(timestamp)
        else:
            if current:
                runs.append(current)
                current = []

    if current:
        runs.append(current)

    results = []

    for run in runs:
        if len(run) < 2:
            continue

        start = run[0]
        end = run[-1]

        # 停止開始直前から終了時点までを調べる
        previous = data.index.get_loc(start) - 1

        if previous < 0:
            continue

        window = data.iloc[previous:data.index.get_loc(end) + 1]

        movement = window["Mid"].diff().abs().sum() / 0.0001
        net = (window["Mid"].iloc[-1] - window["Mid"].iloc[0]) / 0.0001
        width = (
            window["Mid"].max() - window["Mid"].min()
        ) / 0.0001

        results.append({
            "開始": start.strftime("%H:%M"),
            "終了": end.strftime("%H:%M"),
            "停止分数": len(run),
            "Duka累積変動": movement,
            "Duka最終変化": net,
            "Duka値幅": width
        })

    print("Yahoo停止区間数:", len(results))

    if not results:
        print("2分以上連続した停止区間はありません")
        return

    result = pd.DataFrame(results)

    print(result.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    print("\n停止区間の合計分数:", result["停止分数"].sum())
    print("Duka累積変動の平均:",
          round(result["Duka累積変動"].mean(), 2), "pips")
    print("Duka値幅の平均:",
          round(result["Duka値幅"].mean(), 2), "pips")


analyze("2026-11-05")
analyze("2026-11-06")
