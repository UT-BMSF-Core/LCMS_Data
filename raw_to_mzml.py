"""
raw_to_mzml.py

Original Code create with Claude and edited by Sean Meehan

Convert all .RAW files in the BSA folder that were created within the past
week to .mzML, using MSConvert (ProteoWizard), on Windows. Then figures out
which .mzML files still need to go through BSASpectralparsing.py (i.e. don't
already have a matching output file) and writes their filenames to
to_parse.txt, so BSASpectralparsing.py can be pointed at just those.

Requires ProteoWizard installed, with msconvert.exe at MSCONVERT_PATH below
(edit if it moves).

Usage:
    python raw_to_mzml.py
        Converts every .raw file in BSA_DIR created in the last 7 days,
        writing .mzML files to MZML_DIR, then writes to_parse.txt listing
        any mzML files (new or old) that still need spectral parsing.

    python raw_to_mzml.py --days 3
        Same, but only files created in the last 3 days.

    python raw_to_mzml.py -o C:\\some\\other_folder
        Write the .mzML files to a different folder instead of MZML_DIR.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Default location of msconvert.exe on this machine (not on PATH)
MSCONVERT_PATH = r"[Insert Path]"

# Folder containing the .RAW files to convert
BSA_DIR = Path(r"[Insert Path]")

# Folder where converted .mzML files should be written
MZML_DIR = Path(r"[Insert Path]")

# BSASpectralParsing.py writes its output (PNGs + Excel log) directly into
# MZML_DIR, so that's what we check to know if a file's already been parsed.
PARSED_DIR = MZML_DIR
PARSED_MARKER_SUFFIX = "_TIC_QC.png"  # this file's presence means it's done

# Where the list of mzML filenames still needing parsing gets written
TO_PARSE_LIST = MZML_DIR.parent / "to_parse.txt"


def find_recent_raw_files(folder: Path, days: int) -> list[Path]:
    """Return .raw files in folder whose creation time is within the last `days` days."""
    cutoff = time.time() - (days * 86400)
    raw_files = list(folder.glob("*.raw")) + list(folder.glob("*.RAW"))

    # de-duplicate case-insensitively
    seen = set()
    unique = []
    for f in raw_files:
        key = f.resolve().as_posix().lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # st_ctime is creation time on Windows
    return [f for f in unique if f.stat().st_ctime >= cutoff]


def mzml_exists(raw_file: Path, output_dir: Path) -> bool:
    """Check whether a matching .mzML already exists in output_dir for this .raw file."""
    stem_lower = raw_file.stem.lower()
    if not output_dir.exists():
        return False
    for existing in output_dir.iterdir():
        if existing.name.lower() in (f"{stem_lower}.mzml", f"{stem_lower}.mzml.gz"):
            return True
    return False


def find_unparsed_mzml(mzml_dir: Path, parsed_dir: Path, marker_suffix: str) -> list[Path]:
    """
    Return every .mzML in mzml_dir that does NOT yet have a matching
    "{stem}{marker_suffix}" output file in parsed_dir (i.e. hasn't been
    through BSASpectralParsing.py yet).
    """
    mzml_files = list(mzml_dir.glob("*.mzML")) + list(mzml_dir.glob("*.mzml"))

    seen = set()
    unique = []
    for f in mzml_files:
        key = f.resolve().as_posix().lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)

    def has_parsed_output(mzml_file: Path) -> bool:
        expected = parsed_dir / f"{mzml_file.stem}{marker_suffix}"
        return expected.exists()

    return [f for f in unique if not has_parsed_output(f)]


def main():
    parser = argparse.ArgumentParser(
        description="Convert .RAW files created in the last N days to .mzML."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Only convert .raw files created within this many days (default: 7).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Output folder for the .mzML files (defaults to MZML_DIR).",
    )
    parser.add_argument(
        "--msconvert-path",
        default=MSCONVERT_PATH,
        help="Path to msconvert.exe.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reconvert files even if a matching .mzML already exists.",
    )
    args = parser.parse_args()

    if not BSA_DIR.exists():
        print(f"Error: BSA folder not found: {BSA_DIR}", file=sys.stderr)
        return 1

    if not Path(args.msconvert_path).exists():
        print(f"Error: msconvert.exe not found at: {args.msconvert_path}", file=sys.stderr)
        return 1

    output_dir = args.output_dir or MZML_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_files = find_recent_raw_files(BSA_DIR, args.days)
    if not raw_files:
        print(f"No .raw files created in the last {args.days} day(s) found in {BSA_DIR}.")
        return 0

    to_convert = [f for f in raw_files if args.overwrite or not mzml_exists(f, output_dir)]
    already_done = [] if args.overwrite else [f for f in raw_files if mzml_exists(f, output_dir)]

    if already_done:
        print(f"Skipping {len(already_done)} file(s) that already have an .mzML:")
        for f in already_done:
            print(f"  - {f.name}")

    if not to_convert:
        print("\nNothing new to convert.")
        return 0

    print(f"\nFound {len(to_convert)} file(s) to convert:")
    for f in to_convert:
        print(f"  - {f.name}")

    failures = []
    for raw_file in to_convert:
        cmd = [args.msconvert_path, str(raw_file), "--mzML", "-o", str(output_dir)]
        print(f"\n--- Converting: {raw_file.name} ---")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            print(f"Conversion failed for {raw_file.name}:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            failures.append(raw_file)
        else:
            print(f"Success: {raw_file.name} -> {output_dir}")

    if failures:
        print(f"\n{len(failures)} file(s) failed to convert:", file=sys.stderr)
        for f in failures:
            print(f"  - {f.name}", file=sys.stderr)
        return 1

    print(f"\nAll {len(to_convert)} file(s) converted successfully to {output_dir}")

    # ------------------------------------------------------------------
    # Figure out which mzML files (new ones from this run, plus any older
    # ones never parsed) still need to go through BSASpectralparsing.py
    # ------------------------------------------------------------------
    unparsed = find_unparsed_mzml(output_dir, PARSED_DIR, PARSED_MARKER_SUFFIX)

    if unparsed:
        print(f"\n{len(unparsed)} mzML file(s) still need spectral parsing:")
        for f in unparsed:
            print(f"  - {f.name}")
        TO_PARSE_LIST.parent.mkdir(parents=True, exist_ok=True)
        TO_PARSE_LIST.write_text("\n".join(f.name for f in unparsed) + "\n")
        print(f"\nWrote filenames to {TO_PARSE_LIST} for BSASpectralparsing.py to use.")
    else:
        print("\nNo mzML files are waiting on spectral parsing.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
