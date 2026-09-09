import json
from decimal import Decimal
from pathlib import Path

from ultimate_guillotine.sleeper.scoring import (
    SCORING_DENYLIST,
    preset_drift,
    score_stat_line,
    scoring_version,
)

# A deliberately tiny league so every expected number is hand-computable.
SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fum_lost": -2.0,
    "bonus_rec_te": 0.5,
    "pts_ppr": 1.0,  # present in settings but never scorable: it is a preset, not a stat
}

# The league's real scoring settings, against the recorded week-1 projections.
FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
LEAGUE_SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rush_td": 6.0,
    "fum_lost": -2.0,
    "bonus_rec_te": 0.0,
    "pts_allow_14_20": 1.0,
}


def test_dot_product_matches_a_hand_computed_line() -> None:
    # 243.94 * 0.04 = 9.7576; 1.71 * 4 = 6.84; 0.9 * -1 = -0.9; 0.19 * -2 = -0.38
    # total 15.3176 -> 15.32
    line = {"pass_yd": 243.94, "pass_td": 1.71, "pass_int": 0.9, "fum_lost": 0.19,
            "gp": 1.0, "pts_ppr": 17.11}
    assert score_stat_line(line, SETTINGS) == Decimal("15.32")


def test_bonuses_and_negatives_both_land_in_the_product() -> None:
    # 5.1 * 1 + 62.78 * 0.1 + 0.46 * 6 + 5.1 * 0.5 = 5.1 + 6.278 + 2.76 + 2.55 = 16.688
    line = {"rec": 5.1, "rec_yd": 62.78, "rec_td": 0.46, "bonus_rec_te": 5.1}
    assert score_stat_line(line, SETTINGS) == Decimal("16.69")


def test_rounding_is_half_up_not_bankers() -> None:
    # 0.125 * 1 = 0.125 -> 0.13, and 0.135 -> 0.14. Python's round() gives 0.12 and 0.14.
    assert score_stat_line({"rec": 0.125}, {"rec": 1.0}) == Decimal("0.13")
    assert score_stat_line({"rec": 0.135}, {"rec": 1.0}) == Decimal("0.14")


def test_presets_and_denylisted_keys_never_enter_the_product() -> None:
    assert "pts_ppr" in SCORING_DENYLIST and "gp" in SCORING_DENYLIST
    assert "adp_dd_ppr" in SCORING_DENYLIST and "pos_adp_dd_ppr" in SCORING_DENYLIST
    # pts_ppr carries a scoring value in SETTINGS and still contributes nothing.
    assert score_stat_line({"rec": 2.0, "pts_ppr": 99.0}, SETTINGS) == Decimal("2.00")


def test_unscorable_line_is_none_not_zero() -> None:
    idp_only = {"idp_tkl": 2.98, "idp_int": 0.11, "gp": 1.0, "pts_ppr": 0.22}
    assert score_stat_line(idp_only, SETTINGS) is None


def test_a_line_of_scorable_zeros_is_zero_not_none() -> None:
    assert score_stat_line({"rec": 0.0}, SETTINGS) == Decimal("0.00")


def test_non_numeric_and_boolean_values_are_skipped() -> None:
    assert score_stat_line({"rec": "3", "rec_td": None, "pass_td": True}, SETTINGS) is None
    assert score_stat_line({"rec": "3", "rec_yd": 10.0}, SETTINGS) == Decimal("1.00")


def test_scoring_version_is_twelve_hex_chars_stable_and_order_independent() -> None:
    version = scoring_version(SETTINGS)
    assert len(version) == 12 and all(c in "0123456789abcdef" for c in version)
    assert version == scoring_version(dict(reversed(list(SETTINGS.items()))))
    assert version != scoring_version({**SETTINGS, "rec": 0.5})


def test_preset_drift_measures_distance_to_the_nearest_preset() -> None:
    line = {"pts_ppr": 19.69, "pts_half_ppr": 16.28, "pts_std": 12.86}
    assert preset_drift(Decimal("16.00"), line) == Decimal("0.28")
    assert preset_drift(None, line) is None
    assert preset_drift(Decimal("16.00"), {"gp": 1.0}) is None


def test_recorded_projections_score_against_the_real_league_settings() -> None:
    rows = json.loads(FIXTURE.read_text())
    scored = {r["player_id"]: score_stat_line(r["stats"], LEAGUE_SETTINGS) for r in rows}
    assert scored == {
        "4943": Decimal("15.92"),  # QB: passing, a rushing TD, a fumble
        "7611": Decimal("9.12"),  # RB: bonus_rec_rb is unpriced and drops out
        "9488": Decimal("19.37"),  # WR
        "12517": Decimal("14.10"),  # TE: bonus_rec_te is priced at zero, still scored
        "12713": None,  # K: no kicking key is priced, so no projection at all
        "SEA": Decimal("1.00"),  # DEF: only the points-allowed band is priced
        "10881": None,  # IDP: nothing in the line is priced
    }
    # The WR's 19.37 sits close to Sleeper's own PPR total of 19.69.
    wr = next(r for r in rows if r["player_id"] == "9488")
    assert preset_drift(scored["9488"], wr["stats"]) == Decimal("0.32")
