"""Small real-PDF fixtures exercise exporter geometry and failure handling."""

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from export_dataset import FIELDS, ValidationError, export_dataset, pixel_box, preflight


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "batch"
        self.source.mkdir()
        self.entries = []

    def paper(self, name="paper", pages=2):
        directory = self.source / name
        directory.mkdir()
        with pymupdf.open() as doc:
            for _ in range(pages):
                page = doc.new_page(width=144, height=144)
                page.insert_text((24, 72), "x = 1")
            doc.save(directory / "main.pdf")
        (directory / "metadata.json").write_text(json.dumps({"id": name, "license": "example-license"}))
        (directory / "instrumentation_report.json").write_text('{"deferred": 2}')
        # One-inch baseline, with a descender and positive width.
        self.rows(directory, [[1, 1, 24*65536, round(72.27*65536), 30*65536, 10*65536, 2*65536]])
        self.entries.append({"paper": name, "main_file": "main.tex", "status": "ok", "output": "ignored/stale/path"})
        (self.source / "batch_report.json").write_text(json.dumps({"papers": self.entries}))
        return directory

    def rows(self, directory, rows):
        with (directory / "mathcoords.csv").open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def test_coordinate_conversion_and_descender(self):
        row = dict(x=65536, y=2*65536, width=3*65536, height=4*65536, depth=5*65536)
        for dpi in (72, 150, 300):
            box = pixel_box(row, 144, dpi)
            scale = dpi / 72.27
            expected = [scale, 2*dpi - 6*scale, 3*scale, 9*scale]
            for actual, wanted in zip(box, expected):
                self.assertAlmostEqual(actual, wanted)

    def test_end_to_end_deterministic_coco_and_provenance(self):
        self.paper("z", pages=11)
        self.paper("a")
        first, second = self.root / "first", self.root / "second"
        summary = export_dataset(self.source, first)
        export_dataset(self.source, second)
        self.assertEqual(summary["page_count"], 13)
        self.assertEqual(summary["annotation_count"], 2)
        self.assertEqual((first / "annotations.json").read_bytes(), (second / "annotations.json").read_bytes())
        coco = json.loads((first / "annotations.json").read_text())
        self.assertEqual(coco["images"][0]["paper_id"], "a")
        self.assertEqual([i["page"] for i in coco["images"] if i["paper_id"] == "z"], list(range(1, 12)))
        images = {i["id"]: i for i in coco["images"]}
        self.assertEqual(len(images), 13)
        for ann in coco["annotations"]:
            image = images[ann["image_id"]]
            self.assertEqual(image["paper_id"], ann["paper_id"])
            self.assertEqual(ann["category_id"], 1)
            self.assertEqual(ann["area"], ann["bbox"][2] * ann["bbox"][3])
            pix = pymupdf.Pixmap(first / image["file_name"])
            self.assertEqual((pix.width, pix.height), (image["width"], image["height"]))
            self.assertEqual((pix.width, pix.height), (300, 300))
        for name in ("metadata.json", "instrumentation_report.json", "mathcoords.csv"):
            self.assertEqual((first / "provenance/a" / name).read_bytes(), (self.source / "a" / name).read_bytes())
        self.assertEqual(len(list((first / "images").rglob("*.png"))), 13)

    def test_invalid_annotations_stop_before_output(self):
        directory = self.paper()
        valid = [1, 1, 65536, 65536, 65536, 65536, 0]
        cases = [
            [valid, valid],
            [[1, 9, 65536, 65536, 65536, 65536, 0]],
            [[1, 1, 65536, 65536, 0, 0, 0]],
            [[1, 1, 999999999, 65536, 65536, 65536, 0]],
            [["not-an-int", 1, 1, 1, 1, 1, 0]],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.rows(directory, rows)
                with self.assertRaises(ValidationError):
                    export_dataset(self.source, self.root / "out")
                self.assertFalse((self.root / "out").exists())
                self.assertFalse(list(self.root.glob(".out-*")))

    def test_missing_input_and_failed_batch(self):
        directory = self.paper()
        (directory / "main.pdf").unlink()
        with self.assertRaisesRegex(ValidationError, "paper"):
            preflight(self.source, 150)
        self.entries[0]["status"] = "failed"
        (self.source / "batch_report.json").write_text(json.dumps({"papers": self.entries}))
        with self.assertRaisesRegex(ValidationError, "did not complete"):
            preflight(self.source, 150)

    def test_fragment_identity_survives_export(self):
        directory = self.paper()
        with (directory / "mathcoords.csv").open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([*FIELDS, "expression_id", "fragment"])
            for row_id, page in ((1, 1), (2, 2)):
                writer.writerow([row_id, page, 65536, 65536, 65536, 65536, 0, 7, row_id])
        (directory / "mathrecords.csv").write_text("expression_id,kind\n7,inline\n")
        out = self.root / "out"
        export_dataset(self.source, out)
        annotations = json.loads((out / "annotations.json").read_text())["annotations"]
        self.assertEqual([row["expression_id"] for row in annotations], [7, 7])
        self.assertEqual([row["fragment"] for row in annotations], [1, 2])
        self.assertTrue((out / "provenance/paper/mathrecords.csv").is_file())

    def test_rejects_rotated_pdf(self):
        directory = self.paper()
        with pymupdf.open(directory / "main.pdf") as doc:
            doc[0].set_rotation(90)
            doc.saveIncr()
        with self.assertRaisesRegex(ValidationError, "unsupported"):
            preflight(self.source, 150)

    def test_refuses_existing_destination_and_bad_dpi(self):
        self.paper()
        destination = self.root / "out"
        destination.mkdir()
        with self.assertRaisesRegex(ValidationError, "already exists"):
            export_dataset(self.source, destination)
        for dpi in (0, -1, 1.5):
            with self.assertRaisesRegex(ValidationError, "positive integer"):
                preflight(self.source, dpi)

    def test_render_failure_cleans_partial_export(self):
        self.paper()
        with patch("export_dataset.pymupdf.Page.get_pixmap", side_effect=RuntimeError("render failed")):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                export_dataset(self.source, self.root / "out")
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(list(self.root.glob(".out-*")))

    def save_entries(self):
        (self.source / "batch_report.json").write_text(json.dumps({"papers": self.entries}))

    def test_skip_failed_papers_reports_reasons_and_exports_only_valid_inputs(self):
        self.paper("good")
        self.paper("bad")
        reason = "layout/content changed on pages [3, 6]"
        self.entries[1] = {"paper": "bad", "status": "failed", "error": reason}
        self.save_entries()
        with self.assertRaisesRegex(ValidationError, "layout/content changed"):
            export_dataset(self.source, self.root / "strict")
        self.assertFalse((self.root / "strict").exists())
        for name in ("one", "two"):
            summary = export_dataset(self.source, self.root / name, skip_failed_papers=True)
            self.assertEqual(summary["attempted_paper_count"], 2)
            self.assertEqual(summary["included_paper_count"], 1)
            self.assertEqual(summary["excluded_paper_count"], 1)
            self.assertEqual(summary["excluded_papers"], [
                {"paper_id": "bad", "stage": "batch", "reason": reason}])
            self.assertFalse((self.root / name / "images/bad").exists())
            self.assertFalse((self.root / name / "provenance/bad").exists())
            coco = json.loads((self.root / name / "annotations.json").read_text())
            self.assertEqual({image["paper_id"] for image in coco["images"]}, {"good"})
            self.assertEqual(len(coco["annotations"]), 1)
        self.assertEqual((self.root / "one/annotations.json").read_bytes(),
                         (self.root / "two/annotations.json").read_bytes())
        self.assertTrue((self.source / "bad/main.pdf").exists())

    def test_skip_preflight_failure(self):
        self.paper("good")
        bad = self.paper("bad")
        self.rows(bad, [[1, 1, 1, 1, 0, 0, 0]])
        summary = export_dataset(self.source, self.root / "out", skip_failed_papers=True)
        self.assertEqual(summary["excluded_papers"][0]["stage"], "preflight")
        self.assertIn("nonpositive box dimensions", summary["excluded_papers"][0]["reason"])

    def test_all_failed_creates_no_output(self):
        self.paper()
        self.entries[0]["status"] = "failed"
        self.save_entries()
        with self.assertRaisesRegex(ValidationError, "No papers passed"):
            export_dataset(self.source, self.root / "out", skip_failed_papers=True)
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(list(self.root.glob(".out-*")))

    def test_manifest_errors_remain_fatal_in_skip_mode(self):
        self.paper("good")
        good = self.entries[0].copy()
        for entry in (None, {"paper": "../escape", "status": "failed"},
                      {"paper": [], "status": "failed"}, good,
                      {"paper": "bad", "status": "unknown"},
                      {"paper": "bad", "status": "ok"}):
            with self.subTest(entry=entry):
                self.entries = [good, entry]
                self.save_entries()
                with self.assertRaises(ValidationError):
                    export_dataset(self.source, self.root / "out", skip_failed_papers=True)
                self.assertFalse((self.root / "out").exists())

    def test_render_failure_is_fatal_even_in_skip_mode(self):
        self.paper()
        with patch("export_dataset.pymupdf.Page.get_pixmap", side_effect=RuntimeError("render failed")):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                export_dataset(self.source, self.root / "out", skip_failed_papers=True)
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(list(self.root.glob(".out-*")))


if __name__ == "__main__":
    unittest.main()
