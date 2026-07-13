"""Deterministic regression ordering and seed planning."""

import random


def ordered_regression_tests(all_vcomp):
    """Return vcomp and test mappings in stable lexical order."""
    return {vcomp: dict(sorted(all_vcomp[vcomp].items())) for vcomp in sorted(all_vcomp)}


def plan_test_seeds(all_vcomp, python_seed):
    """Assign deterministic seeds to every planned test iteration."""
    rng = random.Random(python_seed)
    return {
        (vcomp, test, iteration): rng.randint(0, (1 << 31) - 1)
        for vcomp, tests in ordered_regression_tests(all_vcomp).items()
        for test, iterations in tests.items()
        for iteration in range(1, iterations + 1)
    }
