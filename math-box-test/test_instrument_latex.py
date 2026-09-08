"""Regression tests for the phase-one LaTeX instrumenter."""

import unittest

from instrument_latex import instrument_document, wrap_math


class WrapMathTests(unittest.TestCase):
    """Check transformations that must remain stable as the parser grows."""

    def test_inline_dollar_math(self) -> None:
        transformed, counts = wrap_math("Energy is $E=mc^2$.")
        self.assertEqual(transformed, r"Energy is \recordmath{E=mc^2}.")
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

    def test_verbatim_is_protected(self) -> None:
        source = "\\begin{verbatim}\n$x$\n\\end{verbatim}"
        transformed, counts = wrap_math(source)
        self.assertEqual(transformed, source)
        self.assertEqual(counts["inline"], 0)

    def test_align_is_deferred(self) -> None:
        source = r"\begin{align}a&=b\\c&=d\end{align}"
        transformed, counts = wrap_math(source)
        self.assertEqual(transformed, source)
        self.assertEqual(counts["deferred"], 1)

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
