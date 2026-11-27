"""Patch validation, application, and post-pipeline verification."""

from __future__ import annotations

from ..core.document import Document
from .clef import _apply_clef, _validate_clef, _verify_clef
from .ottava import _apply_ottava, _next_octave_number, _validate_ottava, _verify_ottava
from .tuplet import _apply_tuplet, _select_tuplet, _validate_tuplet, _verify_tuplet


def validate_patches(
    payload: dict, doc: Document | None = None, *, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    patches = payload.get("patches")
    if not isinstance(patches, list):
        return ["patches must be an array"]
    tuplet_plans: list[tuple[int, dict]] = []
    for index, patch in enumerate(patches):
        prefix = f"patches[{index}]"
        if not isinstance(patch, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        op = patch.get("op")
        if op == "ottava":
            problems.extend(_validate_ottava(patch, doc, prefix, require_acceptance))
            continue
        if op == "clef":
            problems.extend(_validate_clef(patch, doc, prefix))
            continue
        if op != "tuplet":
            problems.append(f"{prefix}: unsupported op {op!r}")
            continue
        plan, patch_problems = _validate_tuplet(patch, doc, prefix)
        problems.extend(patch_problems)
        if plan is None:
            continue
        for other_index, other in tuplet_plans:
            if plan["measure"] is other["measure"] and not (
                plan["end_index"] < other["start_index"]
                or plan["start_index"] > other["end_index"]
            ):
                problems.append(f"{prefix}: overlaps patches[{other_index}]")
                break
        else:
            tuplet_plans.append((index, plan))
    return problems


def apply_patches(doc: Document, payload: dict) -> int:
    """Apply validated patches; return directions written plus tuplet spans rewritten."""
    divisions = doc.divisions()
    measures = doc.measures()
    next_number = _next_octave_number(doc)
    patches = payload.get("patches") or []
    # Select every range before deleting forwards or changing durations shifts later onsets.
    tuplet_plans = {
        index: _select_tuplet(patch, doc, f"patches[{index}]")[0]
        for index, patch in enumerate(patches)
        if patch.get("op") == "tuplet"
    }
    changed = 0
    for index, patch in enumerate(patches):
        op = patch.get("op")
        if op == "tuplet":
            _apply_tuplet(tuplet_plans[index])
            changed += 1
        elif op == "clef":
            changed += _apply_clef(doc, patch)
        else:
            delta, next_number = _apply_ottava(doc, measures, patch, divisions, next_number)
            changed += delta
    return changed


def verify_patches(doc: Document, payload: dict) -> list[str]:
    """Check that applied patches still have their target notes/shifts after the pipeline."""
    problems: list[str] = []
    for index, patch in enumerate(payload.get("patches") or []):
        prefix = f"patches[{index}]"
        op = patch.get("op")
        if op == "ottava":
            problems.extend(_verify_ottava(doc, patch, prefix))
        elif op == "clef":
            problems.extend(_verify_clef(doc, patch, prefix))
        elif op == "tuplet":
            problems.extend(_verify_tuplet(doc, patch, prefix))
        else:
            problems.append(f"{prefix}: unsupported op {op!r}")
    return problems
