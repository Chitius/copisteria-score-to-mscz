"""Low-level process, PDF, config, timing, and confidence-map helpers for delivery review."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.invariants import LENGTH_CODES
from ..mscz_export import find_musescore


def _run(command: list[str], cwd: Path) -> int:
    print("+ " + " ".join(str(part) for part in command))
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if output.strip():
        print(output.rstrip())
    return completed.returncode


def _pdf_pages(pdf: Path) -> int | None:
    binary = shutil.which("pdfinfo")
    if not binary:
        return None
    completed = subprocess.run(
        [binary, str(pdf)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in completed.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _parts(facts_dir: Path) -> list[Path]:
    return sorted(facts_dir.glob("agent-page*.json"))


def _render_pages(pdf: Path, outdir: Path) -> int:
    binary = shutil.which("pdftoppm")
    if not binary:
        raise RuntimeError("pdftoppm not found")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("source-*.png"):
        old.unlink()
    completed = subprocess.run(
        [binary, "-png", "-r", "150", str(pdf), str(outdir / "source")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {(completed.stderr or '').strip()[:400]}")
    return len(list(outdir.glob("source-*.png")))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_env_file(root: Path) -> Path | None:
    """``env.local.json`` beside the caller, else beside the repository."""
    for candidate in (Path.cwd() / "env.local.json", root / "env.local.json"):
        if candidate.is_file():
            return candidate
    return None


def _load_config(path: str | Path | None) -> dict:
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


def _timing(report_path: Path) -> dict:
    """Extract measure-length findings from a scorepipe report."""
    if not report_path.is_file():
        return {"count": 0, "violations": []}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    violations = [
        {"measure": violation.get("measure"), "detail": violation.get("detail")}
        for violation in data.get("verifier") or []
        if violation.get("code") in LENGTH_CODES
    ]
    return {"count": len(violations), "violations": violations}


def _timing_report(baseline: dict | None, reviewed: dict | None) -> dict:
    """Compare measure-length findings; report non-comparability instead of faking deltas."""
    if baseline is None or reviewed is None:
        return {
            "available": False,
            "reason": (
                "timing deltas need both a mechanical baseline report and a reviewed report; "
                "a skipped or failed run is not an empty finding list"
            ),
            "baseline": baseline,
            "reviewed": reviewed,
            "introduced": [],
            "resolved": [],
        }
    before = baseline
    after = reviewed
    before_counts = Counter((item["measure"], item["detail"]) for item in before["violations"])
    after_counts = Counter((item["measure"], item["detail"]) for item in after["violations"])
    introduced = sorted((after_counts - before_counts).elements(), key=lambda item: (item[0], item[1]))
    resolved = sorted((before_counts - after_counts).elements(), key=lambda item: (item[0], item[1]))
    return {
        "available": True,
        "baseline": before,
        "reviewed": after,
        "introduced": [{"measure": measure, "detail": detail} for measure, detail in introduced],
        "resolved": [{"measure": measure, "detail": detail} for measure, detail in resolved],
    }


def _truncation_notes(report_path: Path) -> list[str]:
    if not report_path.is_file():
        return []
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return [
        note
        for entry in data.get("trace") or []
        if entry.get("pass") == "truncate_overfull_mscx"
        for note in entry.get("notes") or []
    ]


def _truncation_performed(operations: list[str]) -> bool:
    """True when a voice was really trimmed, not only normalized.

    The truncation pass reports ``m82 staff 1: 3.25->3 beats; remove 0.25`` for a real edit and
    ``DEFERRED``/``UNRESOLVED`` for the cases it refuses; the duration normalization that runs
    with it reports ``normalized ...``/``converted ...``.  Only the first form changes what the
    user sees, so only that form makes the editable copy the delivery.
    """
    for operation in operations:
        if operation.startswith("m") and " staff " in operation:
            return True
    return False


def parse_accepted_verifier_specs(raw_specs: list[str] | tuple[str, ...] | None) -> list[tuple[int, str]]:
    """Parse ``<measure>:<code>[,<measure>:<code>…]`` entries into ``(measure, code)`` pairs."""
    if not raw_specs:
        return []
    parsed: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for raw in raw_specs:
        if raw is None:
            continue
        for token in str(raw).split(","):
            entry = token.strip()
            if not entry or ":" not in entry:
                raise ValueError(
                    f"invalid --accept-verifier entry {token!r}; expected <measure>:<code>"
                )
            measure_part, code_part = entry.split(":", 1)
            measure_text = measure_part.strip()
            if measure_text[:1].lower() == "m":
                measure_text = measure_text[1:]
            try:
                measure = int(measure_text)
            except ValueError as exc:
                raise ValueError(
                    f"invalid measure in --accept-verifier entry {token!r}"
                ) from exc
            if measure < 1:
                raise ValueError(
                    f"measure must be >= 1 in --accept-verifier entry {token!r}"
                )
            code = code_part.strip()
            if not code:
                raise ValueError(
                    f"missing verifier code in --accept-verifier entry {token!r}"
                )
            key = (measure, code)
            if key not in seen:
                seen.add(key)
                parsed.append(key)
    return parsed


def _report_violations(report_path: Path) -> list[dict] | None:
    """Return the ``verifier`` list of a scorepipe report, or ``None`` if unreadable."""
    if not report_path.is_file():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    violations = data.get("verifier")
    if violations is None:
        return []
    return list(violations) if isinstance(violations, list) else None


def _partition_violations(
    violations: list[dict] | None, accepted_specs: set[tuple[int, str]]
) -> tuple[list[dict], list[dict]]:
    """Split verifier findings into ``(accepted, remaining)`` using ``(measure, code)`` pairs."""
    if not violations:
        return [], []
    if not accepted_specs:
        return [], list(violations)
    accepted: list[dict] = []
    remaining: list[dict] = []
    for violation in violations:
        key = (violation.get("measure"), violation.get("code"))
        if key in accepted_specs:
            accepted.append(violation)
        else:
            remaining.append(violation)
    return accepted, remaining


def _format_accepted_finding(
    violation: dict, *, stage: str, reason: str | None = None
) -> dict:
    entry = {
        "stage": stage,
        "measure": violation.get("measure"),
        "code": violation.get("code"),
        "spec": f"{violation.get('measure')}:{violation.get('code')}",
        "detail": violation.get("detail"),
    }
    if reason:
        entry["reason"] = reason
    return entry


def _only_overfull_violations(report_path: Path) -> bool:
    """True when every verifier finding is a length complaint (overfull bar or its tuplet).

    The reviewed (untruncated) tree is allowed to report an overfull voice: that is exactly the
    condition the editable copy repairs.  A tuplet that does not add up inside that same voice is
    part of the same defect, so it is tolerated with the measure-length codes -- but only while
    the forced-truncation copy verifies clean, which the caller checks separately.  Any other
    verifier finding still blocks.
    """
    if not report_path.is_file():
        return False
    data = json.loads(report_path.read_text(encoding="utf-8"))
    violations = data.get("verifier") or []
    return bool(violations) and all(
        violation.get("code") in LENGTH_CODES for violation in violations
    )


def _verifier_codes(report_path: Path) -> list[str]:
    """Sorted, de-duplicated verifier codes of a scorepipe report (empty when unreadable)."""
    if not report_path.is_file():
        return []
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted({str(violation.get("code")) for violation in data.get("verifier") or []})


def _verifier_count(report_path: Path) -> int:
    if not report_path.is_file():
        return 0
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return len(data.get("verifier") or [])


def _confidence_map(page_dir: Path, outdir: Path) -> dict:
    """Paint where the OMR reader was unsure.

    This is a reading aid for the human, never a delivery gate: a failure here is recorded in the
    report and does not change ``ready``.  ``page_dir`` is the directory the OMR wrote (``--pages``),
    which is where copisteria puts ``<page>.reading.json``; the page images are looked up next to
    it and in the usual ``<work>/pages`` layout.
    """
    try:
        from .. import confidence
    except Exception as exc:  # noqa: BLE001 - report, never raise, a missing aid is not a failure
        return {"status": "failed", "reason": str(exc)}
    jobs = confidence.plan(
        readings_dir=page_dir,
        page_dirs=[page_dir, page_dir.parent / "pages"],
        work_dir=page_dir.parent,
    )
    if not jobs:
        return {
            "status": "skipped",
            "reason": f"no <page>.reading.json in {page_dir}",
        }
    target = outdir / "review" / "confidence"
    try:
        summary = confidence.review(jobs, target)
    except Exception as exc:  # noqa: BLE001 - same rule as above
        return {"status": "failed", "reason": str(exc)}
    print(
        f"confidence map: {summary['status']}, "
        f"{summary['issues']['total']} symbol(s) worth checking first"
    )
    return {**summary, "dir": str(target)}


@dataclass(frozen=True)
class ReviewHooks:
    """Injectable external tool hooks used by the delivery review runner."""

    run: Callable[[list[str], Path], int] = _run
    pdf_pages: Callable[[Path], int | None] = _pdf_pages
    render_pages: Callable[[Path, Path], int] = _render_pages
    find_musescore: Callable[[str | None], str | None] = find_musescore
    confidence_map: Callable[[Path, Path], dict] = _confidence_map
