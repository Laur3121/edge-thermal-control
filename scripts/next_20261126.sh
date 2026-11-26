#!/bin/bash
# run_chain_20261126.sh の続き(simple の後):段階の同定 → 効きの同定 → 段階を予測で選ぶ制御の比較
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
# パラメータの確認(11/26 追加。外れたら回さない)
if ! $PY scripts/check_params.py scripts/control_params_box2.json > experiments/check_params_box2.txt 2>&1; then log "check_params NG(box2)。止める"; exit 0; fi
# 11/26 10:55 追加:ファンの余力を見る提案(結果が出やすそうなものから)
run 20261126_box_control_hr scripts/scenarios/box_control_hr.json scripts/control_params_box2.json
# 11/26 11:50 差し替え:2 コアのやり直し → 台ごとにランダムな負荷(レオと決めた。帰宅したら Claude が SIGINT で止める。終わった巡だけ集計)
run 20261126_box_control_rload scripts/scenarios/box_control_rload.json scripts/control_params_box2.json
# 箱を外すのを待つ(レオが外したら Claude が experiments/BOX_REMOVED を作る)
log "箱を外すのを待つ(experiments/BOX_REMOVED)"
until [ -f experiments/BOX_REMOVED ]; do sleep 30; done
log "箱を外した:$(cat experiments/BOX_REMOVED)"
# ここから囲いなし。パラメータは囲いなしで同定し直す(囲いありのものは流用しない)
run 20261126_open_ident scripts/scenarios/open_ident.json scripts/control_params_box2.json
$PY scripts/fit_control_params_box.py --exp experiments/20261125_pattern_open experiments/20261126_open_ident --head-frac 0.6 \
  --out scripts/control_params_open.json > experiments/20261126_open_ident/fit_params.txt 2>&1
if ! $PY scripts/check_params_holdout.py scripts/control_params_open.json experiments/20261126_open_ident > experiments/check_params_open.txt 2>&1; then
  log "check_params_holdout NG(open)。止める"; exit 0; fi
log "check_params_holdout OK(open)"
run 20261126_open_control scripts/scenarios/open_control.json scripts/control_params_open.json
run 20261126_stage_ident scripts/scenarios/stage_ident.json scripts/control_params_open.json
$PY scripts/fit_stage_eff.py experiments/20261126_stage_ident scripts/control_params_open.json scripts/control_params_open_ms.json \
  > experiments/20261126_stage_ident/fit_stage_eff.txt 2>&1
log "fit_stage_eff: $(grep 平均 experiments/20261126_stage_ident/fit_stage_eff.txt)"
if [ ! -f scripts/control_params_open_ms.json ]; then log "同定に失敗(control_params_open_ms.json なし)。stage_ms は回さない"; exit 0; fi
run 20261126_stage_ms scripts/scenarios/stage_ms.json scripts/control_params_open_ms.json
# ずらした負荷:H の同定 → 制御の比較
run 20261126_stagger_ident scripts/scenarios/stagger_ident.json scripts/control_params_open.json
$PY scripts/fit_control_params_box.py --exp experiments/20261125_pattern_open experiments/20261126_stagger_ident \
  --out scripts/control_params_open3.json > experiments/20261126_stagger_ident/fit_params.txt 2>&1
if $PY scripts/check_params_holdout.py scripts/control_params_open3.json experiments/20261126_open_ident > experiments/check_params_open3.txt 2>&1; then PAR=scripts/control_params_open3.json
else PAR=scripts/control_params_open.json; log "check_params_holdout NG(open3)→ stagger_ctrl は open で回す"; fi
run 20261126_stagger_ctrl scripts/scenarios/stagger_ctrl.json $PAR
run 20261126_box_control_simple scripts/scenarios/box_control_simple.json scripts/control_params_open.json
log "next done"
