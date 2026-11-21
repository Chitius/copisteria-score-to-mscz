"""Build one OMR case from an OpenScore Lieder ``.mxl``.

The original MusicXML is the ground truth; the rendered PDF is the synthetic OMR input.  Rendering
uses the local MuseScore CLI because it is already used by the display pipeline.  This script only
builds files; it never invokes the OMR recogniser.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def extract_mxl(source: Path, destination: Path) -> Path:
    """Extract the root MusicXML from a compressed MusicXML ``.mxl`` container."""
    with zipfile.ZipFile(source) as archive:
        container_name = "META-INF/container.xml"
        if container_name not in archive.namelist():
            raise ValueError(f"{source} has no {container_name}")
        container = ElementTree.fromstring(archive.read(container_name))
        rootfile = next(container.iter("rootfile"), None)
        if rootfile is None or not rootfile.get("full-path"):
            raise ValueError(f"{source} has no rootfile entry")
        destination.write_bytes(archive.read(rootfile.get("full-path")))
    return destination


def render_pdf(musicxml: Path, pdf: Path, musescore: Path | None) -> None:
    executable = musescore or Path(r"S:\Program Files\MuseScore 4\bin\MuseScore4.exe")
    if not executable.exists():
        raise FileNotFoundError(f"MuseScore not found: {executable}")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(executable), "-f", "-o", str(pdf), str(musicxml)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"MuseScore failed ({result.returncode}): {result.stderr[:500]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mxl", type=Path, help="OpenScore .mxl file")
    parser.add_argument("output", type=Path, help="case directory")
    parser.add_argument("--musescore", type=Path)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.mxl, args.output / f"{args.output.name}.mxl")
    ground_truth = args.output / "ground_truth.musicxml"
    extract_mxl(args.mxl, ground_truth)
    print(f"ground truth: {ground_truth}")
    if not args.skip_render:
        pdf = args.output / "input.pdf"
        render_pdf(ground_truth, pdf, args.musescore)
        print(f"OMR input:    {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
