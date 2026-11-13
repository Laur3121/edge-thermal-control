import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from datetime import datetime

st.set_page_config(page_title="Sotuken Cluster Dashboard", layout="wide")

CSV_PATH = "metrics_log.csv"
REFRESH_SEC = 3
TEMP_WARN = 70.0

# 自動更新（streamlit組み込み）
st.write(f"Auto refresh: every {REFRESH_SEC}s")
st.markdown(f"- CSV: `{CSV_PATH}`  /  Warning temp: **{TEMP_WARN}°C**")
st.markdown("---")
st.rerun  # (placeholder to satisfy linters)

# Streamlitのオートリフレッシュ（古いstreamlitでも動くように）
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=REFRESH_SEC * 1000, key="refresh")
except Exception:
    # streamlit_autorefresh が無ければ手動更新ボタンだけにする
    pass

colL, colR = st.columns([1, 2])

@st.cache_data(ttl=REFRESH_SEC)
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df
    # tsは秒エポック
    df["dt"] = pd.to_datetime(df["ts"], unit="s", errors="coerce")
    return df

try:
    df = load_csv(CSV_PATH)
except FileNotFoundError:
    st.error(f"CSV not found: {CSV_PATH}  （mqtt_collect.py を先に動かしてね）")
    st.stop()

if df.empty:
    st.warning("CSV is empty yet.")
    st.stop()

# 最新値テーブル（hostごとに最新行）
df_latest = df.sort_values("dt").groupby("host", as_index=False).tail(1).copy()
df_latest = df_latest.sort_values("temp", ascending=False)

# ===== 左：現在値一覧 =====
with colL:
    st.subheader("Current status (latest per host)")

    # 強調表示用
    def highlight_temp(row):
        try:
            t = float(row["temp"])
        except Exception:
            return [""] * len(row)
        if t >= TEMP_WARN:
            return ["background-color: rgba(255, 0, 0, 0.25)"] * len(row)
        return [""] * len(row)

    show_cols = ["host", "temp", "cpu_percent", "mem_percent", "loadavg_1m", "dt"]
    existing = [c for c in show_cols if c in df_latest.columns]
    styled = df_latest[existing].style.apply(highlight_temp, axis=1)
    st.dataframe(styled, use_container_width=True, height=420)

    st.caption("Tip: temp>=70°C rows are highlighted.")

# ===== 右：グラフ =====
with colR:
    st.subheader("Charts")

    hosts = sorted(df["host"].dropna().unique().tolist())
    default_host = hosts[0] if hosts else None

    chosen = st.selectbox("Select host", hosts, index=hosts.index(default_host) if default_host in hosts else 0)

    # 期間フィルタ
    mins = st.slider("Show last N minutes", min_value=1, max_value=180, value=30, step=1)
    t_end = df["dt"].max()
    t_start = t_end - pd.Timedelta(minutes=mins)

    df_win = df[(df["dt"] >= t_start) & (df["dt"] <= t_end)].copy()

    # 1) 選択ホストの温度
    st.markdown("### Temperature (selected host)")
    g = df_win[df_win["host"] == chosen].sort_values("dt")
    fig = plt.figure()
    plt.plot(g["dt"], g["temp"])
    plt.xlabel("time")
    plt.ylabel("temp (C)")
    plt.tight_layout()
    st.pyplot(fig, clear_figure=True)

    # 2) 全ホスト温度（重ね描き）
    st.markdown("### Temperature (all hosts)")
    fig2 = plt.figure()
    for h in hosts:
        gh = df_win[df_win["host"] == h].sort_values("dt")
        if len(gh) == 0:
            continue
        plt.plot(gh["dt"], gh["temp"], label=h)
    plt.xlabel("time")
    plt.ylabel("temp (C)")
    plt.legend(ncol=4, fontsize=9)
    plt.tight_layout()
    st.pyplot(fig2, clear_figure=True)

    # 3) CPU%（選択ホスト）
    if "cpu_percent" in df_win.columns:
        st.markdown("### CPU% (selected host)")
        g = df_win[df_win["host"] == chosen].sort_values("dt")
        fig3 = plt.figure()
        plt.plot(g["dt"], g["cpu_percent"])
        plt.xlabel("time")
        plt.ylabel("cpu_percent")
        plt.tight_layout()
        st.pyplot(fig3, clear_figure=True)

st.markdown("---")
st.caption(f"Updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
