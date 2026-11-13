# RasPi ノードの準備と node_agent の使い方

対象:raspi1(A=負荷側)、raspi2(B=すぐ隣、真ん中)、raspi3(C=2つ離れた位置)。OS は Ubuntu 24.04、SSH ユーザー `ubuntu`。
ファンは **Raspberry Pi PoE+ HAT のファン**。Linux からは冷却デバイス `cooling_device0`(type=pwm-fan、段階 0〜4)に見える。
OS の初期設定(thermal_zone0 の step_wise)では 40/45/50/55℃ で段階的に回る。IPSJ 時に HAT を外していたのは、これで温度が上がらなかったため。

## 1. 一度だけやる準備(各 RasPi、要 sudo パスワード)

```sh
# Mac から(node_agent.py と install_node.sh は Claude Code がコピー済みなら不要)
scp scripts/node/node_agent.py scripts/node/install_node.sh ubuntu@raspiN:~/
ssh -t ubuntu@raspiN 'sudo bash ~/install_node.sh'
```

`install_node.sh` がやること:paho-mqtt と stress-ng を入れる、systemd サービス `etc-agent` を作る(自動起動はしない)、
`sudo systemctl start/stop/restart etc-agent` だけパスワードなしで打てるようにする。ブローカーのアドレスは `~/etc-agent.env`。

サービス起動中は:ファンを node_agent が制御(OS の自動制御は止める)、CPU ガバナを performance に固定。
停止すると、ファンは OS の自動制御に、ガバナは ondemand に戻る(異常終了しても戻る)。

## 2. 動作確認

```sh
# 計測だけ(root 不要。ファンにも触らない)。数秒で Ctrl-C
python3 ~/node_agent.py --no-mqtt --fan-mode none --log-dir ~/etc_logs_test

# サービスとして起動・停止
sudo systemctl start etc-agent
journalctl -u etc-agent -n 20
sudo systemctl stop etc-agent
```

## 3. 本番

`scripts/run_experiment.py`(収集用 PC)が MQTT で負荷とファンを切り替える。各ノードでは `sudo systemctl start etc-agent` しておくだけ。
手動でファンを切り替えるとき:`mosquitto_pub -h <ブローカー> -t etc/raspi1/fan/set -m 1`(0 で OFF)。

安全機能:温度が 82℃ 以上、または指令が10秒以上途絶えたら(1回でも指令を受けた後)ファンを強制 ON。ログの `failsafe` 列が 1。

## ログの列

`ts, host, temp[℃], cpu[%](前回からの平均), cpu0..3[%], clock[Hz], throttled(16進), fan(0/1), fan_pwm(0〜255), fan_cmd(-1/0/1), failsafe(0/1), load1, load(stress-ng のワーカー数), poe_ma(PoE+ HAT の電流 [mA]。USB-C 給電なら 0)`

## 気づいたこと(2026-11-13 確認)

- 3台とも `enable_uart=1`。PoE+ HAT のファンは GPIO を使わないので関係ない
- raspi2 だけ `poe_ma = 0`(USB-C 給電の可能性)。給電方法は3台そろえる(PoE に統一)
- CPU ガバナは ondemand で、アイドル時のクロックが 0.7〜1.7 GHz で変わる → 実験中は performance に固定する
