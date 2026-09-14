"""Mean-preserving scoring draws, with parameters fitted on historical player weeks."""

import json
import math
import random
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def parameters() -> dict:
    return json.loads(Path(__file__).with_name("distribution_parameters.json").read_text())


def draw_points(
    rng: random.Random, mean: float, variance: float, position: str, zero_probability: float = 0
) -> float:
    if variance <= 0:
        return mean
    if position == "DEF":
        # Defense can lose points during play; never clip a signed draw.
        return rng.gauss(mean, math.sqrt(variance))
    if mean <= 0:
        return mean
    # A zero-inflated gamma has an explicit bust probability and a right tail.
    # Bound the zero mass so its variance can coexist with the requested moments.
    p0 = min(max(zero_probability, 0), 0.95 * variance / (variance + mean * mean))
    if p0 and rng.random() < p0:
        return 0.0
    positive_mean = mean / (1 - p0)
    positive_var = (variance + mean * mean) / (1 - p0) - positive_mean * positive_mean
    if positive_var <= 1e-12:
        return positive_mean
    return rng.gammavariate(
        positive_mean * positive_mean / positive_var, positive_var / positive_mean
    )
