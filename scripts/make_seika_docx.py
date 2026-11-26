#!/usr/bin/env python3
"""成果の要旨(様式 2a)の下書きを、学校の様式ファイルに流し込む(2026-11-26)。

様式:~/Documents/no7_1_youshi_2a-2.docx(リポジトリには入れない)
出力:~/Documents/成果の要旨_下書き.docx(レオが Word で開いて直し、提出する)
- 様式の説明の箱(「このテキストボックスごと削除」)は消す
- 【】は確認・結果待ちの所。黄色の網掛けにする
- 書き方は知念研の先輩(7302 大宮さん、7303 奥田さん)ほか 2025 年度の 6 人の要旨に合わせた

使い方(python-docx が要る):python scripts/make_seika_docx.py [--fig-res 図のパス]
"""
from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

FORM = Path.home() / "Documents" / "no7_1_youshi_2a-2.docx"
OUT = Path.home() / "Documents" / "成果の要旨_下書き.docx"
FIG = Path(__file__).resolve().parents[1] / "thesis" / "figures"

HEAD = {(0, 1): "東京都立産業技術高等専門学校", (0, 3): "創造工学専攻",
        (1, 1): "工学", (1, 3): "情報工学",
        (2, 1): "鈴木 黎映", (2, 3): "25615016",
        (3, 1): "エッジマイクロクラスタにおける空間熱干渉を考慮した熱抑制手法の研究",
        (4, 1): "知念 賢一", (4, 3): "佐藤 喬"}

S11 = [
    "データセンタでは、サーバの排熱が別のサーバの吸気側に回り込む熱の再循環が冷却の効率を下げ、これを考慮した負荷の配置が"
    "研究されている[1][2]。同じ問題は、Raspberry Pi などの小型の計算機を密に並べ、空調のない場所に置くエッジのマイクロクラスタ[3]"
    "でも起こりうる。Raspberry Pi 4B は CPU 温度が約 80℃ を超えると動作周波数を下げ(スロットリング)、処理が遅くなる。ファンを"
    "常に回せば温度は下がるが、ファンの寿命は稼働時間で表され[4]、騒音にもなる。",
    "筆者は対外発表[5]で、あるノードの発熱でほかのノードの温度が上がる現象(空間熱干渉)を、外部熱影響 H として状態に持つ"
    "カルマンフィルタで温度を予測する手法を提案した。密閉した容器では隣の負荷だけでアイドルのノードが約 12℃ 上がったが、"
    "開いたラックでは 0.5℃ 未満で、どのような配置で干渉が起こるのかは測られていなかった。温度を予測して先回りする熱管理[6][7]も"
    "1 台の内部が対象である。",
    "本研究の目的は、(1) 空間熱干渉がどの位置関係・囲いで起こるかを 8 台の実機で明らかにし、(2) 干渉を H として推定すると予測が"
    "改善するか、(3) その予測に基づくファン制御で 80℃ を超えずにファンの稼働を減らせるかを評価することである。小型の計算機を"
    "密に置くとき、どの条件で干渉を考慮した熱管理が必要かを示すことに意義がある。",
]

S12 = [
    "Raspberry Pi 4B を 8 台、10 インチラック(4U)に 2 段 × 4 列で取り付けた(図 1)。各ボードは基板面を鉛直に立て、"
    "ポート側を正面に向けて固定した。Raspberry Pi PoE+ HAT(ファン付き)を付けたノードは、ファンを制御用 PC から ON/OFF した"
    "(干渉の測定では 5 台、制御の実験では 8 台)。各ノードの CPU 温度・使用率・動作周波数・スロットリングの状態・ファンの状態を "
    "1 秒ごとに MQTT で収集し、室温(囲いの外)と囲いの中の気温を市販の温湿度計で約 1 分ごとに記録した。負荷は stress-ng で与えた。",
    "FIG:fig_rack_layout.png:図 1 (a) 1 台の向き(8 台とも同じ)、(b) 配置",
    "モデルは、室温からの温度上昇を、CPU 使用率・ファンの状態・H(周りのノードの温度の変化を一次遅れで追う量)で表す熱 RC モデル"
    "(5 秒ごと)である。カルマンフィルタで推定した 30 秒先の温度(ファン OFF のまま)が 80℃−(2σ+0.5℃) を超えたときだけ"
    "ファンを ON にする。σ は予測の標準偏差。同定と評価には別のデータを用いた。",
    "囲いは「なし」と「あり」の 2 条件とした。囲いありは、ラック全体に段ボール箱(307 × 220 × 120 mm)をかぶせ、上・左右・後ろを"
    "覆い、正面と下を開けた。干渉の測定では、1 台だけ、または下段 4 台に 2 コアの負荷を一度にかけ、負荷のないノードの上昇"
    "(同じ時間の室温の変化を引いた値)が 1℃ 以上なら干渉ありとした。この基準は測定の前に決めた。予測は 30 秒先の誤差を"
    "自ノードだけのモデルと比べ、制御は 8 台に同じ 20 分の負荷パターンをかけて、常時 ON・しきい値(75℃ で ON、70℃ で OFF)・"
    "自ノードだけの予測・提案のファン稼働率と 80℃ を超えた時間を比べた。",
]

ETHICS = ["『履修計画書と成果の要旨等を作成する際に留意すべき倫理的配慮』の(1)〜(3)のいずれにも該当しないため,該当なし"]

S13 = [
    "1 台に負荷をかけたとき、周りのノードの上昇は、囲いありでは真上・横・斜めのどれも ±0.5℃ 以内であり、1 台の排熱が"
    "隣を直接温める経路は小さかった。一方、囲いありでは負荷をかける前から上段の温度が 5〜10℃ 高く、熱は囲いの中に溜まる形で"
    "効いていた。さらに、下段 4 台に 4 コアの負荷をかけて下段のファンを回すと、上段は逆に 2〜3℃ 下がった。隣のファンの風が"
    "囲いの中の空気を動かしたためと考えられ、空間熱干渉は温める向きだけではないことが分かった。",
    "FIG:fig_res_pred.png:図 2 30 秒先の予測の誤差(上段 r1〜r3 の平均)",
    "図 2 に、30 秒先の予測の平均絶対誤差を示す。H を持つ提案のモデルは、部屋の室温だけを使う自ノードのモデルに対し、"
    "囲いなしで 0.64℃ から 0.39℃、囲いありで 0.84℃ から 0.44℃ と、誤差を 4〜5 割減らした。囲いありでの提案の精度は、"
    "囲いの中に温度計を足し、その気温を基準に使う自ノードのモデル(0.41℃)と同じで、提案はこれを追加の温度計なしで達成した。",
    "ファン制御では、囲いなし(3 台 × 3 巡)で、どの方式も 80℃ を超えず、提案のファン稼働率は 38% と常時 ON より約 6 割"
    "少なかったが、しきい値(40%)との差はほぼなかった。囲いありでは、ファンを回し続けても 80℃ 付近までしか下がらず、ファンの"
    "余力が小さい。最初の比較では制御のモデルのファンの効きが 6 台で実測と合っておらず、同定し直して比較をやり直した。"
    "やり直した比較でも、ファンを弱めた場合(提案 56%・80℃ 超過 760 秒、しきい値 63%・246 秒)、ファンの余力を見る判断を"
    "足した場合(提案 67%・431 秒、しきい値 64%・308 秒)とも、予測を使う利点は出なかった(ファンが止まっていた 1 台を除く)。"
    "シミュレーションでは、冷却の効き始めが 30 秒以上遅いと予測が有利になり、これを実機で確かめる実験を進めている。",
    "解決できなかった事項として、PoE+ HAT のファンは速く強いため、予測としきい値の差が小さい。予測の利点は冷却の効きが遅い"
    "条件で出ると考え、ファンの指令を遅らせた実機の比較、ファンの段階を予測で選ぶ制御、ノードごとに負荷をずらす条件、負荷を徐々にかける条件で評価を続ける。",
]

CHANGE = [
    "テーマ名の変更はない。計画からの主な変更は次のとおりである。(1) 計画ではファンの消費電力の削減を挙げたが、PoE+ HAT の"
    "ファンの電力は PoE の電流から区別できないほど小さかった。そのため、ファンの稼働を減らす理由をファンの寿命と騒音とした。"
    "(2) 夏季の高い外気温での評価は行わず、室温を記録して室温からの上昇分でモデル化することで、室温の変化の影響を扱った。"
    "(3) 対外発表の評価では、予測に未来の実測値を用いていたことや、同定と評価に同じデータを用いていたことが分かった。"
    "これらを直し、実機でファンを制御する閉ループで、ファン稼働率と 80℃ を超えた時間により評価した。"
    "【計画書へのコメントがあれば、その対応】",
]

REFS = [
    "[1] J. Moore, J. Chase, P. Ranganathan, R. Sharma, “Making Scheduling ‘Cool’: Temperature-Aware Workload "
    "Placement in Data Centers,” Proc. USENIX ATC, pp.61–74, 2005.",
    "[2] Q. Tang, S. K. S. Gupta, G. Varsamopoulos, “Energy-Efficient Thermal-Aware Task Scheduling for Homogeneous "
    "High-Performance Computing Data Centers: A Cyber-Physical Approach,” IEEE TPDS, Vol.19, No.11, pp.1458–1472, 2008.",
    "[3] S. J. Cox, J. T. Cox, R. P. Boardman, S. J. Johnston, M. Scott, “Iridis-pi: a low-cost, compact demonstration "
    "cluster,” Cluster Computing, pp.349–358, 2014.",
    "[4] S. J. Kim, A. Claassen, “How to Evaluate Fan Life,” Electronics Cooling, 1996.",
    "[5] 鈴木 黎映, 知念 賢一, “空間熱干渉を考慮した状態推定に基づく動的熱マージン制御手法,” 情報処理学会研究報告, "
    "Vol.2026-OS-171, No.3, 2026.",
    "[6] A. K. Coskun, T. S. Rosing, K. C. Gross, “Proactive Temperature Management in MPSoCs,” Proc. ISLPED, 2008.",
    "[7] I. Yeo, C. C. Liu, E. J. Kim, “Predictive Dynamic Thermal Management for Multicore Systems,” Proc. DAC, "
    "pp.734–739, 2008.",
]

S21 = ["専攻科【2】年次の「オペレーティングシステム」では、Linux を中心に、OS が資源を管理・制御する仕組みについて学んだ。"
       "この知識は、Linux の温度管理の仕組み(温度センサ、冷却装置の段階、動作周波数の制御)を扱い、OS の自動制御に代えて"
       "自作のプログラムからファンを制御する際に活かすことができた。また、専攻科【2】年次の「【ネットワーク工学特論Ⅱ】」で"
       "学んだネットワークの知識は、8 台のノードと制御用 PC を PoE スイッチでつなぎ、MQTT で 1 秒ごとに計測値を集める"
       "実験環境の構築に活かすことができた。"]
S22 = ["「【確率統計】」では、平均・分散・分布の考え方を学んだ。本研究では、予測の誤差を平均絶対誤差で評価し、予測の"
       "不確かさを標準偏差で表して安全の余裕(マージン)を決めており、その基礎となった。また、「【線形代数】」で学んだ"
       "ベクトルと行列の計算は、状態をベクトル、不確かさを共分散行列で表して予測と更新を繰り返すカルマンフィルタを"
       "理解する上で役立った。"]
S23 = ["「技術者倫理」では、技術者が結果を正直に示す責任について学んだ。本研究では、実験の条件と判定の基準を測定の前に"
       "決めて記録し、予想と異なる結果や手法の効果が出なかった結果も含めて報告するようにした。"]
S24 = ["4 年間で最も伸びたのは、うまくいかなかったときにめげずに原因を調べ、測り直す力である。対外発表の後に自分の評価を"
       "見直して問題を見つけ、手法を一から実装し直した。その後も、結果が予想と異なることや厳しい指摘を受けることが何度も"
       "あったが、そのたびに実験を設計し直し、結果を隠さずに書いた。"]


def drop_instruction_boxes(doc):
    """様式の説明の箱(テキストボックス)を消す。"""
    body = doc.element.body
    n = 0
    for r in list(body.iter(qn("w:r"))):
        txt = "".join(t.text or "" for t in r.iter(qn("w:t")))
        if "テキストボックスごと削除" in txt and r.getparent() is not None:
            r.getparent().remove(r)
            n += 1
    return n


JP = r"\u3000-\u30ff\u3400-\u9fff\uff00-\uffef℃%、。・「」×±→〜"


def despace(t: str) -> str:
    """日本語・℃ の前後の半角スペースを取る(Word はスペースで改行するため。先輩の要旨もスペースなし)。"""
    t = re.sub(rf"(?<=[{JP}]) +", "", t)
    return re.sub(rf" +(?=[{JP}])", "", t)


def style_run(run, size=10.5):
    """様式の本文と同じ ＭＳ 明朝。指定しないと既定の別フォントになり、太く見える。"""
    run.font.name = "ＭＳ 明朝"
    run.font.size = Pt(size)
    rpr = run._r.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rf)
    for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(k), "ＭＳ 明朝")


def fill(cell, paras, indent=True, keep_spaces=False):
    """セルの中身を paras(段落の文字列のリスト)で置き換える。'FIG:ファイル:キャプション' は図。"""
    ps = cell.paragraphs
    proto = copy.deepcopy(ps[0]._p)
    for p in ps:
        p._p.getparent().remove(p._p)
    for text in paras:
        p_el = copy.deepcopy(proto)
        for r in list(p_el.findall(qn("w:r"))):
            p_el.remove(r)
        cell._tc.append(p_el)
        p = cell.paragraphs[-1]
        if text.startswith("FIG:"):
            _, fname, cap = text.split(":", 2)
            p.alignment = 1
            p.add_run().add_picture(str(FIG / fname), width=Cm(8.5))
            cp = copy.deepcopy(p_el)
            cell._tc.append(cp)
            q = cell.paragraphs[-1]
            for r in list(q._p.findall(qn("w:r"))):
                q._p.remove(r)
            q.alignment = 1
            style_run(q.add_run(cap if keep_spaces else despace(cap)))
            continue
        if indent:
            p.paragraph_format.first_line_indent = Pt(10.5)
        for k, part in enumerate(re.split(r"(【[^】]*】)", text if keep_spaces else despace(text))):
            if not part:
                continue
            run = p.add_run(part)
            style_run(run)
            if part.startswith("【"):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig-res", default=None, help="(1-3) に入れる図(thesis/figures のファイル名)")
    a = ap.parse_args()
    doc = docx.Document(str(FORM))
    print("説明の箱を消した:", drop_instruction_boxes(doc))
    t0, t1, t2 = doc.tables
    for (r, c), v in HEAD.items():
        cell = t0.rows[r].cells[c]
        fill(cell, [v], indent=False)
    s13 = list(S13)
    if a.fig_res:  # 図を差し替えるとき
        s13 = [f"FIG:{a.fig_res}:図 2" if t.startswith("FIG:") else t for t in s13]
    for row, paras in [(1, S11), (3, S12), (5, ETHICS), (7, s13), (9, CHANGE), (11, REFS)]:
        fill(t1.rows[row].cells[0], paras, indent=row not in (5, 11), keep_spaces=row == 11)
    for row, paras in [(1, S21), (3, S22), (5, S23), (7, S24)]:
        fill(t2.rows[row].cells[0], paras)
    doc.save(str(OUT))
    print("保存:", OUT)


if __name__ == "__main__":
    main()
