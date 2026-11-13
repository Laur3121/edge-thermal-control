import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ===== 設定 =====
T_limit = 80.0
M_fixed = 2.37

# 坂本風パラメータ
window = 12   # 12点 ≒ 約1分（5秒周期なら）
k = 2.0

# 提案法パラメータ
alpha = 2.0

# ===== データ読み込み =====
df = pd.read_csv("raspi1r.csv").copy()

# 相対時間
t0 = df["ts"].iloc[0]
df["time"] = df["ts"] - t0

# ===== 予測値列を用意 =====
# すでに predict_rc.py の出力CSVがあればそれを読むのが理想
# ここでは仮に temp をずらして簡易予測を作る
if "T_pred" not in df.columns:
    df["T_pred"] = df["temp"].shift(6)
    df["T_pred"] = df["T_pred"].bfill()

# 誤差
df["error"] = df["temp"] - df["T_pred"]

# ===== 固定マージン =====
df["margin_fixed"] = M_fixed
df["T_safe_fixed"] = T_limit - df["margin_fixed"]

# ===== 坂本風マージン =====
df["err_std"] = df["error"].rolling(window=window, min_periods=3).std()
df["err_std"] = df["err_std"].bfill()
df["margin_sakamoto"] = k * df["err_std"]
df["T_safe_sakamoto"] = T_limit - df["margin_sakamoto"]

# ===== 提案法マージン =====
# P列がなければ仮で誤差分散に近いものを使う
if "P" not in df.columns:
    df["P"] = (df["err_std"].fillna(0.0))**2

df["margin_prop"] = alpha * np.sqrt(df["P"])
df["T_safe_prop"] = T_limit - df["margin_prop"]

# ===== 制御判定 =====
df["ctrl_fixed"] = df["T_pred"] > df["T_safe_fixed"]
df["ctrl_sakamoto"] = df["T_pred"] > df["T_safe_sakamoto"]
df["ctrl_prop"] = df["T_pred"] > df["T_safe_prop"]

print("Control count:")
print("  fixed    =", int(df["ctrl_fixed"].sum()))
print("  sakamoto =", int(df["ctrl_sakamoto"].sum()))
print("  proposed =", int(df["ctrl_prop"].sum()))

# ===== グラフ1: マージン比較 =====
plt.figure(figsize=(10, 5))
plt.plot(df["time"], df["margin_fixed"], label="Fixed margin")
plt.plot(df["time"], df["margin_sakamoto"], label="Sakamoto-like margin")
plt.plot(df["time"], df["margin_prop"], label="Proposed margin")
plt.xlabel("Time [s]")
plt.ylabel("Margin [°C]")
plt.title("Comparison of margin values")
plt.grid()
plt.legend()
plt.tight_layout()
plt.savefig("margin_3way.png")
plt.show()

# ===== グラフ2: 温度と安全閾値 =====
plt.figure(figsize=(10, 5))
plt.plot(df["time"], df["temp"], label="Measured temp", linewidth=2)
plt.plot(df["time"], df["T_pred"], label="Predicted temp", linestyle="--")
plt.plot(df["time"], df["T_safe_fixed"], label="Fixed threshold")
plt.plot(df["time"], df["T_safe_sakamoto"], label="Sakamoto-like threshold")
plt.plot(df["time"], df["T_safe_prop"], label="Proposed threshold")
plt.xlabel("Time [s]")
plt.ylabel("Temperature [°C]")
plt.title("Comparison of safety thresholds")
plt.grid()
plt.legend()
plt.tight_layout()
plt.savefig("threshold_3way.png")
plt.show()


# ===== 逸脱判定 =====
df["violate_actual"] = df["temp"] > T_limit

# 予測温度が各手法の安全閾値を超えたら「制御発動」とみなす
# これはすでに作ってある前提
# df["ctrl_fixed"]
# df["ctrl_sakamoto"]
# df["ctrl_prop"]

# ===== 各手法のマージン量 =====
# すでにある前提
# df["margin_fixed"]
# df["margin_sakamoto"]
# df["margin_prop"]

# ===== 集計関数 =====
dt = df["time"].diff().median()  # 秒
if pd.isna(dt):
    dt = 5.0

def summarize_method(name, ctrl_col, margin_col):
    control_count = int(df[ctrl_col].sum())
    control_ratio = float(df[ctrl_col].mean())

    mean_margin = float(df[margin_col].mean())
    max_margin = float(df[margin_col].max())

    # 「制御しなかった時に実際は温度逸脱していた」回数
    miss_count = int(((~df[ctrl_col]) & df["violate_actual"]).sum())

    # 実際の温度逸脱回数そのもの
    violate_count = int(df["violate_actual"].sum())
    violate_time = float(df["violate_actual"].sum() * dt)

    return {
        "method": name,
        "control_count": control_count,
        "control_ratio": control_ratio,
        "mean_margin": mean_margin,
        "max_margin": max_margin,
        "miss_count": miss_count,
        "violate_count": violate_count,
        "violate_time_s": violate_time,
    }

results = []
results.append(summarize_method("fixed", "ctrl_fixed", "margin_fixed"))
results.append(summarize_method("sakamoto", "ctrl_sakamoto", "margin_sakamoto"))
results.append(summarize_method("proposed", "ctrl_prop", "margin_prop"))

res_df = pd.DataFrame(results)
print(res_df)

res_df.to_csv("comparison_metrics.csv", index=False)
print("[saved] comparison_metrics.csv")

plt.figure(figsize=(10,5))
plt.plot(df["time"], df["margin_fixed"], label="Fixed margin")
plt.plot(df["time"], df["margin_sakamoto"], label="Sakamoto-like margin")
plt.plot(df["time"], df["margin_prop"], label="Proposed margin")
plt.xlabel("Time [s]")
plt.ylabel("Margin [°C]")
plt.title("Comparison of margin values")
plt.grid()
plt.legend()
plt.tight_layout()
plt.savefig("margin_values.png")
plt.show()