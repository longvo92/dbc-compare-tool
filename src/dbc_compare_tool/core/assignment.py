"""Deterministic cardinality-first assignment on independent bipartite components."""

from __future__ import annotations

from collections import defaultdict


def solve_assignment(
    edges: dict[tuple[int, int], float], *, scale: int = 1_000_000
) -> list[tuple[int, int]]:
    """Maximize pair count, then quantized similarity; sorted indices break ties.

    Isolated vertices need no matrix. Components and a smaller row axis bound
    solver memory without discarding any eligible candidate.
    """
    adjacency = defaultdict(set)
    for old, new in edges:
        adjacency[0, old].add((1, new))
        adjacency[1, new].add((0, old))
    remaining = set(adjacency)
    selected = []
    while remaining:
        first = min(remaining)
        remaining.remove(first)
        component, stack = {first}, [first]
        while stack:
            for other in sorted(adjacency[stack.pop()]):
                if other not in component:
                    component.add(other)
                    remaining.discard(other)
                    stack.append(other)
        old = sorted(i for side, i in component if side == 0)
        new = sorted(i for side, i in component if side == 1)
        transpose = len(old) > len(new)
        rows, columns = (new, old) if transpose else (old, new)
        row_index, col_index = (
            {v: i for i, v in enumerate(rows)},
            {v: i for i, v in enumerate(columns)},
        )
        bonus = (len(rows) + 1) * (scale + 1)
        matrix = [[0] * (len(columns) + len(rows)) for _ in rows]
        for i in old:
            for side, j in adjacency[0, i]:
                key = (i, j)
                row, col = (j, i) if transpose else (i, j)
                matrix[row_index[row]][col_index[col]] = bonus + round(
                    edges[key] * scale
                )
        for row, col in enumerate(_maximum_assignment(matrix)):
            if col < len(columns):
                key = (
                    (columns[col], rows[row])
                    if transpose
                    else (rows[row], columns[col])
                )
                if key in edges:
                    selected.append(key)
    return sorted(selected)


def _maximum_assignment(scores: list[list[float]]) -> list[int]:
    """Rectangular Hungarian assignment; rows <= columns, O(rows² * columns)."""
    if not scores:
        return []
    rows, columns = len(scores), len(scores[0])
    u, v = [0] * (rows + 1), [0] * (columns + 1)
    owner, previous = [0] * (columns + 1), [0] * (columns + 1)
    for row in range(1, rows + 1):
        owner[0] = row
        column = 0
        distance = [float("inf")] * (columns + 1)
        visited = [False] * (columns + 1)
        while True:
            visited[column] = True
            current = owner[column]
            delta, next_column = float("inf"), 0
            for other in range(1, columns + 1):
                if visited[other]:
                    continue
                cost = -scores[current - 1][other - 1] - u[current] - v[other]
                if cost < distance[other]:
                    distance[other], previous[other] = cost, column
                if distance[other] < delta:
                    delta, next_column = distance[other], other
            for other in range(columns + 1):
                if visited[other]:
                    u[owner[other]] += delta
                    v[other] -= delta
                else:
                    distance[other] -= delta
            column = next_column
            if owner[column] == 0:
                break
        while column:
            owner[column] = owner[previous[column]]
            column = previous[column]
    assignment = [-1] * rows
    for column in range(1, columns + 1):
        if owner[column]:
            assignment[owner[column] - 1] = column - 1
    return assignment
