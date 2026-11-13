import pandas as pd
import matplotlib.pyplot as plt

df1 = pd.read_csv("raspi1r.csv")
df2 = pd.read_csv("raspi2r.csv")

# 時刻を相対時間に
t0 = df1["ts"].iloc[0]
df1["time"] = df1["ts"] - t0
df2["time"] = df2["ts"] - t0

plt.figure()

plt.plot(df1["time"], df1["temp"], label="raspi1 (target)")
plt.plot(df2["time"], df2["temp"], label="raspi2 (neighbor)")

plt.xlabel("Time [s]")
plt.ylabel("Temperature [°C]")
plt.legend()
plt.grid()

plt.savefig("r_temp_interference.png")
plt.show()