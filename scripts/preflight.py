"""Read-only environment probe for the copisteria-score-to-mscz skill.

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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # the probe must still run when the pipeline package itself is broken
    from scorepipe.discovery import find_musescore as _discover_musescore
except Exception:  # pragma: no cover - reported by the scorepipe import check
    _discover_musescore = None


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
    if _discover_musescore is not None:
        located = _discover_musescore(explicit)
        if located:
            return Path(located).resolve()
        return None
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    for name in ("MuseScore4.exe", "musescore4", "mscore4", "MuseScore4"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates.extend(
        [
            Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe"),
            Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
        ]
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    return None


def load_env(path: str | Path | None) -> dict:
    """Read the file ``--save`` writes; missing or unreadable means "no defaults".

    The quick path in SKILL.md saves ``env.local.json`` once and expects later runs to use it.
    Reading it back here is what makes that promise true; an explicit flag or environment
    variable still wins, so a stale file can always be overridden.
    """
    if not path:
        return {}
    source = Path(path)
    if not source.is_file():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_env_file() -> Path | None:
    """``env.local.json`` beside the caller, else beside the repository."""
    for candidate in (Path.cwd() / "env.local.json", ROOT / "env.local.json"):
        if candidate.is_file():
            return candidate
    return None


def _pick(explicit: str | None, variable: str, config: dict, key: str) -> str | None:
    """Explicit flag > environment variable > env file > nothing (the probe may autodetect)."""
    return explicit or os.environ.get(variable) or (config.get(key) or None)


def probe(args: argparse.Namespace, config: dict | None = None) -> list[Check]:
    checks: list[Check] = []
    config = config or {}
    py = _pick(args.python, "SCOREPIPE_PYTHON", config, "python") or sys.executable
    ok, detail = _run(py, "import sys; print(sys.version.split()[0])")
    checks.append(Check("pipeline python", ok, True, detail, py))
    ok, detail = _run(py, "import scorepipe; print(scorepipe.__file__)")
    checks.append(Check("scorepipe import", ok, True, detail, py))

    omr_python = _pick(args.omr_python, "COPISTERIA_PYTHON", config, "omr_python") or py
    ok, detail = _run(omr_python, "import sys; print(sys.version.split()[0])")
    checks.append(Check("OMR python", ok, True, detail, omr_python))
    ok, detail = _run(omr_python, "import copisteria, music21; print('copisteria + music21')")
    checks.append(Check("copisteria + music21", ok, True, detail, omr_python))

    repo = _find_repo(_pick(args.repo, "COPISTERIA_REPO", config, "copisteria_repo"))
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
    converter = _find_converter(_pick(args.converter, "COPISTERIA_CONVERTER", config, "converter"))
    checks.append(
        Check(
            "copisteria converter",
            converter is not None,
            True,
            str(converter or "not found"),
            str(converter or ""),
        )
    )
    musescore = _find_musescore(_pick(args.musescore, "MUSESCORE_EXE", config, "musescore"))
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
    parser = argparse.ArgumentParser(description="Probe the copisteria-score-to-mscz environment without changing it")
    parser.add_argument("--repo", help="copisteria source checkout")
    parser.add_argument("--converter", help="copisteria-to-musicxml/scripts/convert.py")
    parser.add_argument("--python", help="interpreter that imports scorepipe")
    parser.add_argument("--omr-python", help="interpreter that imports copisteria")
    parser.add_argument("--musescore", help="MuseScore executable")
    parser.add_argument(
        "--env",
        help="env.local.json written by --save; explicit flags and COPISTERIA_*/MUSESCORE_EXE "
        "environment variables still win. Defaults to ./env.local.json or <repo>/env.local.json",
    )
    parser.add_argument("--save", help="write resolved paths to this JSON file")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)

    env_path = args.env or _default_env_file()
    config = load_env(env_path)
    if env_path and not Path(env_path).is_file():
        print(f"warning: env file not found: {env_path}", file=sys.stderr)

    checks = probe(args, config)
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
