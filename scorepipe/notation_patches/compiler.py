"""Patch validation, application, and post-pipeline verification."""

from __future__ import annotations

from ..core.document import Document
from .clef import _apply_clef, _validate_clef, _verify_clef
from .common import _resolve_patch_part
from .dynamic import _apply_dynamic, _validate_dynamic, _verify_dynamic
from .ottava import _apply_ottava, _next_octave_number, _validate_ottava, _verify_ottava
from .pedal import _apply_pedal, _next_pedal_number, _validate_pedal, _verify_pedal
from .tuplet import _apply_tuplet, _select_tuplet, _validate_tuplet, _verify_tuplet
from .wedge import _apply_wedge, _next_wedge_number, _validate_wedge, _verify_wedge


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
        if op == "pedal":
            problems.extend(_validate_pedal(patch, doc, prefix, require_acceptance))
            continue
        if op == "wedge":
            problems.extend(_validate_wedge(patch, doc, prefix, require_acceptance))
            continue
        if op == "dynamic":
            problems.extend(_validate_dynamic(patch, doc, prefix, require_acceptance))
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
    next_number_by_part: dict[str, dict[str, int]] = {}
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
        elif op == "dynamic":
            part_id, part, _problems = _resolve_patch_part(patch, doc, f"patches[{index}]")
            assert part is not None and part_id is not None
            changed += _apply_dynamic(doc, part_id, part, patch)
        elif op in ("ottava", "pedal", "wedge"):
            part_id, part, _problems = _resolve_patch_part(patch, doc, f"patches[{index}]")
            assert part is not None and part_id is not None
            part_counters = next_number_by_part.setdefault(part_id, {})
            if op == "ottava":
                next_number = part_counters.get("ottava") or _next_octave_number(doc, part_id)
                delta, next_number = _apply_ottava(doc, part_id, part, patch, next_number)
                part_counters["ottava"] = next_number
            elif op == "pedal":
                next_number = part_counters.get("pedal") or _next_pedal_number(doc, part_id)
                delta, next_number = _apply_pedal(doc, part_id, part, patch, next_number)
                part_counters["pedal"] = next_number
            else:
                next_number = part_counters.get("wedge") or _next_wedge_number(doc, part_id)
                delta, next_number = _apply_wedge(doc, part_id, part, patch, next_number)
                part_counters["wedge"] = next_number
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
        elif op == "pedal":
            problems.extend(_verify_pedal(doc, patch, prefix))
        elif op == "wedge":
            problems.extend(_verify_wedge(doc, patch, prefix))
        elif op == "dynamic":
            problems.extend(_verify_dynamic(doc, patch, prefix))
        elif op == "clef":
            problems.extend(_verify_clef(doc, patch, prefix))
        elif op == "tuplet":
            problems.extend(_verify_tuplet(doc, patch, prefix))
        else:
            problems.append(f"{prefix}: unsupported op {op!r}")
    return problems
