"""Read-only environment probe for the score-omr skill.

It reports what is present, records resolved paths, and never installs or downloads anything.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    required: bool
    detail: str
    value: str = ""


def _run(python: str, code: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [python, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        return False, str(exc)
    text = (completed.stdout or completed.stderr or "").strip().replace("\n", " ")
    return completed.returncode == 0, text[:300]


def _find_repo(explicit: str | None) -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("COPISTERIA_REPO"):
        candidates.append(Path(os.environ["COPISTERIA_REPO"]))
    here = Path.cwd()
    for base in (here, here.parent, here.parent.parent):
        candidates.extend(
            [
                base / "copisteria_src" / "copisteria-main",
                base / "copisteria",
                base / "musicxml_skill_dev" / "copisteria_src" / "copisteria-main",
            ]
        )
    for candidate in candidates:
        if candidate and (
            (candidate / "copisteria").is_dir()
            or (candidate / "src").is_dir()
            or (candidate / "pyproject.toml").is_file()
        ):
            return candidate.resolve()
    return None


def _find_converter(explicit: str | None) -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("COPISTERIA_CONVERTER"):
        candidates.append(Path(os.environ["COPISTERIA_CONVERTER"]))
    here = Path.cwd()
    for base in (here, here.parent, here.parent.parent):
        candidates.append(base / "musicxml_skill_dev" / "copisteria-to-musicxml" / "scripts" / "convert.py")
        candidates.append(base / "copisteria-to-musicxml" / "scripts" / "convert.py")
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    return None


def _find_musescore(explicit: str | None) -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("MUSESCORE_EXE"):
        candidates.append(Path(os.environ["MUSESCORE_EXE"]))
    for name in ("MuseScore4.exe", "musescore4", "mscore4", "MuseScore4"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates.extend(
        [
            Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe"),
            Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4"),
            Path(r"C:\Program Files\MuseScore 4\bin\mscore4.exe"),
            Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
        ]
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    return None


def probe(args: argparse.Namespace) -> list[Check]:
    checks: list[Check] = []
    py = args.python or os.environ.get("SCOREPIPE_PYTHON") or sys.executable
    ok, detail = _run(py, "import sys; print(sys.version.split()[0])")
    checks.append(Check("pipeline python", ok, True, detail, py))
    ok, detail = _run(py, "import scorepipe; print(scorepipe.__file__)")
    checks.append(Check("scorepipe import", ok, True, detail, py))

    omr_python = args.omr_python or os.environ.get("COPISTERIA_PYTHON") or py
    ok, detail = _run(omr_python, "import sys; print(sys.version.split()[0])")
    checks.append(Check("OMR python", ok, True, detail, omr_python))
    ok, detail = _run(omr_python, "import copisteria, music21; print('copisteria + music21')")
    checks.append(Check("copisteria + music21", ok, True, detail, omr_python))

    repo = _find_repo(args.repo)
    checks.append(
        Check("copisteria source", repo is not None, True, str(repo or "not found"), str(repo or ""))
    )
    if repo is not None:
        models = sorted((repo / "models").glob("*.pt"))
        checks.append(
            Check(
                "copisteria weights",
                bool(models),
                False,
                f"{len(models)} .pt file(s) under {repo / 'models'}",
                str(repo / "models"),
            )
        )
    converter = _find_converter(args.converter)
    checks.append(
        Check(
            "copisteria converter",
            converter is not None,
            True,
            str(converter or "not found"),
            str(converter or ""),
        )
    )
    musescore = _find_musescore(args.musescore)
    checks.append(
        Check(
            "MuseScore 4",
            musescore is not None,
            False,
            str(musescore or "not found; MusicXML-only delivery"),
            str(musescore or ""),
        )
    )
    for tool in ("pdfinfo", "pdftoppm"):
        found = shutil.which(tool)
        checks.append(Check(tool, bool(found), False, found or "not found", found or ""))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe the score-omr environment without changing it")
    parser.add_argument("--repo", help="copisteria source checkout")
    parser.add_argument("--converter", help="copisteria-to-musicxml/scripts/convert.py")
    parser.add_argument("--python", help="interpreter that imports scorepipe")
    parser.add_argument("--omr-python", help="interpreter that imports copisteria")
    parser.add_argument("--musescore", help="MuseScore executable")
    parser.add_argument("--save", help="write resolved paths to this JSON file")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)

    checks = probe(args)
    if args.json:
        print(json.dumps([asdict(check) for check in checks], ensure_ascii=False, indent=2))
    else:
        for check in checks:
            mark = "OK " if check.ok else ("MISS" if check.required else "opt ")
            print(f"[{mark}] {check.name:24s} {check.detail}")
    missing = [check.name for check in checks if check.required and not check.ok]
    if args.save:
        payload = {
            "python": next((c.value for c in checks if c.name == "pipeline python"), sys.executable),
            "omr_python": next((c.value for c in checks if c.name == "OMR python"), ""),
            "copisteria_repo": next((c.value for c in checks if c.name == "copisteria source"), ""),
            "converter": next((c.value for c in checks if c.name == "copisteria converter"), ""),
            "musescore": next((c.value for c in checks if c.name == "MuseScore 4"), ""),
            "missing": missing,
        }
        Path(args.save).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved: {args.save}")
    if missing:
        print("missing required: " + ", ".join(missing))
        return 1
    print("environment ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
