"""League scoring as a pure dot product over Sleeper's stat keys.

Sleeper uses the same keys in a projection's ``stats`` map and in a league's
``scoring_settings``, so multiplying the two maps key-by-key and summing is
exactly the league's scoring rule -- bonuses and negatives included -- with no
per-format special cases. Nothing here touches the network or the database.

Public interface: :data:`SCORING_DENYLIST`, :func:`score_stat_line`,
:func:`scoring_version`, :func:`preset_drift`, :data:`DRIFT_POINTS`,
:data:`DRIFT_SHARE`, and :data:`CENTS` -- the one quantization constant, exported
so later tasks round money and points to the same place rather than redefining it.
"""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

#: Sleeper's own convenience totals and draft metadata. They are numbers that share the
#: namespace with real stats but are not stats: scoring them would double-count (the
#: presets) or invent points out of an average draft position.
SCORING_DENYLIST = frozenset({
    "pts_ppr",
    "pts_half_ppr",
    "pts_std",
    "gp",
    "gms_active",
    "adp_dd_ppr",
    "pos_adp_dd_ppr",
    "cmp_pct",
})

_PRESET_KEYS = ("pts_ppr", "pts_half_ppr", "pts_std")

#: Two decimal places: the quantum every point and dollar total in this package rounds to.
CENTS = Decimal("0.01")

#: A run posts one drift note when more than DRIFT_SHARE of scored players sit further
#: than DRIFT_POINTS from the nearest Sleeper preset.
DRIFT_POINTS = Decimal(3)
DRIFT_SHARE = Decimal("0.02")


def _number(value: object) -> Decimal | None:
    """Return ``value`` as a Decimal, or None when it is not a plain number.

    ``bool`` is excluded explicitly: it is a subclass of ``int`` and a True in a
    stat map is a flag someone added, not one point.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def score_stat_line(
    stat_line: dict[str, object], scoring_settings: dict[str, object]
) -> Decimal | None:
    """Dot-product ``stat_line`` with ``scoring_settings``, rounded half-up to cents.

    Returns ``None`` when not one key could be scored: that is a missing
    projection, and a missing projection is never a zero.
    """
    total = Decimal(0)
    scored = 0
    for key, raw in stat_line.items():
        if key in SCORING_DENYLIST:
            continue
        stat = _number(raw)
        weight = _number(scoring_settings.get(key))
        if stat is None or weight is None:
            continue
        total += stat * weight
        scored += 1
    if scored == 0:
        return None
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)


def scoring_version(scoring_settings: dict[str, object]) -> str:
    """A short, stable fingerprint of the league's scoring rules.

    Keys are sorted and values coerced to float so a settings blob that Sleeper
    re-serializes differently still fingerprints the same.
    """
    canonical = {}
    for key in sorted(scoring_settings):
        value = _number(scoring_settings[key])
        if value is not None:
            canonical[key] = float(value)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def preset_drift(
    league_points: Decimal | None, stat_line: dict[str, object]
) -> Decimal | None:
    """Distance from ``league_points`` to the nearest Sleeper preset in ``stat_line``.

    A large drift across many players means the stat keys stopped lining up with
    the scoring keys, which is the one failure mode the dot product cannot see.
    """
    if league_points is None:
        return None
    presets = [p for p in (_number(stat_line.get(k)) for k in _PRESET_KEYS) if p is not None]
    if not presets:
        return None
    return min(abs(league_points - preset) for preset in presets)
