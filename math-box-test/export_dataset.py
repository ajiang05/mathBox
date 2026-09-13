"""Validate and export an instrumented MathBox batch as a COCO pilot dataset."""

import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import tempfile

import pymupdf


FIELDS = ("id", "page", "x", "y", "width", "height", "depth")
FRAGMENT_FIELDS = ("expression_id", "fragment")
PROVENANCE = ("metadata.json", "instrumentation_report.json", "mathcoords.csv")
COVERAGE = (
    "Pilot annotations are incomplete: headings, captions, front matter and "
    "unsupported constructs may contain unlabelled math. A page without "
    "annotations is not a confirmed negative. Alignment cells remain separate boxes."
)


class ValidationError(ValueError):
    """Input cannot be exported without silently changing annotations."""


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return value


def local_path(root, relative):
    """Resolve an input filename without escaping the input directory."""
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe path: {relative}")
    result = root / relative
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"path escapes input directory: {relative}")
    return result


def pixel_box(row, page_height, dpi):
    scale = dpi / (72.27 * 65536)
    return [
        row["x"] * scale,
        page_height * dpi / 72 - (row["y"] + row["height"]) * scale,
        row["width"] * scale,
        (row["height"] + row["depth"]) * scale,
    ]


def inspect_paper(root, entry, dpi):
    paper_id = entry["paper"]
    if not isinstance(paper_id, str) or Path(paper_id).name != paper_id or paper_id in (".", ".."):
        raise ValueError("invalid paper identifier")
    if entry.get("status") != "ok":
        raise ValueError("batch entry did not complete successfully")
    directory = local_path(root, paper_id)
    metadata = read_json(local_path(directory, "metadata.json"))
    instrumentation = read_json(local_path(directory, "instrumentation_report.json"))
    if instrumentation.get("recorder") == "pdf-breakable-v1":
        layout = read_json(local_path(directory, "layout_report.json"))
        if layout.get("passed") is not True or layout.get("layout", {}).get("passed") is not True:
            raise ValueError("native recorder did not pass original-PDF layout validation")
        if not local_path(directory, "mathrecords.csv").is_file():
            raise ValueError("missing native expression manifest")
    main = Path(entry["main_file"])
    local_path(directory, main)  # Validate even though only the compiled PDF is read.
    pdf_path = local_path(directory, main.stem + ".pdf")
    errors, rows, seen, fragments = [], [], set(), set()
    with local_path(directory, "mathcoords.csv").open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames not in (list(FIELDS), list(FIELDS + FRAGMENT_FIELDS)):
            raise ValueError("mathcoords.csv: unexpected columns")
        for line, raw in enumerate(reader, 2):
            try:
                if None in raw:
                    raise ValueError("extra columns")
                row = {key: int(raw[key]) for key in reader.fieldnames}
                if any(row.get(key, 1) <= 0 for key in FRAGMENT_FIELDS):
                    raise ValueError("expression and fragment IDs must be positive")
                if row["id"] <= 0:
                    raise ValueError("annotation ID must be positive")
                if row["id"] in seen:
                    raise ValueError(f"duplicate annotation ID {row['id']}")
                if "expression_id" in row:
                    fragment_key = (row["expression_id"], row["fragment"])
                    if fragment_key in fragments:
                        raise ValueError(f"duplicate expression fragment {fragment_key}")
                    fragments.add(fragment_key)
                seen.add(row["id"])
                rows.append(row)
            except (TypeError, ValueError) as error:
                errors.append(f"CSV line {line}: {error}")

    pages = []
    with pymupdf.open(pdf_path) as document:
        if not len(document):
            raise ValueError("PDF contains no pages")
        for number, page in enumerate(document, 1):
            if page.rotation or page.cropbox != page.mediabox or page.mediabox.x0 != 0 or page.mediabox.y0 != 0:
                errors.append(f"page {number}: unsupported rotation/crop/media geometry")
            bounds = (page.rect * pymupdf.Matrix(dpi / 72, dpi / 72)).irect
            pages.append({"number": number, "width": bounds.width, "height": bounds.height,
                          "pdf_height": page.rect.height})
        for row in rows:
            prefix = f"annotation {row['id']}"
            if not 1 <= row["page"] <= len(pages):
                errors.append(f"{prefix}: invalid page {row['page']}")
                continue
            page = pages[row["page"] - 1]
            try:
                box = pixel_box(row, page["pdf_height"], dpi)
                x, y, width, height = box
                if not all(math.isfinite(value) for value in box):
                    raise ValueError("nonfinite coordinates")
                if width <= 0 or height <= 0:
                    raise ValueError("nonpositive box dimensions")
                if x < 0 or y < 0 or x + width > page["width"] or y + height > page["height"]:
                    raise ValueError("box extends beyond page")
                row["bbox"] = box
            except (ValueError, OverflowError) as error:
                errors.append(f"{prefix}: {error}")
    if errors:
        raise ValidationError("; ".join(errors))
    return dict(id=paper_id, directory=directory, pdf=pdf_path, metadata=metadata,
                instrumentation=instrumentation, pages=pages,
                rows=sorted(rows, key=lambda row: (row["page"], row["id"])))


def inspect_batch(source, dpi, skip_failed_papers=False):
    """Validate the manifest globally, then accept or exclude whole papers."""
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi <= 0:
        raise ValidationError("DPI must be a positive integer")
    source = Path(source)
    report = read_json(source / "batch_report.json")
    entries = report.get("papers")
    if not isinstance(entries, list) or not entries:
        raise ValidationError("batch report must contain a nonempty papers list")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError("batch entries must be objects")
        paper_id = entry.get("paper")
        if (not isinstance(paper_id, str) or not paper_id
                or Path(paper_id).name != paper_id or paper_id in (".", "..")
                or "\\" in paper_id or "\x00" in paper_id):
            raise ValidationError("invalid or unsafe paper identifier")
        if paper_id in seen:
            raise ValidationError(f"duplicate paper identifier: {paper_id}")
        seen.add(paper_id)
        local_path(source, paper_id)
        if entry.get("status") not in ("ok", "failed"):
            raise ValidationError(f"{paper_id}: invalid batch status")
        if entry["status"] == "ok":
            main_file = entry.get("main_file")
            if not isinstance(main_file, str) or not main_file or "\x00" in main_file:
                raise ValidationError(f"{paper_id}: missing or invalid main_file")
            local_path(source / paper_id, main_file)
        if "error" in entry and not isinstance(entry["error"], str):
            raise ValidationError(f"{paper_id}: invalid batch error message")

    papers, excluded = [], []
    for entry in sorted(entries, key=lambda entry: entry["paper"]):
        paper_id = entry["paper"]
        if entry["status"] == "failed":
            excluded.append({"paper_id": paper_id, "stage": "batch",
                             "reason": entry.get("error") or "batch entry did not complete successfully"})
            continue
        try:
            papers.append(inspect_paper(source, entry, dpi))
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            excluded.append({"paper_id": paper_id, "stage": "preflight", "reason": str(error)})
    details = "\n".join(f"{item['paper_id']} ({item['stage']}): {item['reason']}" for item in excluded)
    if excluded and not skip_failed_papers:
        raise ValidationError("Batch validation failed:\n" + details)
    if not papers:
        raise ValidationError("No papers passed validation; no dataset created.\n" + details)
    return papers, excluded


def preflight(source, dpi):
    """Retain the existing strict preflight interface for callers."""
    papers, _ = inspect_batch(source, dpi)
    return papers


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def export_dataset(source, destination, dpi=150, *, skip_failed_papers=False):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValidationError(f"destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise ValidationError("destination parent directory must already exist")
    papers, excluded = inspect_batch(source, dpi, skip_failed_papers)
    coco = {"info": {"description": "MathBox unsplit pilot", "coverage": COVERAGE},
            "licenses": [], "images": [], "annotations": [],
            "categories": [{"id": 1, "name": "math", "supercategory": "math"}]}
    summary = {"schema_version": 1, "status": "pilot", "coverage": COVERAGE,
               "dpi": dpi, "source_batch": source.name, "papers": [],
               "skip_failed_papers": skip_failed_papers, "excluded_papers": excluded,
               "attempted_paper_count": len(papers) + len(excluded),
               "included_paper_count": len(papers), "excluded_paper_count": len(excluded)}
    licenses = {}
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for paper in papers:
            paper_id = paper["id"]
            license_url = paper["metadata"].get("license") or "unknown"
            if license_url not in licenses:
                licenses[license_url] = len(licenses) + 1
                coco["licenses"].append({"id": licenses[license_url], "name": license_url,
                                         "url": "" if license_url == "unknown" else license_url})
            image_directory = temporary / "images" / paper_id
            image_directory.mkdir(parents=True)
            image_ids = {}
            with pymupdf.open(paper["pdf"]) as document:
                for page_info, page in zip(paper["pages"], document):
                    number = page_info["number"]
                    filename = f"images/{paper_id}/page_{number:04d}.png"
                    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
                    if (pixmap.width, pixmap.height) != (page_info["width"], page_info["height"]):
                        raise ValidationError(f"{paper_id} page {number}: render dimensions changed")
                    pixmap.save(temporary / filename)
                    image_id = len(coco["images"]) + 1
                    image_ids[number] = image_id
                    coco["images"].append({"id": image_id, "file_name": filename,
                        "width": pixmap.width, "height": pixmap.height,
                        "license": licenses[license_url], "paper_id": paper_id, "page": number})
            for row in paper["rows"]:
                box = row["bbox"]
                coco["annotations"].append({"id": len(coco["annotations"]) + 1,
                    "image_id": image_ids[row["page"]], "category_id": 1,
                    "bbox": box, "area": box[2] * box[3], "iscrowd": 0,
                    "paper_id": paper_id, "page": row["page"], "source_id": row["id"]})
                if "expression_id" in row:
                    coco["annotations"][-1].update(
                        expression_id=row["expression_id"], fragment=row["fragment"])
            provenance = temporary / "provenance" / paper_id
            provenance.mkdir(parents=True)
            for filename in PROVENANCE:
                shutil.copyfile(paper["directory"] / filename, provenance / filename)
            for filename in ("mathrecords.csv", "layout_report.json"):
                if (paper["directory"] / filename).is_file():
                    shutil.copyfile(paper["directory"] / filename, provenance / filename)
            summary["papers"].append({"paper_id": paper_id, "pages": len(paper["pages"]),
                "boxes": len(paper["rows"]), "instrumentation": paper["instrumentation"]})
        summary.update(paper_count=len(papers), page_count=len(coco["images"]),
                       annotation_count=len(coco["annotations"]))
        write_json(temporary / "annotations.json", coco)
        write_json(temporary / "export_report.json", summary)
        if destination.exists() or destination.is_symlink():
            raise ValidationError("destination appeared during export; refusing to overwrite")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--skip-failed-papers", action="store_true",
                        help="exclude whole papers failing batch or preflight checks and report why")
    args = parser.parse_args()
    try:
        summary = export_dataset(args.source, args.destination, args.dpi,
                                 skip_failed_papers=args.skip_failed_papers)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Exported {summary['paper_count']} papers, {summary['page_count']} pages, "
          f"{summary['annotation_count']} boxes to {args.destination}")
    print(COVERAGE)
    print(f"Excluded {summary['excluded_paper_count']} of {summary['attempted_paper_count']} papers.")
    for excluded in summary["excluded_papers"]:
        print(f"  {excluded['paper_id']} ({excluded['stage']}): {excluded['reason']}")


if __name__ == "__main__":
    main()
