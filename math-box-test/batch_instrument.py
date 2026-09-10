"""Instrument, compile, and verify a directory of sampled arXiv papers.

Example:
    python batch_instrument.py arxiv_batch_10 arxiv_batch_10_instrumented
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instrument, compile, and render audits for sampled papers."
    )
    parser.add_argument("source", type=Path, help="directory containing paper folders")
    parser.add_argument("destination", type=Path, help="new batch output directory")
    parser.add_argument("--dpi", type=int, default=150, help="audit render DPI")
    return parser.parse_args()


def main_file_from_metadata(paper: Path) -> Path:
    """Return the selected main TeX path recorded by the sampler."""
    metadata_path = paper / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {metadata_path}: {error}") from error

    selected = metadata.get("compiled_main_file")
    candidates = metadata.get("main_file_candidates") or []
    if not selected and len(candidates) == 1:
        selected = candidates[0]
    if not selected:
        raise ValueError("metadata does not identify one main TeX file")

    main_file = Path(selected)
    if main_file.is_absolute() or ".." in main_file.parts:
        raise ValueError(f"unsafe main file path: {selected!r}")
    if not (paper / main_file).is_file():
        raise ValueError(f"main file does not exist: {main_file}")
    return main_file


def run_command(command: list[str], cwd: Path | None = None) -> None:
    """Run one visible subprocess and raise a concise error on failure."""
    result = subprocess.run(command, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"command exited with status {result.returncode}")


def process_paper(paper: Path, destination: Path, dpi: int) -> dict[str, str]:
    """Run the complete pipeline for one paper and return its report entry."""
    name = paper.name
    output = destination / name
    entry = {"paper": name, "status": "failed"}
    try:
        main_file = main_file_from_metadata(paper)
        print(f"\n[{name}] Instrumenting {main_file}", flush=True)
        run_command([
            sys.executable,
            str(SCRIPT_DIRECTORY / "instrument_latex.py"),
            str(paper),
            str(output),
            "--main",
            str(main_file),
        ])

        if shutil.which("tectonic") is None:
            raise RuntimeError("tectonic command is not installed")
        print(f"[{name}] Compiling", flush=True)
        run_command([
            "tectonic", "--outdir", ".", str(main_file)
        ], cwd=output)

        pdf = output / f"{main_file.stem}.pdf"
        coordinates = output / "mathcoords.csv"
        if not pdf.is_file() or not coordinates.is_file():
            raise RuntimeError("compilation did not produce the PDF and mathcoords.csv")

        print(f"[{name}] Rendering audit images", flush=True)
        run_command([
            sys.executable,
            str(SCRIPT_DIRECTORY / "verify.py"),
            str(pdf),
            str(coordinates),
            "--output-dir",
            str(output / "audit"),
            "--dpi",
            str(dpi),
        ])
        entry.update(status="ok", main_file=str(main_file), output=str(output))
        print(f"[{name}] Complete", flush=True)
    except (ValueError, RuntimeError) as error:
        entry["error"] = str(error)
        print(f"[{name}] FAILED: {error}", file=sys.stderr, flush=True)
    return entry


def main() -> None:
    args = parse_args()
    if not args.source.is_dir():
        raise SystemExit(f"Source directory not found: {args.source}")
    if args.destination.exists():
        raise SystemExit(f"Destination already exists: {args.destination}")
    if args.dpi < 1:
        raise SystemExit("--dpi must be at least 1")

    papers = sorted(
        path for path in args.source.iterdir()
        if path.is_dir() and (path / "metadata.json").is_file()
    )
    if not papers:
        raise SystemExit(f"No paper folders found in {args.source}")

    args.destination.mkdir(parents=True)
    entries = [process_paper(paper, args.destination, args.dpi) for paper in papers]
    succeeded = sum(entry["status"] == "ok" for entry in entries)
    report = {
        "source": str(args.source),
        "destination": str(args.destination),
        "total": len(entries),
        "succeeded": succeeded,
        "failed": len(entries) - succeeded,
        "papers": entries,
    }
    report_path = args.destination / "batch_report.json"
    report_path.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"\nFinished: {succeeded}/{len(entries)} succeeded. Report: {report_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
