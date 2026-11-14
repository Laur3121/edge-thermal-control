# control_trial(閉ループ制御の試運転)

開発用の試運転。比較の結果には使わない。

## 条件

- 日時:2026-11-14 16:58〜17:09(約 11 分)。温度が落ち着くのを待たずに開始(--no-settle)
- ノード:A = raspi1 のみ(raspi2・3 は etc-agent 停止、OS のファン制御)
- 配置:ラック上段、左から raspi1 | raspi2 | raspi3。PoE 給電、PoE+ HAT 装着
- 室温(ハブ2):22.1℃
- 負荷・ファン:4 コア 8 分 → 0 コア 3 分。ファンは提案手法(`src/etc/control.py` の proposed)
- 制御の設定:Tlimit 80℃、Δ 30 秒、α 2、δ 0.5℃、ヒステリシス 1℃、最小 ON 時間 30 秒。モデルは `scripts/control_params.json`(11/14 夜間データで同定、c = 0)
- CPU ガバナ:performance

## 結果(`results/control_metrics.csv`、`results/control_timeseries.png`)

- 最高 76.4℃、80℃ 超過 0 秒、スロットリング・強制 ON なし、クロックは 1.8 GHz のまま
- σ = 1.11℃ → M = 2.71℃、Tsafe = 77.3℃(一定)
- 4 コアの間、ファンは約 50 秒周期で ON 30 秒(最小 ON 時間)/ OFF 約 20 秒をくり返した。稼働率 41%、ON 9 回
- 4 コアをファンなしで続けると定常で約 86℃ になる条件なので、周期的な ON/OFF は設計どおり。ON の長さは最小 ON 時間で決まっている
