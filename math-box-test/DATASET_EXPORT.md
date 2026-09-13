# Exporting the pilot dataset

From `math-box-test`, using the existing Python environment:

```bash
.venv/bin/python export_dataset.py arxiv_batch_10_instrumented_v3 math_dataset_v3 --dpi 150
```

The destination must not exist; its parent must exist. All inputs are validated
before output is created. Any failed paper, missing required file, malformed CSV,
duplicate ID, invalid page, nonpositive box, or out-of-page box stops the export.
Rotated/cropped PDFs are unsupported in this version. Errors identify the paper
and annotation when available. Rendering failures remove temporary output.

## Explicitly skip failed papers

Strict mode remains the default. To export the valid subset of a batch:

```bash
.venv/bin/python export_dataset.py arxiv_batch_10_instrumented_v4 math_dataset_v4 --skip-failed-papers
```

This excludes whole papers marked failed by the batch pipeline or rejected by
export preflight. All included papers still pass every validation check. The
report lists `excluded_papers` with `paper_id`, `stage` (`batch` or `preflight`),
and `reason`, retaining the original batch error. It also records
`attempted_paper_count`, `included_paper_count`, and `excluded_paper_count`.
The existing `paper_count` continues to mean included papers.

For the current v4 batch, expect 8 papers, 186 pages, and 9,131 boxes; papers
`2607.00123` and `2607.00132` are excluded for layout changes. Excluded papers
contribute no images, annotations, licenses, or provenance to the dataset.
Input files remain untouched. The CLI prints exclusions and exits successfully
when a nonempty valid subset is exported.

Malformed batch manifests, duplicate or unsafe paper identifiers, invalid
arguments, and destination conflicts always fail. If no papers pass, no dataset
is created. Rendering or writing failures also abort and remove temporary output;
the skip option applies only to batch and preflight failures.

The current v3 batch is expected to fail validation for paper `2607.00130`:
annotations `1041` and `1350` extend beyond the page, and `3065` has zero size.
Repairing those source annotations is a separate task. The exporter deliberately
does not clip boxes or skip invalid papers.

## Output

- `images/<paper_id>/page_0001.png`: fresh RGB renders of instrumented PDFs,
  without the audit rectangles. Image paths in COCO are relative to the dataset root.
- `annotations.json`: COCO bounding-box records, one `math` category, global
  deterministic IDs, original paper/page/annotation IDs, and source licenses.
- `export_report.json`: counts, DPI, instrumentation counters and coverage warning.
- `provenance/<paper_id>/`: unchanged metadata, instrumentation report and raw CSV.

Coordinates are floating-point `[left, top, width, height]` in image pixels.
Scaled points convert using `DPI / (72.27 * 65536)`. The vertical origin is
flipped using the PDF's physical page height, not rounded raster height; therefore
subpixel differences from the older audit overlays are possible. Descenders are
included. No box merging, class inference, segmentation or data splitting occurs.

This is an **incompletely annotated pilot**, not a training-ready coverage claim.
Headings, captions, front matter and unsupported math can be unlabelled.
Alignment-cell boxes remain separate. Pages with no recorded boxes are included
but must not be assumed to be true negative examples. Compilation and geometric
validation do not prove that instrumentation preserved the original layout.

Run tests:

```bash
.venv/bin/python -B -m unittest test_export_dataset test_instrument_latex test_batch_instrument
```

## Breakable recorder (v4)

The new recorder leaves inline math breakable and uses invisible PDF backend
annotations to obtain rectangles after TeX has laid out the page. It does not
reformat the original expressions. Empty whitespace/comment-only math is retained
but not annotated; unexpected nonempty expressions with no geometry fail extraction.

```bash
.venv/bin/python batch_instrument.py arxiv_batch_10 arxiv_batch_10_instrumented_v4
```

Choose a fresh destination for each run. The batch runner compiles an untouched
copy under each paper's `baseline/`, compares it with the instrumented PDF, and
only then extracts coordinates and renders audit images. Layout checks require
the same page geometry and glyph sequence/styles, with at most 0.02 PDF points
of glyph-origin drift. Raster differences at 150 DPI are limited to 0.02% of
channels and mean absolute channel difference 0.01/255. These small tolerances
allow PDF text-run serialization rounding; they do not allow changed line breaks.
Results are retained in `layout_report.json`.

**Known limitation:** Tectonic/XeTeX annotation specials can inhibit `microtype`
margin protrusion. Such papers fail the layout gate; the pipeline must not disable
microtype, alter expressions, or silently loosen validation to export them.

The extended CSV appends `expression_id,fragment` to the original seven columns.
`id` uniquely identifies a fragment; multiple rows may share an expression ID.
For this recorder, `y` is the lower edge, `height` is the rectangle height, and
`depth` is zero; all are still scaled points. It no longer records a TeX baseline.
The exporter accepts both formats and preserves the additional IDs in COCO,
along with `mathrecords.csv` and `layout_report.json` in provenance. New-recorder
papers require a successful layout report. Hidden PDF markers do not appear in
the page images.

For standalone extraction after compilation (and an original baseline build):

```bash
.venv/bin/python extract_mathcoords.py path/to/paper.pdf --baseline path/to/original.pdf
```

This writes `mathcoords.csv` beside the instrumented PDF, reading its
`mathrecords.csv`. Use the batch runner for the complete validated export workflow.

The additional real-TeX regression suite requires Tectonic and cached TeX packages:

```bash
.venv/bin/python -B -m unittest test_native_recorder
```
