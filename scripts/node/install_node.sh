#!/usr/bin/env bash
# 各 RasPi で一度だけ実行する(要 sudo)。node_agent を systemd サービス etc-agent として登録する。
#
#   scp scripts/node/node_agent.py scripts/node/install_node.sh ubuntu@raspiN:~/
#   ssh -t ubuntu@raspiN 'sudo bash ~/install_node.sh'
#
# やること:
#   1. python3-paho-mqtt と stress-ng を入れる
#   2. /etc/systemd/system/etc-agent.service を作る(起動時に自動では動かさない)
#      - 起動中:PoE+ HAT ファンを node_agent が制御、CPU ガバナを performance に固定
#      - 停止後:ファンを OS の自動制御(step_wise)に、ガバナを ondemand に戻す(異常終了でも戻す)
#   3. ubuntu ユーザーが sudo のパスワードなしで etc-agent の start/stop/restart だけできるようにする
#      (実験スクリプトや Claude Code から SSH で起動・停止するため。ほかのコマンドには影響しない)
# 設定(ブローカーのアドレス等)は ~ubuntu/etc-agent.env。sudo なしで編集できる。
set -euo pipefail

USER_NAME=ubuntu
HOME_DIR=/home/$USER_NAME
AGENT=$HOME_DIR/node_agent.py
ENV_FILE=$HOME_DIR/etc-agent.env

[ "$(id -u)" -eq 0 ] || { echo "sudo で実行してください"; exit 1; }
[ -f "$AGENT" ] || { echo "$AGENT がない。先に scp する"; exit 1; }

apt-get update -qq
apt-get install -y -qq python3-paho-mqtt stress-ng

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
# etc-agent の設定。変えたら: sudo systemctl restart etc-agent
BROKER=192.168.0.50
AGENT_ARGS=--fan-mode poe
EOF
  chown $USER_NAME:$USER_NAME "$ENV_FILE"
fi
mkdir -p /var/log/etc-agent
chown $USER_NAME:$USER_NAME /var/log/etc-agent

cat > /etc/systemd/system/etc-agent.service <<EOF
[Unit]
Description=edge-thermal-control node agent (telemetry + PoE+ HAT fan + load)
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
ExecStartPre=/bin/sh -c 'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > \$g; done'
ExecStart=/usr/bin/python3 $AGENT --broker \${BROKER} --log-dir /var/log/etc-agent \$AGENT_ARGS
ExecStopPost=/bin/sh -c 'echo step_wise > /sys/class/thermal/thermal_zone0/policy; for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo ondemand > \$g; done; pkill -x stress-ng || true'
KillSignal=SIGINT
TimeoutStopSec=15
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/sudoers.d/etc-agent <<EOF
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl start etc-agent, /usr/bin/systemctl stop etc-agent, /usr/bin/systemctl restart etc-agent
EOF
chmod 440 /etc/sudoers.d/etc-agent
visudo -cf /etc/sudoers.d/etc-agent

systemctl daemon-reload
echo "OK: sudo systemctl start etc-agent で起動、stop で停止(ファンと CPU ガバナは自動で元に戻る)"
