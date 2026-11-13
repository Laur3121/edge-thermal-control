import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("metrics_log.csv")
df["dt"] = pd.to_datetime(df["ts"], unit="s")
g = df[df["host"]=="raspi1"]

plt.figure()
plt.plot(g["dt"], g["temp"])
plt.xlabel("time")
plt.ylabel("temp (C)")
plt.title("raspi1 temperature")
plt.tight_layout()
plt.savefig("raspi1_temp.png")
