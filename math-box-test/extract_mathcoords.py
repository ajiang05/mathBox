"""Extract line-fragment geometry recorded by Tectonic's PDF backend."""

import argparse
from collections import Counter
import csv
import json
import math
import re
from pathlib import Path

import pymupdf
import numpy as np


FIELDS = ("id", "page", "x", "y", "width", "height", "depth", "expression_id", "fragment")
SP_PER_BP = 65536 * 72.27 / 72


def paint_markers(contents):
    """Read our marked-content points outside PDF strings and comments.

    Inline images have arbitrary binary payloads. Fail closed rather than
    interpreting their bytes as expression markers.
    """
    masked = bytearray(contents)
    index = 0
    while index < len(contents):
        start = index
        char = contents[index]
        if char == 37:  # comment
            while index < len(contents) and contents[index] not in (10, 13):
                index += 1
        elif char == 40:  # balanced literal string, including escaped parentheses
            depth = 1
            index += 1
            while index < len(contents) and depth:
                char = contents[index]
                if char == 92:
                    index += 2
                    continue
                depth += (char == 40) - (char == 41)
                index += 1
            if depth:
                raise ValueError("unterminated PDF string in paint metadata")
        elif contents[index:index + 2] == b"<<":
            index += 2
            continue
        elif char == 60:  # hexadecimal string
            end = contents.find(b">", index + 1)
            if end < 0:
                raise ValueError("unterminated PDF hex string in paint metadata")
            index = end + 1
        else:
            index += 1
            continue
        masked[start:index] = b" " * (index - start)
    if re.search(rb"(?<![^\s])BI(?=\s)", masked):
        raise ValueError("inline PDF images are unsupported for paint attribution")
    return list(re.finditer(
        rb"/MathBox(Begin|End)([1-9][0-9]*)\s+MP(?=[\s/<>\[\]()]|$)", masked
    ))


def painted_rules(document, expected):
    """Attribute vector ink using markers, never spatial proximity to prose.

    On an in-memory copy only, turn marked-content points into visible optional
    content groups so MuPDF reports the owning expression for each path. The
    published PDF is untouched. Page-spanning or nested marker scopes are
    rejected because shipout furniture can occur inside those scopes.
    """
    kind, version = document.xref_get_key(document.pdf_catalog(), "MathBoxPaintVersion")
    if kind == "null":
        return {}  # Legacy PDFs have no trustworthy paint ownership metadata.
    if kind != "int" or version != "1":
        raise ValueError("unsupported MathBox paint metadata version")
    rules = {}
    seen = set()
    with pymupdf.open(stream=document.tobytes(), filetype="pdf") as tagged:
        for number, page in enumerate(tagged, 1):
            contents = page.read_contents()
            markers = paint_markers(contents)
            active = None
            chunks = []
            offset = 0
            properties = {}
            for marker in markers:
                event, value = marker.groups()
                expression = int(value)
                if expression not in expected:
                    raise ValueError(f"page {number}: unknown paint expression {expression}")
                chunks.append(contents[offset:marker.start()])
                if event == b"Begin":
                    if active is not None or expression in seen:
                        raise ValueError(f"expression {expression}: nested/duplicate paint scope")
                    seen.add(expression)
                    active = expression
                    name = f"MathBoxPaint{expression}"
                    ocg = tagged.add_ocg(name)
                    properties[name] = ocg
                    chunks.append(f" /OC /{name} BDC ".encode())
                else:
                    if active != expression:
                        raise ValueError(f"expression {expression}: unmatched/page-spanning paint scope")
                    active = None
                    chunks.append(b" EMC ")
                offset = marker.end()
            if active is not None:
                raise ValueError(f"expression {active}: page-spanning paint scope is unsupported")
            chunks.append(contents[offset:])
            if not markers:
                continue
            # Give this page its own resource dictionary, preserving existing
            # resources and property names, including indirect dictionaries.
            resource_kind, resource = tagged.xref_get_key(page.xref, "Resources")
            if resource_kind == "xref":
                resource = tagged.xref_object(int(resource.split()[0]))
            elif resource_kind != "dict":
                raise ValueError(f"page {number}: unsupported inherited PDF resources")
            resource_xref = tagged.get_new_xref()
            tagged.update_object(resource_xref, resource)
            prop_kind, prop = tagged.xref_get_key(resource_xref, "Properties")
            if prop_kind == "xref":
                prop = tagged.xref_object(int(prop.split()[0]))
            elif prop_kind == "null":
                prop = "<< >>"
            elif prop_kind != "dict":
                raise ValueError(f"page {number}: invalid PDF properties")
            tagged.xref_set_key(resource_xref, "Properties", prop)
            for name, ocg in properties.items():
                if tagged.xref_get_key(resource_xref, f"Properties/{name}")[0] != "null":
                    raise ValueError(f"page {number}: conflicting paint property {name}")
                tagged.xref_set_key(resource_xref, f"Properties/{name}", f"{ocg} 0 R")
            tagged.xref_set_key(page.xref, "Resources", f"{resource_xref} 0 R")
            stream = tagged.get_new_xref()
            tagged.update_object(stream, "<< >>")
            tagged.update_stream(stream, b"".join(chunks))
            page.set_contents(stream)
            for operation, bounds, layer in page.get_bboxlog(layers=True):
                if layer not in properties:
                    continue
                expression = int(layer.removeprefix("MathBoxPaint"))
                if operation in ("fill-path", "stroke-path"):
                    if not all(math.isfinite(value) for value in bounds):
                        raise ValueError(f"expression {expression}: invalid painted bounds")
                    rules.setdefault((expression, number), []).append(bounds)
    if seen != set(expected):
        raise ValueError(f"missing paint scopes: {sorted(set(expected) - seen)}")
    return rules


def include_painted_rules(boxes, rules, page_heights):
    """Expand a fragment only for ink explicitly owned by its expression."""
    original = list(boxes)
    groups = {}
    for index, box in enumerate(original):
        groups.setdefault(box[:2], []).append(index)
    for key, paths in rules.items():
        for left, top, right, bottom in paths:
            height = page_heights[key[1]]
            y0, y1 = height - bottom, height - top
            candidates = []
            for index in groups.get(key, []):
                _, _, x0, b0, x1, b1 = original[index]
                if right > x0 and left < x1:
                    gap = max(b0 - y1, y0 - b1, 0)
                    candidates.append((gap, index))
            candidates.sort()
            if not candidates or (len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 1e-6):
                raise ValueError(f"expression {key[0]}: ambiguous painted-rule fragment")
            index = candidates[0][1]
            expression, page, x0, b0, x1, b1 = boxes[index]
            boxes[index] = (expression, page, min(x0, left), min(b0, y0),
                            max(x1, right), max(b1, y1))


def compare_layout(original, instrumented, dpi=150):
    """Reject layout changes, allowing only subpixel PDF serialization rounding.

    Markers flush PDF text runs, which changes coordinate rounding. Require
    identical glyph identities/styles, <= .02 bp origin drift, and a very small
    raster difference. A line break, omitted symbol or protrusion shift fails.
    """
    max_drift = max_fraction = max_mean = 0.0
    exact = True
    with pymupdf.open(original) as before, pymupdf.open(instrumented) as after:
        if len(before) != len(after):
            raise ValueError(f"layout changed: page count {len(before)} -> {len(after)}")
        changed = []
        for number, (left, right) in enumerate(zip(before, after), 1):
            if (left.mediabox, left.cropbox, left.rotation) != (right.mediabox, right.cropbox, right.rotation):
                changed.append(number)
                continue
            a = left.get_pixmap(dpi=dpi, annots=False)
            b = right.get_pixmap(dpi=dpi, annots=False)
            if (a.width, a.height) != (b.width, b.height):
                changed.append(number)
                continue
            def glyphs(page):
                return [(span["font"], span["size"], span["color"], span["type"],
                         char[0], char[1], char[2])
                        for span in page.get_texttrace() for char in span["chars"]]
            first, second = glyphs(left), glyphs(right)
            if len(first) != len(second) or any(x[:-1] != y[:-1] for x, y in zip(first, second)):
                changed.append(number)
                continue
            drift = max((max(abs(v-w) for v, w in zip(x[-1], y[-1]))
                         for x, y in zip(first, second)), default=0)
            max_drift = max(max_drift, drift)
            fraction = mean = 0.0
            if a.digest != b.digest:
                exact = False
                delta = np.abs(np.frombuffer(a.samples, dtype=np.uint8).astype(np.int16)
                               - np.frombuffer(b.samples, dtype=np.uint8).astype(np.int16))
                fraction, mean = float(np.mean(delta != 0)), float(np.mean(delta))
                max_fraction, max_mean = max(max_fraction, fraction), max(max_mean, mean)
            if drift > 0.02 or fraction > 0.0002 or mean > 0.01:
                changed.append(number)
        if changed:
            raise ValueError(f"layout/content changed on pages {changed}")
        return {"pages": len(before), "comparison_dpi": dpi, "pixel_identical": exact,
                "max_glyph_drift_bp": max_drift, "max_changed_channel_fraction": max_fraction,
                "max_mean_channel_difference": max_mean, "passed": True}


def extract_coordinates(pdf, records, output):
    """Keep one row per backend fragment; never clip or discard missing geometry."""
    expected = {}
    with Path(records).open(newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != ["expression_id", "kind"]:
            raise ValueError("invalid mathrecords.csv header")
        for record in reader:
            expression_id = int(record["expression_id"])
            if expression_id <= 0 or expression_id in expected:
                raise ValueError(f"duplicate/invalid expression ID {expression_id}")
            expected[expression_id] = record["kind"]
    boxes = []
    errors = []
    with pymupdf.open(pdf) as document:
        paint_version = document.xref_get_key(document.pdf_catalog(), "MathBoxPaintVersion")[1]
        rules = painted_rules(document, expected)
        for page_number, page in enumerate(document, 1):
            if page.rotation or page.cropbox != page.mediabox or page.mediabox.x0 or page.mediabox.y0:
                raise ValueError(f"page {page_number}: unsupported PDF geometry")
            for xref, _, _ in page.annot_xrefs():
                key_type, key_value = document.xref_get_key(xref, "MathBoxID")
                if key_type == "null":
                    continue
                expression_id = int(key_value)
                if expression_id not in expected:
                    errors.append(f"page {page_number}: unknown expression {expression_id}")
                    continue
                rect_type, rect_value = document.xref_get_key(xref, "Rect")
                if rect_type != "array":
                    raise ValueError(f"expression {expression_id}: missing annotation rectangle")
                rect = [float(value) for value in rect_value.strip("[]").split()]
                if len(rect) != 4 or not all(math.isfinite(value) for value in rect):
                    raise ValueError(f"expression {expression_id}: invalid rectangle")
                x0, y0, x1, y1 = rect  # PDF coordinates: bottom-left origin, big points.
                if x1 <= x0 or y1 <= y0:
                    errors.append(f"expression {expression_id}: nonpositive fragment")
                elif x0 < 0 or y0 < 0 or x1 > page.rect.width or y1 > page.rect.height:
                    errors.append(f"expression {expression_id}, page {page_number}: fragment outside page")
                boxes.append((expression_id, page_number, x0, y0, x1, y1))
        annotation_boxes = list(boxes)
        include_painted_rules(boxes, rules, {i: p.rect.height for i, p in enumerate(document, 1)})
        expanded_fragments = sum(a != b for a, b in zip(annotation_boxes, boxes))
        for expression, number, x0, y0, x1, y1 in boxes:
            page = document[number - 1]
            if x0 < 0 or y0 < 0 or x1 > page.rect.width or y1 > page.rect.height:
                errors.append(f"expression {expression}, page {number}: painted fragment outside page")
    found = {box[0] for box in boxes}
    missing = sorted(set(expected) - found)
    if missing:
        errors.append(f"nonempty expressions produced no geometry: {missing}")
    if errors:
        raise ValueError("; ".join(errors))
    # PDF traversal order preserves within-page fragment order, including complex
    # math whose superscripts need not sort by their geometric top edge.
    boxes.sort(key=lambda box: (box[0], box[1]))
    fragments = Counter()
    rows = []
    for row_id, (expression_id, page, x0, y0, x1, y1) in enumerate(boxes, 1):
        fragments[expression_id] += 1
        left, bottom, right, top = [round(value * SP_PER_BP) for value in (x0, y0, x1, y1)]
        rows.append(dict(id=row_id, page=page, x=left, y=bottom, width=right-left,
                         height=top-bottom, depth=0, expression_id=expression_id,
                         fragment=fragments[expression_id]))
    with Path(output).open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return {"expressions": len(expected), "fragments": len(rows),
            "multi_fragment_expressions": sum(count > 1 for count in fragments.values()),
            "paint_bounds_version": 1 if paint_version == "1" else 0,
            "paint_expanded_fragments": expanded_fragments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        report = {}
        if args.baseline:
            report["layout"] = compare_layout(args.baseline, args.pdf)
        report.update(extract_coordinates(args.pdf, args.pdf.parent / "mathrecords.csv",
                                          args.pdf.parent / "mathcoords.csv"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
