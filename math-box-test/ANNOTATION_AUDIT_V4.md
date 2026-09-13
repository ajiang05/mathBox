# V4 annotation audit

Recorded: 2026-09-12. Status: initial visual audit complete; coverage certification
and instrumentation fixes remain open.

## Scope and method

Reviewed 33 existing boxed page images from all eight accepted papers in
`arxiv_batch_10_instrumented_v4/`. Selection included each paper's first,
middle, final, and highest-annotation-count page, deduplicated, followed by
three additional pages to investigate recurring issues. These are targeted
samples, not a random sample or an exhaustive expression census.

Cross-checked selected examples against pristine LaTeX sources, instrumenter
logic, COCO annotations, and PDF drawing coordinates. Re-ran read-only export
preflight: eight papers eligible and two excluded. Checked all 9,131 COCO boxes
for unique annotation IDs, finite positive dimensions, image references, and
page bounds; referenced image files exist across 186 image records.

These structural checks passed. They do not establish that boxes contain every
painted part of an expression or that all visible math has labels. Existing
layout reports were used by preflight; the batch was not recompiled for this
audit. No source, annotation, or image was modified.

## Pages inspected

Page numbers below are physical PDF pages. Images are under
`arxiv_batch_10_instrumented_v4/<paper_id>/audit/page_<page>_boxed.png`.

| Paper | Pages inspected | Main observations |
| --- | --- | --- |
| 2607.00067 | 1, 2, 3 | Wrapped inline expression has separate fragments; no obvious missing expression identified in this visual pass. Candidate for detailed review, not certified complete. |
| 2607.00076 | 1, 12, 30, 31, 59 | Alignment-cell boxes on page 12; equation (5.62) missing on page 30. Page 31 provides adjacent examples of labeled simple displays. |
| 2607.00088 | 1, 17, 19, 33 | Abstract math missing on page 1; commutative diagram unboxed and equation row split on page 17. Dense inline math and footnotes inspected on page 19. |
| 2607.00094 | 1, 13, 24, 26 | Cases equation (1.1) and aligned equation (4.1) missing; confirmed overbar outside a box on page 24; cell splitting on page 26. |
| 2607.00096 | 1, 3, 6 | Abstract O(1,1) missing; multiline/cell grouping differs; appendix heading R_t missing on page 6. |
| 2607.00097 | 1, 3, 5, 8, 10 | Abstract math missing; multiple matrix displays missing on page 8; bibliography math can be labeled. |
| 2607.00109 | 1, 2, 4, 5, 7 | Abstract and deferred displays missing; figure legend/axis math missing on page 2; cell splitting on page 4; no obvious target math on page 7. |
| 2607.00130 | 1, 11, 21, 42 | Heading math missing on page 11; array-based displays missing on page 21; plain-text K3 and math-mode K3 receive different treatment. |

## Confirmed findings

### A1: A box can omit visible mathematical marks

In [2607.00094, page 24](arxiv_batch_10_instrumented_v4/2607.00094/audit/page_24_boxed.png),
the first lemma contains an expression ending in an overlined Omega. The bar
lies above the recorded box.

This is confirmed numerically, not just by the red overlay: COCO annotation
4953, expression ID 802, has PDF-point bounds approximately
`[465.373, 75.504, 524.732, 83.385]` in top-left coordinates. The PDF draws the
overbar from x=516.853 to x=524.732 at y=73.977, with stroke width 0.436.
The bar is outside the annotation's top edge. The example demonstrates an
omission; it does not establish how frequently this happens across the dataset.

**Action:** reproduce with a small compilation fixture and investigate recorder
bounds for rules, accents, radicals, and nested structures. Validate actual
painted extents without altering layout. Do not use arbitrary padding or
manual per-expression edits as the fix.

### A2: Nested displays are deferred wholesale

- [2607.00076, page 30](arxiv_batch_10_instrumented_v4/2607.00076/audit/page_30_boxed.png):
  equation (5.62) is absent from the labels. Original
  `cyl_t2_arxiv_v1.tex`, lines 1748–1776, uses `equation` containing `aligned`.
- [2607.00094, page 1](arxiv_batch_10_instrumented_v4/2607.00094/audit/page_1_boxed.png):
  equation (1.1) is absent. Original `Preprint.tex`, lines 249–256, uses
  `equation` containing `cases`.
- The same paper's page 24 equation (4.1) uses `equation` containing `aligned`
  at original lines 1885–1891 and is also absent.
- [2607.00097, page 8](arxiv_batch_10_instrumented_v4/2607.00097/audit/page_8_boxed.png)
  contains multiple unboxed matrix displays, including (2.11) and (2.12).
- [2607.00130, page 21](arxiv_batch_10_instrumented_v4/2607.00130/audit/page_21_boxed.png)
  has unboxed displays defining j_1(h_X) and j_2(h_X), using arrays inside
  dollar-delimited displays. Similar nested material can be boxed inline.

`has_alignment_tokens` checks for alignment tokens anywhere in a display body,
so nested alignment tokens cause simple-display handling to defer the entire
expression. Supporting top-level `align` alone does not resolve these cases.

**Action:** distinguish nested structures from outer rows; support common
nested displays under the annotation policy and retain explicit rejection for
unsupported cases.

### A3: The current grouping is not consistently a visual equation row

[2607.00076, page 12](arxiv_batch_10_instrumented_v4/2607.00076/audit/page_12_boxed.png)
shows separate left- and right-hand boxes in equations (3.8)–(3.10).
Similar splits occur on 2607.00096 page 3, 2607.00109 page 4, and
2607.00094 page 26. The instrumenter explicitly records top-level alignment
cells separately.

**Action:** retain structural row identity and group only cells belonging to
the same intended target. Do not merge by proximity across columns or unrelated
equations. Inline line-break fragments must remain separate boxes.

### A4: Protected contexts leave real math unlabeled

Examples include abstract math in 2607.00088, 2607.00096, 2607.00097, and
2607.00109 on page 1; the R_t heading in 2607.00096 page 6; and the nu-star
heading in 2607.00130 page 11. Original heading commands occur at
`2607.00096/main.tex:327` and `2607.00130/arxiv_version.tex:578`.

Not all abstracts are skipped: 2607.00130 has labeled abstract math. Behavior
depends on source position relative to title processing. Protected-command
counts are not counts of missed expressions: they also include reference keys
and arguments without visible math.

**Action:** treat these as coverage gaps, not background. Either implement safe
recording or exclude affected pages/papers from a complete-label release.

### A5: Included content and graphics need an explicit scope

[2607.00109, page 2](arxiv_batch_10_instrumented_v4/2607.00109/audit/page_2_boxed.png)
contains unboxed plot-legend formulas and an axis variable. The main source
inputs `graph.tex` at line 175; only the main file is transformed. A static scan
of accepted main files found explicit input commands in this paper for the
graph and bibliography. This is not a complete TeX dependency analysis.

The same paper also has missing `alignat` displays on page 1 and `gather`
displays on page 5. Recursive processing alone would not fix those gaps.

**Action:** define figure/table math as a target or explicitly restrict the
dataset scope; instrument supported included content and record unresolved
coverage. Do not silently turn unannotated regions into negative examples.

### A6: Visual notation is not equivalent to LaTeX math mode

In 2607.00130, K3 appears both as plain text and inside math delimiters. Original
line 190 contains both forms; page 1 shows inconsistent box treatment. Page 42
also contains differently treated K3 occurrences in bibliography titles.

**Action:** define the visual target independently of author syntax. If the
instrumenter cannot cover an in-scope notation reliably, flag it for review or
exclude the affected material. Do not claim all visible math is recoverable by
finding dollar signs.

## Disposition and next work

- Keep the existing v4 export marked **pilot/smoke-test only**. Do not promote
  it to a complete-label training or evaluation release based on this audit.
- Seven papers have observed omissions or grouping problems. The remaining
  paper, 2607.00067, needs detailed verification before any certification.
- Preserve the two existing layout exclusions, 2607.00123 and 2607.00132.
- No precision, recall, or coverage percentage is reported: a complete manual
  reference set has not been enumerated.
- Prioritize A1 bounds, A2 nested displays, and A3 grouping; then address A4–A6
  through support or explicit data eligibility rules.
- Recompile and regenerate into a fresh dataset version after approved code
  changes, repeat the structural checks, and re-audit these exact examples.
- Review all target expressions in held-out evaluation pages before freezing
  splits. Postpone the 100-candidate collection milestone until the policy and
  recurring defects are addressed.

See [the labeling policy draft](ANNOTATION_POLICY.md) for the intended targets.

## Bounds-fix follow-up — 2026-09-13

The focused bounds fix is implemented in `instrument_latex.py` and
`extract_mathcoords.py`, with real compilation regressions in
`test_native_recorder.py`. New recordings contain non-rendering marked-content
points and `/MathBoxPaintVersion 1` metadata. Extraction attributes vector paths
to their expression on an in-memory PDF copy and expands the appropriate native
fragment bounds to include their painted extents. It does not add arbitrary
padding, modify source expressions, or group alignment cells.

The audited overbar is now contained: expression 802 in 2607.00094 page 24 has
PDF-point bounds approximately `[465.373, 73.759, 524.950, 83.385]`. Its overbar's
painted bounds are approximately `[516.635, 73.759, 524.950, 74.195]`.
This was checked numerically and on the regenerated boxed page.

Fresh artifacts:

- `arxiv_batch_10_instrumented_v5_bounds/`: all ten originals attempted;
  seven passed layout and extraction checks.
- `math_dataset_v5_bounds/`: seven papers, 144 pages, 5,793 boxes at 150 DPI.
- 236 fragments expanded to include attributed vector ink: 21 in 2607.00076,
  103 in 2607.00088, 107 in 2607.00094, and five in 2607.00109. This count is
  not a count of previously missing expressions or a coverage metric.

The two existing layout failures remain excluded. Paper 2607.00130 is also
excluded: expression 1650 spans pages 20–21. Inspection found the original
backend annotation includes the page-20 footer number as an extra fragment.
The new extractor rejects page-spanning marker scopes because page furniture
can interrupt the expression's drawing sequence. It does not guess which
operations to retain. Nested scopes, missing markers, ambiguous fragment
attribution, inline PDF images, and unsupported resource structures also fail
explicitly rather than produce guessed bounds.

Validation: all 52 tests passed. Compilation regressions cover overbars,
underlines, radicals, fractions, accents/superscripts within the fixture,
inline wrapping, display math, neighboring prose, malformed markers,
cross-page rejection, legacy PDFs, and existing layout gates. Export integrity
checks passed for all 144 image records and 5,793 boxes. The real batch passed
the unchanged layout checks for all seven included papers.

Legacy v4 PDFs remain readable, but lack paint attribution metadata; rerunning
extraction on them does not repair their bounds. Fresh instrumentation and
compilation are required. Reports now record `paint_bounds_version` and
`paint_expanded_fragments`.

This resolves the demonstrated vector-rule omission for accepted recordings,
not all annotation quality concerns. Glyph bounds still originate from the
native annotations; arbitrary graphics, clipping, and complete glyph-ink
coverage have not been certified. A2–A6 remain open, and the new export remains
a pilot. Missing nested displays are the next proposed implementation task.
