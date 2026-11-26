# 引き継ぎ(2026-11-26 夜、予備審査 11/27 10:30 の前夜)

新しいセッションはまずこれを読む。CLAUDE.md・`docs/tasks.md`・メモリも。

## 締切
- 11/26 23:59 Teams 提出:発表資料(スライド)・成果の要旨・論文第 1 稿。レジュメは提出済み(直した版 `thesis/resume/resumeB_2p.pdf` を出し直すかは先生に確認)
- 11/27 10:30 予備審査(15 分)

## 成果物の場所
- スライド:claude.ai の Slides アーティファクト https://claude.ai/artifact/D8oxjNxY5KARopHAdCfUbS(ローカルの作業コピーは前のセッションの scratchpad にあったので、編集するときは Artifact の read で取り直す)
- 成果の要旨:`scripts/make_seika_docx.py` → `~/Documents/成果の要旨_下書き.docx`(残りの【】は科目名・年次、計画書へのコメント。レオが埋める)
- 論文:`thesis/`(`latexmk main.tex` → `thesis/build/main.pdf`)。7.7 節に結果待ちのダミーの図(\DUMMYFIG)が 4 つ:open_control、open_delay60、stage_ms、stagger_ctrl
- 図:`scripts/fig_resume.py`(fig_rise、fig_pred、fig_fan、fig_box_rerun、fig_sim_slide、fig_sim_trace)

## 研究の結末(11/26 にレオと合意)
1. 空間熱干渉の正体は囲いの蓄熱(直接の排熱で隣の温度が上がるのは 1℃ 未満、囲うと +5〜10℃)
2. H は温度計の代わりになる(囲いありで温度計と同じ精度)。ただし 30 秒先の精度だけなら温度の履歴だけの AR でも同程度(`eval_pattern_ar.py`)。H の価値は「囲いの熱の量が分かる」「ファンを止めたら何℃かを予測できる」
3. ファン制御で予測が得をするのは冷却が遅い場合。PoE+ HAT(5 秒で効く)ではしきい値で十分。シミュレーション(`20261122_sim_slow_cooling`、`fig_sim_trace.png`)では遅れ 60 秒でしきい値は 80℃ を超え、提案は超えない
提案が勝つことを結末にしない。外れた結果も全部書く。「経路が小さい」などの言い方は使わない(先生 11/26)。

## 実験の状態(収集用 PC、Tailscale `ssh -o HostKeyAlias=192.168.0.50 laur@100.68.157.76`)
- 自動実行:`scripts/next2_20261126.sh`(11/26 19:23 開始、ログ `experiments/chain_20261126.log`)
  1. `20261126_box_control_rload`(囲いあり、台ごとにランダムな負荷)の終了を待つ(20:50 ごろ)
  2. `experiments/BOX_REMOVED` ができるまで待つ ← **レオが箱を外したら Claude が作る**(中身は時刻とメモ)
  3. open_ident → パラメータ同定・holdout 確認(NG なら止まる)→ **open_delay60**(ファンの指令を 60 秒遅らせる、しきい値 vs 提案)→ open_control → stage_ident → stage_ms → stagger_ident → stagger_ctrl → box_control_simple
- **r5 のファンが止まっていた**(11/26 夕、触ったら回った。接触不良の疑い)。箱を外すときにレオが HAT を押し込む → BOX_REMOVED を作る前に r5 だけファンを 2 分 ON/OFF して温度が下がるか確かめる。判定は r5 を除く 7 台で行う(各 README に実行前に記載済み)
- 結果が出たら:`python scripts/analyze_box_control.py experiments/<名前>` → README の「結果」に判定(実行前に決めた基準)を書く → 図 → 論文のダミーを差し替え → スライドに反映。生ログは編集しない

## 今日の結果(囲いあり、r5 を除く 7 台)
- 段階 2:提案 56%・80℃ 超え 760 秒、しきい値 63%・246 秒 → 差なし
- 余力を見る提案:提案 + 余力 67%・431 秒、しきい値 64%・308 秒、常時 ON 0 秒 → 予想外れ
- クロックの低下(参考の指標)は 80℃ 超えよりずっと短い

## 先生の指摘(11/26 夕)への対応
温度上昇・干渉ありの定義を文で、主語を補う、負荷 10 分・休み 12 分の理由(時定数 1〜1.5 分の 6 倍以上。最初からこの理由で決めたとは言わない)、式の根拠と引用(熱 RC モデル:Skadron ら ISCA 2003、Kalman 1960)、図 2 は囲いなし点線・あり実線で重ねた、Q2 の凡例を「基準:部屋の室温/ラック前の温度計/提案」に。「囲いの気温を引く意味は?」への答えは Q2 スライドの原稿メモ。
