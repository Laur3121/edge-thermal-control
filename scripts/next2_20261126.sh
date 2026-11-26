#!/bin/bash
# next_20261126.sh の続きを組み直したもの(11/26 20:00)。レオ「やりたい実験からどんどん回してくれていい」。
# 変更:箱を外したあと、open_ident の次に open_delay60(ファンの指令を 60 秒遅らせる)を入れた。ほかの順番は同じ
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
run() {  # $1 名前, $2 シナリオ, $3 パラメータ
  local exp=experiments/$1
  for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
  log "start $1 ($3)"
  setsid nohup $PY scripts/run_experiment.py --scenario "$2" --nodes $NODES --out $exp --ambient --ambient-name ハブ２ \
    --control-params "$3" > experiments/${1}_run.log 2>&1 < /dev/null &
  sleep 15
  setsid nohup $PY scripts/box_watchdog.py --exp $exp --limit 50 > experiments/${1}_watchdog.out 2>&1 < /dev/null &
  sleep 30
  wait_end $exp
  pkill -f "box_watchdog.py --exp $exp"
  log "end $1: $(tail -1 $exp/events.csv)"
  if grep -q "上限超え" experiments/${1}_watchdog.out 2>/dev/null; then log "watchdog stopped $1; next aborted"; exit 0; fi
}
log "next2 開始(next_20261126.sh から引き継ぎ)"
# 走っている rload の終わりを待つ(next_20261126.sh の run の後始末をここでする)
wait_end experiments/20261126_box_control_rload
pkill -f "box_watchdog.py --exp experiments/20261126_box_control_rload"
log "end 20261126_box_control_rload: $(tail -1 experiments/20261126_box_control_rload/events.csv)"
if grep -q "上限超え" experiments/20261126_box_control_rload_watchdog.out 2>/dev/null; then log "watchdog stopped rload"; fi
# 箱を外すのを待つ(レオが外したら Claude が experiments/BOX_REMOVED を作る)
log "箱を外すのを待つ(experiments/BOX_REMOVED)"
until [ -f experiments/BOX_REMOVED ]; do sleep 30; done
log "箱を外した:$(cat experiments/BOX_REMOVED)"
run 20261126_open_ident scripts/scenarios/open_ident.json scripts/control_params_box2.json
$PY scripts/fit_control_params_box.py --exp experiments/20261125_pattern_open experiments/20261126_open_ident --head-frac 0.6 \
  --out scripts/control_params_open.json > experiments/20261126_open_ident/fit_params.txt 2>&1
if ! $PY scripts/check_params_holdout.py scripts/control_params_open.json experiments/20261126_open_ident > experiments/check_params_open.txt 2>&1; then
  log "check_params_holdout NG(open)。止める"; exit 0; fi
log "check_params_holdout OK(open)"
run 20261126_open_delay60 scripts/scenarios/open_delay60.json scripts/control_params_open.json
run 20261126_open_control scripts/scenarios/open_control.json scripts/control_params_open.json
run 20261126_stage_ident scripts/scenarios/stage_ident.json scripts/control_params_open.json
$PY scripts/fit_stage_eff.py experiments/20261126_stage_ident scripts/control_params_open.json scripts/control_params_open_ms.json \
  > experiments/20261126_stage_ident/fit_stage_eff.txt 2>&1
log "fit_stage_eff: $(grep 平均 experiments/20261126_stage_ident/fit_stage_eff.txt)"
if [ -f scripts/control_params_open_ms.json ]; then
  run 20261126_stage_ms scripts/scenarios/stage_ms.json scripts/control_params_open_ms.json
else log "同定に失敗(control_params_open_ms.json なし)。stage_ms は回さない"; fi
run 20261126_stagger_ident scripts/scenarios/stagger_ident.json scripts/control_params_open.json
$PY scripts/fit_control_params_box.py --exp experiments/20261125_pattern_open experiments/20261126_stagger_ident \
  --out scripts/control_params_open3.json > experiments/20261126_stagger_ident/fit_params.txt 2>&1
if $PY scripts/check_params_holdout.py scripts/control_params_open3.json experiments/20261126_open_ident > experiments/check_params_open3.txt 2>&1; then PAR=scripts/control_params_open3.json
else PAR=scripts/control_params_open.json; log "check_params_holdout NG(open3)→ stagger_ctrl は open で回す"; fi
run 20261126_stagger_ctrl scripts/scenarios/stagger_ctrl.json $PAR
run 20261126_box_control_simple scripts/scenarios/box_control_simple.json scripts/control_params_open.json
log "next2 done"
