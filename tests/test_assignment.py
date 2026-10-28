"""Exhaustive cardinality-first assignment verification."""

import itertools
import random
import unittest
from dbc_compare_tool.core.assignment import solve_assignment


class AssignmentTests(unittest.TestCase):
    def test_exhaustive_all_small_graphs_max_cardinality_then_similarity(self):
        rng = random.Random(420)
        for rows, cols in ((1, 3), (3, 1), (2, 3), (3, 2), (3, 3)):
            positions = list(itertools.product(range(rows), range(cols)))
            for bits in range(1 << len(positions)):
                edges = {
                    p: rng.randrange(0, 101) / 100
                    for i, p in enumerate(positions)
                    if bits & (1 << i)
                }
                expected = (0, 0)
                for choices in itertools.product(range(-1, cols), repeat=rows):
                    used = [c for c in choices if c >= 0]
                    if len(used) != len(set(used)):
                        continue
                    pairs = [(r, c) for r, c in enumerate(choices) if c >= 0]
                    if all(p in edges for p in pairs):
                        expected = max(
                            expected,
                            (
                                len(pairs),
                                sum(round(edges[p] * 1_000_000) for p in pairs),
                            ),
                        )
                actual = solve_assignment(edges)
                self.assertEqual(
                    (len(actual), sum(round(edges[p] * 1_000_000) for p in actual)),
                    expected,
                )

    def test_quantization_ties_components_and_zero_similarity_edges(self):
        edges = {
            (0, 0): 1.0,
            (0, 1): 0.0,
            (1, 0): 0.0,
            (3, 4): 0.50000001,
            (3, 5): 0.50000002,
        }
        self.assertEqual(solve_assignment(edges), [(0, 1), (1, 0), (3, 4)])
        self.assertEqual(
            solve_assignment(dict(reversed(list(edges.items())))),
            solve_assignment(edges),
        )
