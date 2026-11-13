#!/usr/bin/env python3
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ===== パラメータ =====
DELTA = 30
WINDOW = 30
TLIMIT = 80.0

# ===== モデル係数 =====
a = 0.869049
b = 5.089084
c = 0.128026
d = -0.057212

# ===== CSV読み込み（修正済み）=====
df1 = pd.read_csv("/home/laur/sotuken/raspi1r.csv")
df2 = pd.read_csv("/home/laur/sotuken/raspi2r.csv")

t = df1["ts"].values
T = df1["temp"].values
u = df1["cpu_percent"].values / 100.0
z = df2["temp"].values

dt = np.median(np.diff(t))
m = int(DELTA / dt)
w = int(WINDOW / dt)

# ===== 予測関数 =====
def predict(T0, u_seq, z_seq):
    Tk = T0
    for uk, zk in zip(u_seq, z_seq):
        Tk = a * Tk + b * uk + c * zk + d
    return Tk

# ===== Δ先予測 =====
T_pred = np.full(len(T), np.nan)
for i in range(len(T) - m):
    T_pred[i] = predict(T[i], u[i:i+m], z[i:i+m])

# ===== 評価用整形 =====
meas = T[m:]
pred = T_pred[:-m]
e = meas - pred
z_future = z[:-m]

# ===== マージン =====
margin_s = np.zeros(len(e))
margin_p = np.zeros(len(e))

for i in range(len(e)):
    start = max(0, i - w + 1)

    std_e = np.std(e[start:i+1])
    std_z = np.std(z_future[start:i+1])

    # 坂本風
    margin_s[i] = 2.0 * std_e

    # 提案
    margin_p[i] = 2.0 * (std_e + 0.3 * std_z)  # ← 0.3くらいがバランス良い

# ===== 判定 =====
pred_s = pred + margin_s
pred_p = pred + margin_p

def evaluate(pred_with_margin):
    detect = pred_with_margin > TLIMIT
    actual = meas > TLIMIT
    miss = np.sum(actual & (~detect))
    false = np.sum((~actual) & detect)
    return miss, false

miss_s, false_s = evaluate(pred_s)
miss_p, false_p = evaluate(pred_p)

print("=== RESULT ===")
print("Sakamoto-like")
print("miss:", miss_s, "false:", false_s)
print("Proposed")
print("miss:", miss_p, "false:", false_p)

# ===== グラフ =====
plt.figure(figsize=(8, 4))
plt.plot(meas, label="Measured")
plt.plot(pred_s, label="Sakamoto-like")
plt.plot(pred_p, label="Proposed")
plt.axhline(TLIMIT, label="Limit")
plt.legend()
plt.tight_layout()
plt.show()

dt = np.median(np.diff(t))

# ===== Headroom =====
headroom = TLIMIT - meas
headroom = headroom[headroom > 0]  # 超過してない時だけ

mean_headroom = np.mean(headroom)
p95_headroom = np.quantile(headroom, 0.95)

# ===== Over area =====
over = np.maximum(0, meas - TLIMIT)
over_area = np.sum(over) * dt
over_count = np.sum(over > 0)

# ===== マージン =====
mean_margin_s = np.mean(margin_s)
mean_margin_p = np.mean(margin_p)

max_margin_s = np.max(margin_s)
max_margin_p = np.max(margin_p)

# ===== false rate =====
false_rate_s = false_s / len(meas)
false_rate_p = false_p / len(meas)

print("\n=== METRICS ===")
print(f"mean_headroom: {mean_headroom:.3f} °C")
print(f"p95_headroom: {p95_headroom:.3f} °C")
print(f"over_area: {over_area:.3f}")
print(f"over_count: {over_count}")

print("\n--- Sakamoto-like ---")
print(f"false_rate: {false_rate_s:.3f}")
print(f"mean_margin: {mean_margin_s:.3f}")
print(f"max_margin: {max_margin_s:.3f}")

print("\n--- Proposed ---")
print(f"false_rate: {false_rate_p:.3f}")
print(f"mean_margin: {mean_margin_p:.3f}")
print(f"max_margin: {max_margin_p:.3f}")