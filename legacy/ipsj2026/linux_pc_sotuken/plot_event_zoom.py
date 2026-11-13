import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("model_fit_comparison.csv")

# ===== ここ変えられる =====
t_start = 300
t_end = 450
# ==========================

sub = df[(df["time_s"] >= t_start) & (df["time_s"] <= t_end)]

plt.figure(figsize=(8,4.5))

plt.plot(sub["time_s"], sub["T_meas_future"], label="Measured", linewidth=2.5)
plt.plot(sub["time_s"], sub["T_pred_self_only"], "--", label="Self-only")
plt.plot(sub["time_s"], sub["T_pred_sakamoto_like"], "--", label="Sakamoto-like")
plt.plot(sub["time_s"], sub["T_pred_proposed"], "--", label="Proposed")

plt.xlabel("Time [s]")
plt.ylabel("Temperature [°C]")
plt.title("Prediction around disturbance (load ON)")
plt.grid()
plt.legend()
plt.tight_layout()

plt.savefig("event_on_zoom.png", dpi=200)
plt.show()