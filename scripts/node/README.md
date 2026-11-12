# RasPi ノードの準備と node_agent の使い方

対象:実験に使う3台(A=負荷側、B=A のすぐ隣、C=離れた位置)。収集用 PC(Linux)で MQTT ブローカーと `scripts/collector.py` を動かす。

## 1. 一度だけやる準備(各 RasPi)

1. **標準のファン制御を無効化**:`/boot/firmware/config.txt`(古い OS は `/boot/config.txt`)の `dtoverlay=gpio-fan,...` をコメントアウトする(raspi-config の Performance → Fan で設定した場合もここに書かれる)。再起動
2. **ファンの配線**:公式ケースファンの赤 = 5V、黒 = GND、**青(制御)= GPIO14**
3. **パッケージ**:`sudo apt install python3-paho-mqtt python3-gpiozero stress-ng`
4. **時刻同期**:`timedatectl` で `System clock synchronized: yes` を確認(なっていなければ chrony か systemd-timesyncd を有効化)
5. **CPU ガバナを記録**:`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor` の結果を実験 README に書く
6. `node_agent.py` を RasPi にコピー:`scp scripts/node/node_agent.py pi@<RasPi>:~/`

## 2. 動作確認

```sh
# 計測だけ(MQTT・GPIO なし)。10秒ほどで Ctrl-C、~/etc_logs/ の CSV を確認
python3 node_agent.py --no-mqtt --no-fan

# ファンの単体確認(GPIO14 を 5 秒 ON)
python3 -c "from gpiozero import OutputDevice; import time; f=OutputDevice(14); f.on(); time.sleep(5); f.off()"
```

確認すること:`cpu` が 0〜100 の間で滑らかに変わる(`stress-ng --cpu 2 --timeout 30` を流すと約50%)、`clock` が数値、`throttled` が `0x0`。

## 3. 本番(MQTT 経由)

```sh
# 収集用 PC
python scripts/collector.py --broker localhost --out experiments/YYYYMMDD_<name>
# 各 RasPi
python3 node_agent.py --broker <PCのIP>
# 手動でファンを切り替える(PC から)
mosquitto_pub -h localhost -t etc/<host>/fan/set -m 1
```

安全機能:温度が 82℃ 以上、または指令が10秒以上途絶えたら(1回でも指令を受けた後)ファンを強制 ON にする。ログの `failsafe` 列が 1 になる。

## ログの列

`ts, host, temp[℃], cpu[%](前回からの平均), cpu0..3[%], clock[Hz], throttled(16進), fan(0/1), fan_cmd(-1/0/1), failsafe(0/1), load1`
