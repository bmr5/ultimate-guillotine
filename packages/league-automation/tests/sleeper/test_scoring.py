import json
from decimal import Decimal
from pathlib import Path

from ultimate_guillotine.sleeper.scoring import (
    CENTS,
    DRIFT_POINTS,
    DRIFT_SHARE,
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

# The league's live scoring settings, read on 2026-09-09 and recorded verbatim in
# docs/superpowers/plans/2026-09-09-league-data-layer.md. Not a hand-picked subset:
# whatever the league prices is what the recorded projections are scored against.
FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
LEAGUE_SETTINGS = {
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -1.0, "pass_2pt": 2.0,
    "rush_yd": 0.1, "rush_td": 6.0, "rush_2pt": 2.0,
    "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rec_2pt": 2.0,
    "bonus_rec_te": 0.0, "bonus_rec_wr": 0.0, "bonus_rec_rb": 0.0,
    "fum_lost": -2.0, "fum_rec": 2.0, "def_td": 6.0, "int": 2.0, "sack": 1.0,
    "safe": 2.0, "ff": 1.0, "blk_kick": 2.0,
    "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0, "fgm_40_49": 4.0,
    "fgm_50p": 5.0, "xpm": 1.0,
    "pts_allow_0": 10.0, "pts_allow_1_6": 7.0, "pts_allow_7_13": 4.0,
    "pts_allow_14_20": 1.0, "pts_allow_21_27": 0.0, "pts_allow_28_34": -1.0,
    "pts_allow_35p": -4.0,
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
    """Every recorded row, scored by hand against the league's live settings.

    4943 (QB): 243.94*0.04 = 9.7576, 1.71*4 = 6.84, 0.9*-1 = -0.9, 0.1*2 = 0.2,
      9.79*0.1 = 0.979, 0.1*6 = 0.6, 0.19*-2 = -0.38 -> 17.0966 -> 17.10.
    7611 (RB): 2.94*1 + 20.57*0.1 + 0.12*6 + 72.39*0.1 + 0.59*6 + 0.07*-2
      + 2.94*0.0 -> 16.356 -> 16.36.
    9488 (WR): 6.83*1 + 94.17*0.1 + 0.53*6 + 1.85*0.1 + 0.03*-2 + 6.83*0.0
      -> 19.552 -> 19.55.
    12517 (TE): 5.1*1 + 62.78*0.1 + 0.46*6 + 0.02*-2 + 5.1*0.0 -> 14.098 -> 14.10.
    12713 (K): 0.05*3 + 0.25*3 + 0.45*3 + 0.4*4 + 2.4*1 = 0.15 + 0.75 + 1.35 + 1.6
      + 2.4 -> 6.25. Kickers ARE scorable: the league prices every made-field-goal
      band and the extra point; only `fga`, `fgm` and `fgm_yds` go unpriced.
    SEA (DEF): 0.05*2 (blk_kick) + 0.21*6 (def_td) + 0.78*1 (ff) + 0.57*2 (fum_rec)
      + 0.83*2 (int) + 1.0*1 (pts_allow_14_20) + 2.45*1 (sack) + 0.05*2 (safe)
      = 0.10 + 1.26 + 0.78 + 1.14 + 1.66 + 1.00 + 2.45 + 0.10 -> 8.49. The raw
      `pts_allow` of 20.75 is unpriced -- only the band keys are.
    10881 (IDP): every `idp_*` key is unpriced and the rest is denylisted -> None.
    """
    rows = json.loads(FIXTURE.read_text())
    scored = {r["player_id"]: score_stat_line(r["stats"], LEAGUE_SETTINGS) for r in rows}
    assert scored == {
        "4943": Decimal("17.10"),
        "7611": Decimal("16.36"),
        "9488": Decimal("19.55"),
        "12517": Decimal("14.10"),
        "12713": Decimal("6.25"),
        "SEA": Decimal("8.49"),
        "10881": None,
    }


def test_every_scored_row_tracks_sleepers_own_ppr_total() -> None:
    """The league's own totals stay well inside the drift alarm's threshold.

    This is the assertion that fires if a real payload key stops lining up with a
    scoring key: the dot product would still return a number, but it would wander
    away from Sleeper's `pts_ppr` for the same line.
    """
    rows = json.loads(FIXTURE.read_text())
    drifts = {}
    for row in rows:
        points = score_stat_line(row["stats"], LEAGUE_SETTINGS)
        if points is None:
            continue
        drifts[row["player_id"]] = abs(points - Decimal(str(row["stats"]["pts_ppr"])))
    assert set(drifts) == {"4943", "7611", "9488", "12517", "12713", "SEA"}
    assert all(drift < DRIFT_POINTS for drift in drifts.values()), drifts
    # preset_drift agrees with the hand subtraction on the widest row: 8.81 - 8.49.
    sea = next(r for r in rows if r["player_id"] == "SEA")
    assert preset_drift(Decimal("8.49"), sea["stats"]) == Decimal("0.32")


def test_drift_thresholds_are_the_values_later_tasks_depend_on() -> None:
    assert DRIFT_POINTS == Decimal(3)
    assert DRIFT_SHARE == Decimal("0.02")
    assert CENTS == Decimal("0.01")
