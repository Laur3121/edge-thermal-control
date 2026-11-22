#!/bin/bash
# 11/22 夜:compare_os が終わったら、interference_load と fan_stage を続けて回す(収集用 PC で実行)。
# run_experiment.py は終了時に各ノードの etc-agent を止めるので、実験ごとに起動し直す。
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="A=raspi1 B=raspi2 C=raspi3"
log() { echo "[$(date '+%F %T')] $*" >> experiments/chain_20261123.log; }
start_agents() {
  for h in 192.168.0.51 192.168.0.52 192.168.0.53; do
    ssh -o BatchMode=yes -o ConnectTimeout=10 ubuntu@$h 'sudo -n systemctl start etc-agent; systemctl is-active etc-agent' >> experiments/chain_20261123.log 2>&1
  done
  sleep 15
}
log "wait for compare_os"
while pgrep -f "scenarios/compare_os.json" > /dev/null; do sleep 60; done
log "compare_os finished"; sleep 30
start_agents
log "start interference_load"
$PY scripts/run_experiment.py --scenario scripts/scenarios/interference_load.json --nodes $NODES \
  --out experiments/20261123_interference_load --ambient > experiments/interference_load_run.log 2>&1
log "interference_load exit $?"; sleep 30
start_agents
log "start fan_stage"
$PY scripts/run_experiment.py --scenario scripts/scenarios/fan_stage.json --nodes $NODES \
  --out experiments/20261123_fan_stage --ambient --control-params scripts/control_params.json > experiments/fan_stage_run.log 2>&1
log "fan_stage exit $?"
