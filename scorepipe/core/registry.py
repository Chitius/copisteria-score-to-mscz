"""Registry sanity: names, phase membership and one writer per property inside a phase."""

from __future__ import annotations

from .pass_base import Pass, Phase


def validate_registry(passes: list[Pass], phase: Phase) -> list[str]:
    problems: list[str] = []
    names: set[str] = set()
    owners: dict[str, str] = {}
    for one_pass in passes:
        spec = one_pass.spec
        if spec.name in names:
            problems.append(f"duplicate pass name: {spec.name}")
        names.add(spec.name)
        if spec.phase is not phase:
            problems.append(f"{spec.name}: declared {spec.phase.value}, registered under {phase.value}")
        if spec.kind.value == "mechanical" and not spec.measure:
            problems.append(f"{spec.name}: mechanical pass without a monotone measure")
        for property_name in spec.owns:
            if property_name in owners:
                problems.append(
                    f"property {property_name} owned by both {owners[property_name]} and {spec.name}"
                )
            owners[property_name] = spec.name
    return problems


def validate_all(groups: dict[Phase, list[Pass]]) -> list[str]:
    problems: list[str] = []
    for phase, passes in groups.items():
        problems.extend(validate_registry(passes, phase))
    return problems
