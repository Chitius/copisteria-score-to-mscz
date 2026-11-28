"""Patch validation, application, and post-pipeline verification."""

from __future__ import annotations

from ..core.document import Document
from .arpeggio import _apply_arpeggio, _next_arpeggio_number, _validate_arpeggio, _verify_arpeggio
from .clef import _apply_clef, _validate_clef, _verify_clef
from .common import _resolve_patch_part
from .dynamic import _apply_dynamic, _validate_dynamic, _verify_dynamic
from .fermata import _apply_fermata, _validate_fermata, _verify_fermata
from .glissando import _apply_glissando, _next_glissando_number, _validate_glissando, _verify_glissando
from .navigation import _apply_navigation, _validate_navigation, _verify_navigation
from .ornament import _apply_ornament, _validate_ornament, _verify_ornament
from .ottava import _apply_ottava, _next_octave_number, _validate_ottava, _verify_ottava
from .parentheses import _apply_parentheses, _validate_parentheses, _verify_parentheses
from .pedal import _apply_pedal, _next_pedal_number, _validate_pedal, _verify_pedal
from .repeat import _apply_repeat, _validate_repeat, _verify_repeat
from .tuplet import _apply_tuplet, _select_tuplet, _validate_tuplet, _verify_tuplet
from .volta import _apply_volta, _validate_volta, _verify_volta
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
        if op == "repeat":
            problems.extend(_validate_repeat(patch, doc, prefix, require_acceptance))
            continue
        if op == "volta":
            problems.extend(_validate_volta(patch, doc, prefix, require_acceptance))
            continue
        if op == "fermata":
            problems.extend(_validate_fermata(patch, doc, prefix, require_acceptance))
            continue
        if op == "navigation":
            problems.extend(_validate_navigation(patch, doc, prefix, require_acceptance))
            continue
        if op == "ornament":
            problems.extend(_validate_ornament(patch, doc, prefix, require_acceptance))
            continue
        if op == "glissando":
            problems.extend(_validate_glissando(patch, doc, prefix, require_acceptance))
            continue
        if op == "arpeggio":
            problems.extend(_validate_arpeggio(patch, doc, prefix, require_acceptance))
            continue
        if op == "parentheses":
            problems.extend(_validate_parentheses(patch, doc, prefix, require_acceptance))
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
        elif op in ("dynamic", "repeat", "volta", "fermata", "navigation", "ornament", "parentheses"):
            part_id, part, _problems = _resolve_patch_part(patch, doc, f"patches[{index}]")
            assert part is not None and part_id is not None
            if op == "dynamic":
                changed += _apply_dynamic(doc, part_id, part, patch)
            elif op == "repeat":
                changed += _apply_repeat(doc, part_id, part, patch)
            elif op == "volta":
                changed += _apply_volta(doc, part_id, part, patch)
            elif op == "fermata":
                changed += _apply_fermata(doc, part_id, part, patch)
            elif op == "navigation":
                changed += _apply_navigation(doc, part_id, part, patch)
            elif op == "ornament":
                changed += _apply_ornament(doc, part_id, part, patch)
            else:
                changed += _apply_parentheses(doc, part_id, part, patch)
        elif op in ("ottava", "pedal", "wedge", "glissando", "arpeggio"):
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
            elif op == "wedge":
                next_number = part_counters.get("wedge") or _next_wedge_number(doc, part_id)
                delta, next_number = _apply_wedge(doc, part_id, part, patch, next_number)
                part_counters["wedge"] = next_number
            elif op == "glissando":
                next_number = part_counters.get("glissando") or _next_glissando_number(doc, part_id)
                delta, next_number = _apply_glissando(doc, part_id, part, patch, next_number)
                part_counters["glissando"] = next_number
            else:
                next_number = part_counters.get("arpeggio") or _next_arpeggio_number(doc, part_id)
                delta, next_number = _apply_arpeggio(doc, part_id, part, patch, next_number)
                part_counters["arpeggio"] = next_number
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
        elif op == "repeat":
            problems.extend(_verify_repeat(doc, patch, prefix))
        elif op == "volta":
            problems.extend(_verify_volta(doc, patch, prefix))
        elif op == "fermata":
            problems.extend(_verify_fermata(doc, patch, prefix))
        elif op == "navigation":
            problems.extend(_verify_navigation(doc, patch, prefix))
        elif op == "ornament":
            problems.extend(_verify_ornament(doc, patch, prefix))
        elif op == "glissando":
            problems.extend(_verify_glissando(doc, patch, prefix))
        elif op == "arpeggio":
            problems.extend(_verify_arpeggio(doc, patch, prefix))
        elif op == "parentheses":
            problems.extend(_verify_parentheses(doc, patch, prefix))
        elif op == "clef":
            problems.extend(_verify_clef(doc, patch, prefix))
        elif op == "tuplet":
            problems.extend(_verify_tuplet(doc, patch, prefix))
        else:
            problems.append(f"{prefix}: unsupported op {op!r}")
    return problems
