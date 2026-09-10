"""Tests for the arXiv batch instrumentation runner."""

import json
import tempfile
import unittest
from pathlib import Path

from batch_instrument import main_file_from_metadata


class MainFileMetadataTests(unittest.TestCase):
    def make_paper(
        self, metadata: dict, main_file: str = "main.tex", create_main: bool = True
    ) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        paper = Path(temporary.name)
        if create_main:
            (paper / main_file).parent.mkdir(parents=True, exist_ok=True)
            (paper / main_file).write_text("", encoding="utf-8")
        (paper / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return paper

    def test_uses_compiled_main_file(self) -> None:
        paper = self.make_paper({"compiled_main_file": "main.tex"})
        self.assertEqual(main_file_from_metadata(paper), Path("main.tex"))

    def test_uses_only_candidate_as_fallback(self) -> None:
        paper = self.make_paper(
            {"main_file_candidates": ["paper/main.tex"]}, "paper/main.tex"
        )
        self.assertEqual(main_file_from_metadata(paper), Path("paper/main.tex"))

    def test_rejects_ambiguous_candidates(self) -> None:
        paper = self.make_paper({"main_file_candidates": ["a.tex", "b.tex"]})
        with self.assertRaisesRegex(ValueError, "does not identify one"):
            main_file_from_metadata(paper)

    def test_rejects_path_outside_paper(self) -> None:
        paper = self.make_paper(
            {"compiled_main_file": "../main.tex"}, create_main=False
        )
        with self.assertRaisesRegex(ValueError, "unsafe main file"):
            main_file_from_metadata(paper)


if __name__ == "__main__":
    unittest.main()
