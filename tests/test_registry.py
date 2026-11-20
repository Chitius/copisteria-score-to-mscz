from __future__ import annotations

import unittest

from scorepipe.core.pass_base import Kind, PassResult, PassSpec, Phase
from scorepipe.core.registry import validate_all, validate_registry


class FakePass:
    def __init__(self, spec: PassSpec):
        self.spec = spec

    def run(self, doc, ctx):
        return PassResult()


def spec(name="p", phase=Phase.STRUCTURAL, owns=(), kind=Kind.MECHANICAL, measure="thing"):
    return PassSpec(name=name, phase=phase, owns=owns, kind=kind, measure=measure)


class RegistryTest(unittest.TestCase):
    def test_clean_registry(self):
        passes = [FakePass(spec(name="a", owns=("x",))), FakePass(spec(name="b", owns=("y",)))]
        self.assertEqual(validate_registry(passes, Phase.STRUCTURAL), [])

    def test_duplicate_names_are_reported(self):
        passes = [FakePass(spec(name="a")), FakePass(spec(name="a"))]
        self.assertTrue(any("duplicate pass name" in problem for problem in validate_registry(passes, Phase.STRUCTURAL)))

    def test_wrong_phase_is_reported(self):
        passes = [FakePass(spec(name="a", phase=Phase.DISPLAY))]
        self.assertTrue(any("registered under" in problem for problem in validate_registry(passes, Phase.STRUCTURAL)))

    def test_mechanical_pass_needs_a_measure(self):
        passes = [FakePass(spec(name="a", measure=""))]
        self.assertTrue(any("monotone measure" in problem for problem in validate_registry(passes, Phase.STRUCTURAL)))

    def test_two_owners_of_one_property_are_reported(self):
        passes = [FakePass(spec(name="a", owns=("x",))), FakePass(spec(name="b", owns=("x",)))]
        self.assertTrue(any("owned by both" in problem for problem in validate_registry(passes, Phase.STRUCTURAL)))

    def test_the_real_registry_is_clean(self):
        from scorepipe.passes import DISPLAY_PASSES, INJECT_PASSES, STRUCTURAL_PASSES

        problems = validate_all(
            {
                Phase.STRUCTURAL: STRUCTURAL_PASSES,
                Phase.INJECT: INJECT_PASSES,
                Phase.DISPLAY: DISPLAY_PASSES,
            }
        )
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
