"""Create an instrumented copy of a LaTeX paper for math-box labels.

Phase one supports inline math and single-block display math. Multi-line
alignment environments are reported but left unchanged until their individual
rows can be measured without changing the document layout.

Example:
    python instrument_latex.py \
        arxiv_sample_new/2607.00096 \
        arxiv_sample_instrumented/2607.00096 \
        --main main.tex
"""

import argparse
import json
import re
import shutil
from pathlib import Path


RECORDER = r"""
% mathBox automatic coordinate recorder
\usepackage{zref-savepos}
\usepackage{zref-abspage}
\newsavebox{\mathboxrecordbox}
\newwrite\mathcoords
\immediate\openout\mathcoords=mathcoords.csv
\immediate\write\mathcoords{id,page,x,y,width,height,depth}
\newcounter{mathrecordid}
\makeatletter
\zref@addprop{savepos}{abspage}
\newcommand{\recordmath}[1]{%
  \ifmeasuring@ #1%
  \else
    \stepcounter{mathrecordid}%
    \sbox{\mathboxrecordbox}{$#1$}%
    \edef\mathrecordlabel{math-record-\themathrecordid}%
    \leavevmode\zsavepos{\mathrecordlabel}%
    \immediate\write\mathcoords{%
      \themathrecordid,
      \zref@extractdefault{\mathrecordlabel}{abspage}{0},
      \zposx{\mathrecordlabel},\zposy{\mathrecordlabel},
      \number\wd\mathboxrecordbox,\number\ht\mathboxrecordbox,
      \number\dp\mathboxrecordbox}%
    \usebox{\mathboxrecordbox}%
  \fi}
\makeatother
\newcommand{\recorddisplay}[1]{\recordmath{\displaystyle #1}}
\AtEndDocument{\immediate\closeout\mathcoords}
% end mathBox automatic coordinate recorder
"""

VERBATIM_ENVIRONMENTS = ("verbatim", "verbatim*", "lstlisting", "minted")
DEFERRED_ENVIRONMENTS = (
    "align", "align*", "alignat", "alignat*", "flalign", "flalign*",
    "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*",
)
EQUATION_ENVIRONMENTS = ("equation", "equation*", "displaymath")
PROTECTED_COMMANDS = (r"\texorpdfstring",)


def escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def find_unescaped(text: str, token: str, start: int) -> int:
    position = text.find(token, start)
    while position >= 0 and escaped(text, position):
        position = text.find(token, position + len(token))
    return position


def has_alignment_tokens(body: str) -> bool:
    uncommented = re.sub(r"(?<!\\)%[^\n]*", "", body)
    return "&" in uncommented or re.search(r"(?<!\\)\\\\", uncommented) is not None


def braced_command_end(source: str, start: int, arguments: int) -> int | None:
    """Return the end of a command with balanced braced arguments."""
    position = start
    for _ in range(arguments):
        while position < len(source) and source[position].isspace():
            position += 1
        if position >= len(source) or source[position] != "{":
            return None
        depth = 1
        position += 1
        while position < len(source) and depth:
            if source[position] == "{" and not escaped(source, position):
                depth += 1
            elif source[position] == "}" and not escaped(source, position):
                depth -= 1
            position += 1
        if depth:
            return None
    return position


def wrap_math(source: str) -> tuple[str, dict[str, int]]:
    counts = {
        "inline": 0, "display": 0, "equation": 0,
        "deferred": 0, "protected": 0,
    }
    output: list[str] = []
    index = 0

    while index < len(source):
        # Preserve comments exactly and do not interpret math-like text in them.
        if source[index] == "%" and not escaped(source, index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end + 1
            output.append(source[index:end])
            index = end
            continue

        protected = False
        for command in PROTECTED_COMMANDS:
            if source.startswith(command, index):
                end = braced_command_end(source, index + len(command), 2)
                if end is not None:
                    output.append(source[index:end])
                    counts["protected"] += 1
                    index = end
                    protected = True
                    break
        if protected:
            continue

        matched_environment = False
        for environment in VERBATIM_ENVIRONMENTS + DEFERRED_ENVIRONMENTS + EQUATION_ENVIRONMENTS:
            begin = rf"\begin{{{environment}}}"
            if not source.startswith(begin, index):
                continue
            end_token = rf"\end{{{environment}}}"
            end_start = source.find(end_token, index + len(begin))
            if end_start < 0:
                output.append(source[index:])
                return "".join(output), counts
            end = end_start + len(end_token)
            body = source[index + len(begin):end_start]

            if environment in EQUATION_ENVIRONMENTS and not has_alignment_tokens(body):
                output.extend((begin, "\n\\recorddisplay{", body, "}\n", end_token))
                counts["equation"] += 1
            else:
                output.append(source[index:end])
                if environment in DEFERRED_ENVIRONMENTS or (
                    environment in EQUATION_ENVIRONMENTS and has_alignment_tokens(body)
                ):
                    counts["deferred"] += 1
            index = end
            matched_environment = True
            break
        if matched_environment:
            continue

        if source.startswith("$$", index) and not escaped(source, index):
            end = find_unescaped(source, "$$", index + 2)
            if end >= 0:
                body = source[index + 2:end]
                if not has_alignment_tokens(body):
                    output.extend(("\\[\\recorddisplay{", body, "}\\]"))
                    counts["display"] += 1
                else:
                    output.append(source[index:end + 2])
                    counts["deferred"] += 1
                index = end + 2
                continue

        if source.startswith(r"\[", index) and not escaped(source, index):
            end = find_unescaped(source, r"\]", index + 2)
            if end >= 0:
                body = source[index + 2:end]
                if not has_alignment_tokens(body):
                    output.extend((r"\[\recorddisplay{", body, r"}\]"))
                    counts["display"] += 1
                else:
                    output.append(source[index:end + 2])
                    counts["deferred"] += 1
                index = end + 2
                continue

        if source.startswith(r"\(", index) and not escaped(source, index):
            end = find_unescaped(source, r"\)", index + 2)
            if end >= 0:
                output.extend(("\\recordmath{", source[index + 2:end], "}"))
                counts["inline"] += 1
                index = end + 2
                continue

        if source[index] == "$" and not escaped(source, index):
            end = find_unescaped(source, "$", index + 1)
            if end >= 0:
                output.extend(("\\recordmath{", source[index + 1:end], "}"))
                counts["inline"] += 1
                index = end + 1
                continue

        output.append(source[index])
        index += 1

    return "".join(output), counts


def instrument_document(source: str) -> tuple[str, dict[str, int]]:
    document_start = source.find(r"\begin{document}")
    if document_start < 0:
        raise ValueError("main file has no \\begin{document}")
    insertion = document_start
    body_start = document_start + len(r"\begin{document}")
    before = source[:insertion]
    body = source[body_start:]
    instrumented_body, counts = wrap_math(body)
    return before + RECORDER + "\n\\begin{document}" + instrumented_body, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--main", required=True, type=Path)
    args = parser.parse_args()

    if args.destination.exists():
        raise SystemExit(f"Destination already exists: {args.destination}")
    source_main = args.source / args.main
    if not source_main.is_file():
        raise SystemExit(f"Main file not found: {source_main}")

    shutil.copytree(args.source, args.destination)
    destination_main = args.destination / args.main
    original = destination_main.read_text(encoding="utf-8")
    instrumented, counts = instrument_document(original)
    destination_main.write_text(instrumented, encoding="utf-8")

    report = {"main_file": str(args.main), **counts}
    (args.destination / "instrumentation_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
