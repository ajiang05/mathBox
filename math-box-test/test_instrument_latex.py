"""Regression tests for the phase-one LaTeX instrumenter."""

import unittest

from instrument_latex import instrument_document, wrap_math


class WrapMathTests(unittest.TestCase):
    """Check transformations that must remain stable as the parser grows."""

    def test_inline_dollar_math(self) -> None:
        transformed, counts = wrap_math("Energy is $E=mc^2$.")
        self.assertEqual(transformed, r"Energy is \recordmath{E=mc^2}.")
        self.assertEqual(counts["inline"], 1)

    def test_nested_cases_remain_in_one_box(self) -> None:
        cases = r"\begin{cases}x & x>0\\0 & x\leq0\end{cases}"
        transformed, counts = wrap_math(
            r"\begin{align}f &= " + cases + r"\\g &= 1\end{align}"
        )
        self.assertIn(cases, transformed)
        self.assertEqual(counts["equation"], 4)

    def test_intertext_remains_between_rows(self) -> None:
        for command in ("intertext", "shortintertext"):
            with self.subTest(command=command):
                directive = "\\" + command + "{and {also}}"
                transformed, counts = wrap_math(
                    r"\begin{align}a&=b\\" + directive + r"c&=d\end{align}"
                )
                self.assertIn(r"\\" + directive + r"\recorddisplay{c", transformed)
                self.assertEqual(counts["equation"], 4)

    def test_moving_arguments_are_preserved(self) -> None:
        for command in (
            r"\subsection{Symplectic $K3$ surfaces}",
            r"\section*{An {$x$} title}",
            r"\caption[Short {$x\in[0,1]$}]{Long $y$ caption}",
        ):
            with self.subTest(command=command):
                transformed, counts = wrap_math(command + " Body $z$.")
                self.assertEqual(transformed, command + r" Body \recordmath{z}.")
                self.assertEqual(counts["moving_arguments_skipped"], 1)
                self.assertEqual(counts["inline"], 1)

    def test_parenthesized_inline_math(self) -> None:
        transformed, counts = wrap_math(r"Value \(x_1\).")
        self.assertEqual(transformed, r"Value \recordmath{x_1}.")
        self.assertEqual(counts["inline"], 1)

    def test_display_delimiters(self) -> None:
        transformed, counts = wrap_math(r"\[x^2\] $$y^2$$")
        self.assertEqual(
            transformed,
            r"\[\recorddisplay{x^2}\] \[\recorddisplay{y^2}\]",
        )
        self.assertEqual(counts["display"], 2)

    def test_comments_are_unchanged(self) -> None:
        transformed, counts = wrap_math("% $not math$\n$x$")
        self.assertEqual(transformed, "% $not math$\n" + r"\recordmath{x}")
        self.assertEqual(counts["inline"], 1)

    def test_escaped_dollar_is_unchanged(self) -> None:
        transformed, counts = wrap_math(r"Cost: \$5 and $x$.")
        self.assertEqual(transformed, r"Cost: \$5 and \recordmath{x}.")
        self.assertEqual(counts["inline"], 1)

    def test_texorpdfstring_is_protected(self) -> None:
        source = r"\texorpdfstring{$R_t$}{Rt}"
        transformed, counts = wrap_math(source)
        self.assertEqual(transformed, source)
        self.assertEqual(counts["protected"], 1)

    def test_label_and_reference_keys_are_preserved(self) -> None:
        for command in (
            "label", "ref", "eqref", "pageref", "autoref", "nameref",
            "cref", "Cref", "cpageref", "Cpageref", "ref*", "autoref*",
        ):
            with self.subTest(command=command):
                source = "\\" + command + "{thm: projective $K3$ {G} polarized}"
                transformed, counts = wrap_math(source + " Body $K3$.")
                self.assertEqual(transformed, source + r" Body \recordmath{K3}.")
                self.assertEqual(counts["protected"], 1)
                self.assertEqual(counts["inline"], 1)

    def test_reference_prefix_does_not_protect_other_commands(self) -> None:
        transformed, counts = wrap_math(r"\reference{$x$}")
        self.assertEqual(transformed, r"\reference{\recordmath{x}}")
        self.assertEqual(counts["protected"], 0)

    def test_multline_rows_are_instrumented(self) -> None:
        source = "\\begin{multline}\nfirst \\\\\nsecond\n\\end{multline}"
        transformed, counts = wrap_math(source)
        self.assertEqual(
            transformed,
            "\\begin{multline}\n\\recorddisplay{first\n} \\\\\n"
            "\\recorddisplay{second\n}\n\\end{multline}",
        )
        self.assertEqual(counts["equation"], 2)
        self.assertEqual(counts["deferred"], 0)

    def test_align_cells_are_instrumented(self) -> None:
        source = "\\begin{align}\na &= b \\\\\nc &= d\n\\end{align}"
        transformed, counts = wrap_math(source)
        self.assertEqual(
            transformed,
            "\\begin{align}\n\\recorddisplay{a\n} &\\recorddisplay{= b\n} \\\\\n"
            "\\recorddisplay{c\n} &\\recorddisplay{= d\n}\n\\end{align}",
        )
        self.assertEqual(counts["equation"], 4)

    def test_starred_multiline_environment_is_supported(self) -> None:
        transformed, counts = wrap_math(
            r"\begin{align*}x &= y\end{align*}"
        )
        self.assertEqual(
            transformed,
            "\\begin{align*}\\recorddisplay{x\n} &\\recorddisplay{= y\n}\\end{align*}",
        )
        self.assertEqual(counts["equation"], 2)

    def test_comments_do_not_split_multiline_math(self) -> None:
        source = "\\begin{multline}x % fake \\\\\n y \\\\\n z\\end{multline}"
        transformed, counts = wrap_math(source)
        self.assertIn("% fake \\\\\n y", transformed)
        self.assertEqual(counts["equation"], 2)

    def test_labels_and_nonumber_are_preserved(self) -> None:
        source = r"\begin{align}\label{eq:x}x &= y\nonumber\end{align}"
        transformed, counts = wrap_math(source)
        self.assertIn(r"\label{eq:x}", transformed)
        self.assertIn(r"\nonumber", transformed)
        self.assertNotIn(r"\recorddisplay{= y\nonumber", transformed)
        self.assertEqual(counts["equation"], 2)

    def test_explicit_tag_stays_outside_recorded_cell(self) -> None:
        source = r"\begin{align*}x &= y\tag{A.1}\end{align*}"
        transformed, _ = wrap_math(source)
        self.assertIn("\\recorddisplay{= y\n}\\tag{A.1}", transformed)

    def test_nonumber_on_own_line_does_not_create_paragraph(self) -> None:
        transformed, _ = wrap_math(
            "\\begin{align*}a &= b\n    \\nonumber\\\\c &= d\\end{align*}"
        )
        self.assertIn("\\recorddisplay{= b\n}\\nonumber", transformed)
        self.assertNotRegex(transformed, r"\n\s*\n")

    def test_verbatim_is_protected(self) -> None:
        source = "\\begin{verbatim}\n$x$\n\\end{verbatim}"
        transformed, counts = wrap_math(source)
        self.assertEqual(transformed, source)
        self.assertEqual(counts["inline"], 0)

    def test_align_is_not_deferred(self) -> None:
        source = r"\begin{align}a&=b\\c&=d\end{align}"
        transformed, counts = wrap_math(source)
        self.assertEqual(
            transformed,
            "\\begin{align}\\recorddisplay{a\n}&\\recorddisplay{=b\n}"
            "\\\\\\recorddisplay{c\n}&\\recorddisplay{=d\n}\\end{align}",
        )
        self.assertEqual(counts["deferred"], 0)

    def test_simple_equation_is_wrapped(self) -> None:
        source = r"\begin{equation}x=1\end{equation}"
        transformed, counts = wrap_math(source)
        self.assertIn(r"\recorddisplay{x=1}", transformed)
        self.assertEqual(counts["equation"], 1)

    def test_frontmatter_before_maketitle_is_unchanged(self) -> None:
        source = (
            r"\documentclass{article}\begin{document}"
            r"\begin{abstract}$x$\end{abstract}\maketitle Body $y$."
        )
        transformed, counts = instrument_document(source)
        self.assertIn(r"\begin{abstract}$x$\end{abstract}", transformed)
        self.assertIn(r"Body \recordmath{y}.", transformed)
        self.assertEqual(counts["frontmatter_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
