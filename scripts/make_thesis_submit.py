#!/usr/bin/env python3
"""提出用の論文 PDF を作る(11/27 予備審査、レオ「黄色とか結果待ちとか言い訳がましいのがない版が今回だけ欲しい」)。
thesis/ を一時フォルダに写し、次を外してから組む。元のファイルは変えない。
  - 概要の冒頭の注記の枠
  - \\TBD{...}(中身ごと消す)
  - 結果待ちのダミーの図(\\DUMMYFIG)を含む節:囲いなし 8 台の制御、段階選択と負荷の形
  - ファンの指令を遅らせる比較の節は、シミュレーションの図と説明だけ残し、実機の部分は今後の課題の 1 文にする
出力:~/Documents/7303_鈴木黎映_論文.pdf
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "thesis"
TMP = Path("/tmp/thesis_submit")
OUT = Path.home() / "Documents" / "7303_鈴木黎映_論文.pdf"

if TMP.exists():
    shutil.rmtree(TMP)
shutil.copytree(SRC, TMP, ignore=shutil.ignore_patterns("build", "resume", "*.aux", "*.log", "*.fdb_latexmk", "*.fls"))

ab = TMP / "chapters/00_abstract.tex"
s = ab.read_text()
s = re.sub(r"\\noindent\\fbox\{\\parbox\{0\.95\\linewidth\}\{.*?\}\}\n\n\\vspace\{1em\}\n", "", s, flags=re.S)
ab.write_text(s)

ev = TMP / "chapters/07_evaluation.tex"
s = ev.read_text()
# 囲いなし 8 台の制御の節を消す
i = s.index(r"\subsection{Q3:囲いなしでの 8 台の制御")
j = s.index(r"\subsection{ファンの指令を遅らせた比較")
s = s[:i] + s[j:]
# 遅らせる比較の節:題、実機の段落、ダミーの図
s = s.replace(r"\subsection{ファンの指令を遅らせた比較(11 月 26 日夜)}", r"\subsection{冷却の効きが遅い場合(シミュレーション)}")
i = s.index("これを実機で確かめるため、")
j = s.index(r"\begin{figure}", i)
s = s[:i] + "冷却の効きが遅い条件を実機で作り、この結果を確かめることは今後の課題である(第\\ref{chap:conclusion}章)。\n\n" + s[j:]
s = re.sub(r"\\begin\{figure\}\[tb\]\s*\\centering\s*\\DUMMYFIG.*?\\end\{figure\}\n*", "", s, flags=re.S)
# 段階選択と負荷の形の節を消す(次の \section まで)
i = s.index(r"\subsection{ファンの段階を予測で選ぶ制御と、負荷の形を変えた条件}")
j = s.index(r"\section{まとめ}", i)
s = s[:i] + s[j:]
s = re.sub(r"\\TBD\{[^{}]*\}", "", s)
ev.write_text(s)

for p in (TMP / "chapters").glob("*.tex"):
    t = p.read_text()
    t2 = re.sub(r"\\TBD\{[^{}]*\}", "", t)
    if t2 != t:
        p.write_text(t2)
left = [str(p.name) for p in (TMP / "chapters").glob("*.tex") if "DUMMYFIG" in p.read_text() or "\\TBD" in p.read_text()]
if left:
    sys.exit(f"残っている:{left}")

env = {"PATH": "/Library/TeX/texbin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
r = subprocess.run(["latexmk", "main.tex"], cwd=TMP, env=env, capture_output=True, text=True)
pdf = TMP / "build" / "main.pdf"
if not pdf.exists():
    sys.exit(r.stdout[-2000:] + r.stderr[-2000:])
shutil.copy(pdf, OUT)
log = (TMP / "build" / "main.log").read_text(errors="ignore")
print("ページ:", re.search(r"Output written on .*?\((\d+) pages", log).group(1), " 未定義の参照:", log.count("undefined"))
print("保存:", OUT)
