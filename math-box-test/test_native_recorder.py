"""Real Tectonic regressions: line breaks, glyph geometry, and validation gates."""

import csv
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import pymupdf

from extract_mathcoords import compare_layout, extract_coordinates, paint_markers, SP_PER_BP
from instrument_latex import instrument_document


@unittest.skipUnless(shutil.which("tectonic"), "Tectonic is required for renderer regressions")
class NativeRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mathbox-regression-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def compile_pair(self, body, preamble="", width=170):
        source = (r"\documentclass{article}\usepackage{amsmath,amssymb}" + preamble
                  + rf"\setlength{{\textwidth}}{{{width}pt}}\begin{{document}}"
                  + body + r"\end{document}")
        transformed, counts = instrument_document(source)
        for name, contents in (("original", source), ("marked", transformed)):
            directory = self.root / name
            directory.mkdir()
            (directory / "main.tex").write_text(contents)
            run = subprocess.run(["tectonic", "--only-cached", "main.tex"], cwd=directory,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return self.root / "original/main.pdf", self.root / "marked/main.pdf", counts

    def extract(self, pdf):
        out = pdf.parent / "mathcoords.csv"
        report = extract_coordinates(pdf, pdf.parent / "mathrecords.csv", out)
        with out.open() as file:
            rows = [{key: int(value) for key, value in row.items()} for row in csv.DictReader(file)]
        return report, rows

    def test_inline_breaks_and_preserves_rendering(self):
        original, marked, _ = self.compile_pair(
            r"\noindent Some text preceding $a+b+c+d+e+f+g+h+i+j+k+l=m+n+o+p+q+r+s+t+u+v+w+x+y+z$ followed by text."
        )
        self.assertTrue(compare_layout(original, marked)["passed"])
        report, rows = self.extract(marked)
        self.assertEqual(report["expressions"], 1)
        self.assertGreater(report["fragments"], 1)
        self.assertEqual({row["expression_id"] for row in rows}, {1})
        self.assertEqual([row["fragment"] for row in rows], list(range(1, len(rows)+1)))
        # Distinct baselines, rather than one rectangle covering several lines.
        self.assertEqual(len({row["y"] for row in rows}), len(rows))

    def test_nested_cases_fraction_and_explicit_row_spacing(self):
        original, marked, _ = self.compile_pair(
            r"Inline $\frac{x_1^2}{y}+\sqrt{z}=\sum_{i=1}^n i$."
            r"\begin{align}f&=\begin{cases}x&x>0\\0&x\le0\end{cases}\\[2mm]g&=1\end{align}"
            r"\begin{align}x&=2\\\intertext{and}y&=3\nonumber\end{align}", width=300
        )
        self.assertTrue(compare_layout(original, marked)["passed"])
        report, rows = self.extract(marked)
        self.assertEqual(report["expressions"], 9)
        self.assertTrue(all(row["width"] > 0 and row["height"] > 0 for row in rows))

    def test_painted_rules_are_inside_bounds_without_absorbing_prose(self):
        original, marked, _ = self.compile_pair(
            r"\noindent Before $E\subset F\subset\overline{\Omega}$ after.\par "
            r"Before $\underline{x}+\sqrt{y}+\frac{x_1^2}{z}+\hat{a}$ after.\par "
            r"\noindent Before $\overline{a}+b+c+d+e+f+g+h+i+j+k+l=m+n+o+p+\underline{q}$ after."
            r"\[\overline{\Omega}+\sqrt{\frac{x^2}{y_1}}\]"
            r"Before $\overline{x}$ gap $\underline{y}$ after.",
            width=170,
        )
        self.assertTrue(compare_layout(original, marked)["passed"])
        report, rows = self.extract(marked)
        self.assertEqual(report["paint_bounds_version"], 1)
        self.assertGreater(report["paint_expanded_fragments"], 0)
        self.assertGreater(report["multi_fragment_expressions"], 0)
        with pymupdf.open(marked) as document:
            page = document[0]
            rects = [pymupdf.Rect(row["x"] / SP_PER_BP,
                                 page.rect.height - (row["y"] + row["height"]) / SP_PER_BP,
                                 (row["x"] + row["width"]) / SP_PER_BP,
                                 page.rect.height - row["y"] / SP_PER_BP) for row in rows]
            paths = [pymupdf.Rect(bounds) for op, bounds in page.get_bboxlog()
                     if op in ("fill-path", "stroke-path")]
            self.assertGreaterEqual(len(paths), 6)
            for path in paths:
                self.assertTrue(any((rect + (-0.0001, -0.0001, 0.0001, 0.0001)).contains(path)
                                    for rect in rects), (path, rects))
            for word in page.get_text("words"):
                if word[4] in ("Before", "after."):
                    self.assertFalse(any(rect.intersects(pymupdf.Rect(word[:4])) for rect in rects))
            # Prove the old annotation alone misses the first overbar.
            first = next(x for x, _, _ in page.annot_xrefs()
                         if document.xref_get_key(x, "MathBoxID")[1] == "1")
            values = document.xref_get_key(first, "Rect")[1].strip("[]").split()
            x0, y0, x1, y1 = map(float, values)
            legacy = pymupdf.Rect(x0, page.rect.height-y1, x1, page.rect.height-y0)
            self.assertFalse(legacy.contains(paths[0]))

    def test_missing_paint_marker_is_rejected(self):
        _, marked, _ = self.compile_pair(r"Text $\overline{x}$.")
        with pymupdf.open(marked) as document:
            page = document[0]
            for xref in page.get_contents():
                content = document.xref_stream(xref)
                document.update_stream(xref, content.replace(b"/MathBoxEnd1 MP", b""))
            document.saveIncr()
        with self.assertRaisesRegex(ValueError, "page-spanning paint scope"):
            self.extract(marked)
        self.assertFalse((marked.parent / "mathcoords.csv").exists())

    def test_cross_page_scope_is_rejected_instead_of_labeling_footer(self):
        original, marked, _ = self.compile_pair(
            r"\noindent Before $" + "+".join(["x"] * 100) + r"$ after.",
            preamble=r"\setlength{\textheight}{70pt}", width=100,
        )
        self.assertTrue(compare_layout(original, marked)["passed"])
        with pymupdf.open(marked) as document:
            self.assertGreater(len(document), 1)
        with self.assertRaisesRegex(ValueError, "page-spanning paint scope"):
            self.extract(marked)
        self.assertFalse((marked.parent / "mathcoords.csv").exists())

    def test_legacy_pdf_remains_readable(self):
        _, marked, _ = self.compile_pair(r"Text $x$.")
        with pymupdf.open(marked) as document:
            document.xref_set_key(document.pdf_catalog(), "MathBoxPaintVersion", "null")
            document.saveIncr()
        report, _ = self.extract(marked)
        self.assertEqual(report["expressions"], 1)
        self.assertEqual(report["paint_bounds_version"], 0)

    def test_whitespace_has_no_annotation(self):
        original, marked, counts = self.compile_pair(r"Text $ $ and \( \) then $x$.")
        self.assertTrue(compare_layout(original, marked)["passed"])
        report, _ = self.extract(marked)
        self.assertEqual(counts["empty_math_skipped"], 2)
        self.assertEqual(report["expressions"], 1)

    def test_nonempty_invisible_math_is_an_error(self):
        _, marked, _ = self.compile_pair(r"Text $\phantom{x}$.")
        with self.assertRaisesRegex(ValueError, "no geometry"):
            self.extract(marked)
        self.assertFalse((marked.parent / "mathcoords.csv").exists())

    def test_microtype_protrusion_change_is_rejected(self):
        original, marked, _ = self.compile_pair(
            r"\noindent $(0,\infty)$ a long line of text with some words that need wrapping.",
            preamble=r"\usepackage{microtype}", width=150
        )
        with self.assertRaisesRegex(ValueError, "layout/content changed"):
            compare_layout(original, marked)

    def test_added_content_is_rejected(self):
        original, marked, _ = self.compile_pair("Plain text.")
        with pymupdf.open(marked) as doc:
            doc[0].insert_text((100, 100), "unexpected")
            doc.saveIncr()
        with self.assertRaisesRegex(ValueError, "layout/content changed"):
            compare_layout(original, marked)


class PaintMarkerTests(unittest.TestCase):
    def test_strings_and_comments_are_not_markers(self):
        content = (b"(/MathBoxBegin99 MP \\(nested\\)) Tj\n"
                   b"% /MathBoxBegin98 MP\n"
                   b"<2f4d617468426f78> Tj /MathBoxBegin1 MP /MathBoxEnd1 MP")
        self.assertEqual([m.groups() for m in paint_markers(content)],
                         [(b"Begin", b"1"), (b"End", b"1")])


if __name__ == "__main__":
    unittest.main()
