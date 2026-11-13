import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("out_kalman_adaptive_qh_prediction_timeseries.csv")

window = 6

df["measured_ma"] = df["measured_temp"].rolling(window=window, center=True).mean()
df["self_ma"] = df["self_only_pred"].rolling(window=window, center=True).mean()
df["saka_ma"] = df["sakamoto_pred"].rolling(window=window, center=True).mean()
df["prop_ma"] = df["proposed_kalman_pred"].rolling(window=window, center=True).mean()

plt.figure(figsize=(10, 5))

# 生データを薄く残すなら
# plt.plot(df["time_s"], df["measured_temp"], alpha=0.25, label="Measured raw")

# 移動平均後
plt.plot(df["time_s"], df["measured_ma"], linewidth=2.2, label="Measured")
plt.plot(df["time_s"], df["self_ma"], "--", linewidth=1.8, label="Self-only")
plt.plot(df["time_s"], df["saka_ma"], "--", linewidth=1.8, label="Sakamoto-like")
plt.plot(df["time_s"], df["prop_ma"], "--", linewidth=2.0, label="Proposed (Kalman)")

plt.xlabel("Time [s]")
plt.ylabel("Temperature [°C]")
plt.grid()
plt.legend()
plt.tight_layout()
plt.savefig("meas_vs_pred_ma6.png", dpi=300)
plt.show()