"""Stream a small sample from scholarweave/arxiv-latex and extract its files.

Run these commands from ``math-box-test``::

    pip install -r requirements.txt
    python sample_arxiv_latex.py --count 10

Useful options::

    python sample_arxiv_latex.py --count 5 --categories math.PR math.ST
    python sample_arxiv_latex.py --count 5 --compile-check
    python sample_arxiv_latex.py --extract-existing

The script streams only the requested Parquet shard; it does not download the
complete dataset. By default, it uses shard 46, currently the newest shard,
rather than beginning with the oldest arXiv papers.

Overview of file: 
  - Extract real .tex, .bib, .sty, and nested source files.
  - Reject unsafe or malformed filenames.
  - Reject papers without a detectable LaTeX2e main file.
  - Use the newer Parquet shard 46 by default instead of starting with 1991 papers.
  - Optionally retain only papers that compile with Tectonic using --compile-check.
  - Record possible main files in metadata.json.
  original source_bundle.txt files were preserved as raw backups.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


DATASET_URL = (
    "https://huggingface.co/datasets/scholarweave/arxiv-latex/resolve/main/"
    "arxiv_part_{part:04d}.parquet"
)
DEFAULT_CATEGORIES = ("cs.LG", "math.", "stat.ML")
FILE_MARKER = re.compile(
    r"^={10,}\s*\nFILE:\s*(.+?)\s*\n={10,}\s*\n?", re.MULTILINE
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream arXiv papers and reconstruct their source files."
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument(
        "--categories", nargs="+", default=list(DEFAULT_CATEGORIES)
    )
    parser.add_argument("--output", type=Path, default=Path("arxiv_sample"))
    parser.add_argument(
        "--part", type=int, default=46,
        help="Parquet shard to stream (default: 46, currently the newest).",
    )
    parser.add_argument(
        "--compile-check", action="store_true",
        help="Keep only sources that compile successfully with Tectonic.",
    )
    parser.add_argument(
        "--extract-existing", action="store_true",
        help="Extract existing source_bundle.txt files, then exit.",
    )
    return parser.parse_args()


def category_matches(categories: str, wanted: list[str]) -> bool:
    if "*" in wanted:
        return True
    paper_categories = categories.split()
    return any(
        category == pattern or category.startswith(pattern)
        for category in paper_categories
        for pattern in wanted
    )


def safe_directory_name(arxiv_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", arxiv_id)


def safe_relative_path(raw_name: str) -> Path:
    """Validate an embedded filename so it cannot escape the paper folder."""
    normalized = raw_name.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe embedded filename: {raw_name!r}")
    cleaned_parts = tuple(part for part in path.parts if part not in ("", "."))
    if not cleaned_parts:
        raise ValueError(f"empty embedded filename: {raw_name!r}")
    return Path(*cleaned_parts)


def parse_source_bundle(bundle: str) -> dict[Path, str]:
    """Split the dataset's marked text field into its original source files."""
    markers = list(FILE_MARKER.finditer(bundle))
    if not markers:
        raise ValueError("source bundle contains no FILE markers")

    files: dict[Path, str] = {}
    for index, marker in enumerate(markers):
        relative_path = safe_relative_path(marker.group(1))
        content_end = markers[index + 1].start() if index + 1 < len(markers) else len(bundle)
        content = bundle[marker.end():content_end]
        if relative_path in files:
            raise ValueError(f"duplicate embedded filename: {relative_path}")
        files[relative_path] = content
    return files


def write_source_files(directory: Path, files: dict[Path, str]) -> None:
    for relative_path, content in files.items():
        destination = directory / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def latex2e_main_files(files: dict[Path, str]) -> list[Path]:
    return [
        path for path, content in files.items()
        if path.suffix.lower() == ".tex" and r"\documentclass" in content
    ]


def compiles_with_tectonic(files: dict[Path, str]) -> tuple[bool, str]:
    mains = latex2e_main_files(files)
    if not mains:
        return False, "no LaTeX2e main file containing \\documentclass"
    if shutil.which("tectonic") is None:
        raise RuntimeError("--compile-check requires the tectonic command")

    with tempfile.TemporaryDirectory(prefix="mathbox-arxiv-") as temporary:
        source_directory = Path(temporary) / "source"
        output_directory = Path(temporary) / "output"
        source_directory.mkdir()
        output_directory.mkdir()
        write_source_files(source_directory, files)

        for main_file in mains:
            result = subprocess.run(
                ["tectonic", "--outdir", str(output_directory), str(main_file)],
                cwd=source_directory, capture_output=True, text=True,
            )
            if result.returncode == 0:
                return True, str(main_file)
    return False, "all detected main files failed to compile"


def extract_existing(output: Path) -> None:
    bundles = sorted(output.glob("*/source_bundle.txt"))
    if not bundles:
        print(f"No source_bundle.txt files found under {output}")
        return
    for bundle_path in bundles:
        try:
            files = parse_source_bundle(bundle_path.read_text(encoding="utf-8"))
            write_source_files(bundle_path.parent, files)
            print(f"Extracted {len(files)} file(s) in {bundle_path.parent}")
        except (OSError, UnicodeError, ValueError) as error:
            print(f"Rejected {bundle_path}: {error}")


def save_paper(paper: dict, output: Path, compile_check: bool) -> tuple[bool, str]:
    try:
        files = parse_source_bundle(paper.get("latex") or "")
    except ValueError as error:
        return False, str(error)

    mains = latex2e_main_files(files)
    if not mains:
        return False, "not LaTeX2e or no detectable main file"

    compiled_main = None
    if compile_check:
        success, reason = compiles_with_tectonic(files)
        if not success:
            return False, reason
        compiled_main = reason

    arxiv_id = paper["id"]
    paper_directory = output / safe_directory_name(arxiv_id)
    paper_directory.mkdir(parents=True, exist_ok=True)
    write_source_files(paper_directory, files)

    metadata = {
        "id": arxiv_id,
        "title": paper.get("title"),
        "authors": paper.get("authors"),
        "categories": paper.get("categories"),
        "license": paper.get("license"),
        "update_date": paper.get("update_date"),
        "main_file_candidates": [str(path) for path in mains],
        "compiled_main_file": compiled_main,
    }
    (paper_directory / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return True, f"{len(files)} source file(s)"


def main() -> None:
    args = parse_args()
    if args.extract_existing:
        extract_existing(args.output)
        return
    if args.count < 1:
        raise SystemExit("--count must be at least 1")

    # Import lazily so --extract-existing works without the datasets package.
    try:
        from datasets import load_dataset
    except ImportError as error:
        raise SystemExit(
            "Install dependencies with: pip install -r requirements.txt"
        ) from error

    args.output.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset(
        "parquet",
        data_files={"train": DATASET_URL.format(part=args.part)},
        split="train",
        streaming=True,
    )

    saved = 0
    scanned = 0
    rejected = 0
    for paper in dataset:
        scanned += 1
        if not category_matches(paper.get("categories") or "", args.categories):
            continue
        success, detail = save_paper(paper, args.output, args.compile_check)
        if not success:
            rejected += 1
            print(f"Rejected {paper.get('id')}: {detail}")
            continue
        saved += 1
        print(f"[{saved}/{args.count}] Saved {paper['id']} ({detail})")
        if saved == args.count:
            break

    print(f"Finished: saved {saved}, rejected {rejected}, scanned {scanned} rows.")
    print(f"Output directory: {args.output.resolve()}")


if __name__ == "__main__":
    main()
