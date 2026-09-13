# MathBox annotation policy

Version: 0.1 draft, 2026-09-12.

This document proposes the conventions for the next complete-label dataset.
It does not declare v4 compliant, freeze the final policy, or authorize code
changes. See [the v4 audit](ANNOTATION_AUDIT_V4.md) for observed gaps.

## Target and scope

Use one detection category, `math`, for visible mathematical notation.
The intended scope includes body text, titles, abstracts, headings, captions,
footnotes, bibliography titles, and mathematical content in tables and figures.
This broad scope is a proposed decision and exceeds current instrumenter support.

Include standalone variables and meaningful mathematical expressions, even
when the author used ordinary text rather than math delimiters. For example,
K3 used as mathematical notation should receive consistent treatment across
contexts. Ambiguous cases require review; syntax alone cannot settle them.

Exclude document navigation and identifiers: page numbers, section numbers,
equation tags, citation markers, author-affiliation markers, dates, DOI strings,
and list numbering. Plain prose and isolated numerical data entries are not
automatically mathematical expressions. A variable or formula in a table cell
is a target; the table itself is not one large math box. Figure curves, grid
lines, and tick values are not formula boxes; formula legends and axis variables
are targets.

## Box units

| Context | Proposed unit |
| --- | --- |
| Inline expression | One box for each visible line fragment; retain shared expression identity across fragments. |
| Single-line display | One box around the complete displayed expression, excluding its equation tag. |
| Multiline derivation | One box per outer visual equation row, including both sides of the relation. |
| Nested matrix or cases | Keep the entire nested structure, delimiters, and attached expression together; internal rows are not separate detection targets. |
| Independent equations side by side | Separate targets when structurally independent; never merge across document columns. |
| Inter-row prose | Exclude prose separating equation rows; math inside that prose remains an inline target. |

A cases block spanning several internal lines is an explicit exception to the
outer-row convention. Keep it as one containing expression. Fractions, sums
with limits, and stacked indices likewise remain whole structures.

For example, the left and right cells of equation (3.8) in 2607.00076 belong
to the same target row. The cases system (1.1) in 2607.00094 is one enclosing
target. An inline expression wrapping at a page margin has separate fragment
boxes rather than one rectangle spanning intervening text or whitespace.

## Bounds and punctuation

Enclose all visible parts of the target, including superscripts, subscripts,
overbars, accents, radicals, fraction rules, and delimiters. Avoid unrelated
prose, neighboring expressions, or added padding. Retain floating-point bounds
through export and apply the same render scale to images and boxes.

Mathematical punctuation and short conditions within an expression belong to
the target. Adjacent sentence punctuation and equation numbers do not. Where
inline explanatory words are embedded within one display expression, retain
them in its enclosing box; separate inter-row prose is not included. Borderline
cases should be logged with examples and resolved consistently before release.

The overbar omission confirmed in the v4 audit violates this bounds requirement
even though that box has valid dimensions and remains inside the page.

## Identity and traceability

Keep stable identities scoped to the paper and dataset version. Distinguish an
expression's line fragments from different alignment cells or independent
equations. Future row grouping must preserve its source-cell lineage; geometry
alone is not sufficient to reconstruct that relationship reliably.

Retain source metadata, license information, raw coordinates, instrumentation
reports, layout reports, and exclusion reasons. Source filename and location
mapping are desired additions, not currently complete capabilities.

## Coverage and eligibility

A complete-label image must cover every in-scope target. Compilation, layout
preservation, positive boxes, and a sampled visual review are necessary checks,
but none proves completeness alone.

When an in-scope expression cannot be labeled reliably:

1. Fix the recurring instrumentation issue and regenerate from pristine source;
   or exclude the affected paper from the next complete-label export.
2. Page-level selection is an alternative only after explicit support and a
   recorded review process exist. Current export exclusion operates on papers.
3. Do not silently remove a bad box while leaving its expression in an ordinary
   training image. An ignore region is not a solution until both the data format
   and training/evaluation code implement it explicitly.

Only mark a page as a confirmed negative after reviewing it for all in-scope
targets. Validation and test pages require full annotation review, including
omissions. Model evaluation against incomplete labels is not a completeness
check.

## Before freezing version 1.0

Implementation note (2026-09-13): the focused bounds fix now includes attributed
vector-rule ink in newly recorded fragments. It rejects ambiguous and
page-spanning paint scopes. The resulting `math_dataset_v5_bounds` export is
still a pilot, not a policy-compliant release; missing displays and inconsistent
row grouping remain. See the audit follow-up for validation and limitations.

- Confirm the scope and grouping conventions above with representative examples.
- Resolve the bounds, nested-display, and alignment-cell findings from the audit.
- Establish explicit handling for protected contexts, included content, and
  visual notation outside math mode.
- Regenerate and audit a fresh dataset version; document unsupported cases and
  resulting exclusions.
- Record any changed conventions as a policy version change and regenerate
  affected labels rather than mixing incompatible conventions.
