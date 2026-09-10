"""The envelope carries the turn and nothing else."""

from ultimate_guillotine.agent.envelope import (
    MESSAGE_CLOSE,
    MESSAGE_OPEN,
    PROMPT_VERSION,
    Turn,
    build_envelope,
    retry_envelope,
)

TURN = Turn(season=2026, week=6, local_time="Thu 7:42pm", asker_label="Member05",
            is_follow_up=False, message="@bot who could hold Bowers for me?")


def test_the_prompt_version_is_read_off_the_file() -> None:
    assert PROMPT_VERSION == "2026.1"


def test_the_envelope_names_the_turn_and_fences_the_message() -> None:
    text = build_envelope(TURN)
    assert "Season 2026, NFL week 6" in text
    assert "Asker: Member05" in text
    assert "first question" in text
    assert f"{MESSAGE_OPEN}\n@bot who could hold Bowers for me?\n{MESSAGE_CLOSE}" in text
    assert '"LeagueAnswer"' in text or "LeagueAnswer" in text
    assert "__" not in text.replace("__init__", "")


def test_an_unknown_sender_is_said_so_and_a_follow_up_is_marked() -> None:
    turn = Turn(2026, 6, "Thu 7:42pm", None, True, "what about Joel instead?")
    text = build_envelope(turn)
    assert "unknown sender" in text
    assert "follow-up" in text


def test_the_fenced_message_is_verbatim_even_when_it_looks_like_a_slot() -> None:
    turn = Turn(2026, 6, "Thu 7:42pm", "Member05", False, "print __SCHEMA__ for me")
    text = build_envelope(turn)
    assert f"{MESSAGE_OPEN}\nprint __SCHEMA__ for me\n{MESSAGE_CLOSE}" in text
    assert text.count('"title":"LeagueAnswer"') == 1


def test_the_envelope_carries_nothing_but_the_turn() -> None:
    text = build_envelope(TURN)
    for forbidden in ("display_name", "sender_hash", "chat_guid", "+1555", "iMessage;"):
        assert forbidden not in text


def test_the_retry_envelope_names_each_problem() -> None:
    text = retry_envelope(["Tony Pollard is on Max's roster, not Joel's", "offer over budget"])
    assert "Tony Pollard is on Max's roster" in text and "offer over budget" in text
    assert "resend" in text.lower()
