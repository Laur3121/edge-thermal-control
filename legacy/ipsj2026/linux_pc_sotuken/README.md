# IPSJ 時の研究フォルダ(収集用 Linux PC の ~/sotuken/ のコピー)

2026-11-13 に収集用 PC(192.168.0.50、laur-IdeaPad-5-14ALC05)で発見し、コピーしたもの。**参照用。編集しない。**
除外したもの:`venv/`(689MB)と `*.png`(図。元の PC に残っている)。

## 重要:IPSJ 予稿の数値を出したコード

`predict_kalman.py` を `--adaptive_qh` 付きで実行した出力 `out_kalman_adaptive_qh_*.csv`(2026-04-20)が、予稿の表3・表4と一致する。

| 手法 | Bias | MAE | RMSE | R² | 平均マージン | 最大マージン | 制御率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Self-only | 0.041 | 0.999 | 1.290 | 0.913 | 1.861 | 1.861 | 0.809 |
| 坂本型 | −0.074 | 1.164 | 1.489 | 0.884 | 1.827 | 4.062 | 0.763 |
| 提案(Kalman) | 0.131 | 0.878 | 1.139 | 0.932 | 1.491 | 1.823 | 0.750 |

データは `data/legacy/expC_*`(raspi1.csv / raspi2.csv)と同じと考えられる(Self-only と坂本型の値が `predict_rc.py` の系統と同じ形)。
実行時のコマンドライン引数(β、qT、qH、R など)は残っていない。予稿の値(ρ=0.90、R=0.077、qT=0.038、qH0=0.008、β=2.0)で指定したと推定。

## このコードの問題点(特研IIの再実装 `src/etc/` で直したもの)

1. **Δ秒先の予測に未来の実測値を使っている**:`kalman_k_step_predict_from_filtered_state` に `ug[k:k+m]`(未来の CPU 使用率)と `zg_centered[k:k+m]`(未来の隣接温度)を渡している。適応ノイズ qH も未来の隣接温度の変化量から計算している。実時間の制御では使えない情報
2. **同定と評価が同じデータ**:a, b, c, d を全区間で最小二乗し、同じ区間で評価している
3. **同じデータで設定を変えながら評価した履歴がある**:`out_kalman_*` の提案手法の MAE は 3.11(out_kalman)→ 9.03(rev, rev2)→ 0.918(compare)→ 0.878(adaptive_qh)。最後のものが予稿に載った
4. **c の同定と使い方が食い違う**:`fit_model_with_neighbor` は c を「中心化した隣接温度 z」の係数として同定しているが、KF では「H(z を一次遅れで通したもの)」の係数として使っている
5. **miss_count の定義**:制御が発動していれば実測が 80℃ を超えても数えない(violate 166 サンプル・830秒あるのに miss 0)
6. b(自ノード負荷の係数)が負。CPU 使用率が瞬時値で記録されていたため(`experiments/20261112_legacy_kf_check/README.md`)

## その他のファイル

- `mqtt_collect.py`:旧収集スクリプト。トピック `cluster/+/metrics`、ブローカー localhost
- `control_master.py`, `control_master_online.py`:SSH で RasPi の温度を取って制御判断するスクリプト(4月16〜17日)。`logs/*_5_10_5.csv` はその実行ログ(5分・10分・5分の負荷パターン)
- `predict_rc.py`:`legacy/ipsj2026/predict_rc.py` と同系統(ARX 版)
- `eval_*.py`, `make_paper_figures.py`, `plot_*.py`, `シミュレーション/`:評価・作図
- `metrics_log_*.csv`, `output/metrics_log_stress2.csv`:1〜3月ごろの収集ログ
