# 5. シグナル結果の検証機能（過去のシグナルが成功したか判定）
def verify_past_signals(history_df, market_df):
    updated = False

    # market_df のインデックスをタイムゾーンなし（JST）に統一しておくと比較しやすい
    m_df = market_df.copy()
    if m_df.index.tz is not None:
        m_df.index = m_df.index.tz_convert("Asia/Tokyo").tz_localize(None)

    for idx, row in history_df.iterrows():
        if row["Result"] != "Pending":
            continue

        # 保存されているタイムスタンプを naive (JST) な datetime に変換
        sig_time = pd.to_datetime(row["Timestamp"])
        if sig_time.tzinfo is not None:
            sig_time = sig_time.tz_convert("Asia/Tokyo").tz_localize(None)

        sig_type = row["Type"]
        entry_price = float(row["Entry"])
        tp = float(row["TP"])
        sl = float(row["SL"])

        # シグナル発生以降の5分足データを取得（最大30本分 = 2.5時間分）
        future_data = m_df[m_df.index > sig_time].head(30)
        if future_data.empty:
            continue

        for _, f_row in future_data.iterrows():
            high = float(f_row["High"])
            low = float(f_row["Low"])

            if sig_type == "BUY":
                if high >= tp:
                    history_df.loc[idx, "Result"] = "WIN"
                    updated = True
                    break
                elif low <= sl:
                    history_df.loc[idx, "Result"] = "LOSE"
                    updated = True
                    break
            elif sig_type == "SELL":
                if low <= tp:
                    history_df.loc[idx, "Result"] = "WIN"
                    updated = True
                    break
                elif high >= sl:
                    history_df.loc[idx, "Result"] = "LOSE"
                    updated = True
                    break

    return history_df, updated
