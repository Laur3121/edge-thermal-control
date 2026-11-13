# uplatex + dvipdfmx(先輩の論文と同じ作り方)。latexmk main.tex で build/main.pdf ができる
$latex = 'uplatex -synctex=1 -halt-on-error -interaction=nonstopmode -file-line-error %O %S';
$bibtex = 'upbibtex %O %B';
$dvipdf = 'dvipdfmx %O -o %D %S';
$makeindex = 'upmendex %O -o %D %S';
$pdf_mode = 3;
$out_dir = 'build';
# \include{chapters/...} の .aux を build/chapters/ に書けるように
system("mkdir -p build/chapters");
