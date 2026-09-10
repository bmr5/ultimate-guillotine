from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.prompt import footage_prompt, voiced_prompt
from ultimate_guillotine.video.script import Beat, Script


def test_prompt_describes_the_anchor_and_bans_on_screen_text() -> None:
    copy = TradeCopy(
        "pov: x",
        "SOURCES: PLAYER ALPHA TRADED TO CHARLIE",
        "Derek gets 450 FAAB · Charlie gets Player Alpha",
    )
    prompt = footage_prompt(copy, seconds=8)
    assert "00:00-00:08" in prompt
    assert "no on-screen text" in prompt and "no lower third" in prompt
    assert "derek gets 450 faab" in prompt
    assert "9:16" in prompt


def test_voiced_prompt_carries_the_read_as_timed_dialogue() -> None:
    copy = TradeCopy(
        "pov: x", "SOURCES: PLAYER ALPHA TRADED TO CHARLIE", "Charlie gets Player Alpha"
    )
    script = Script(
        beats=[
            Beat(start=0, end=3, direction="leans in", text="Breaking news."),
            Beat(
                start=3, end=12, direction="straight to lens", text="Player Alpha is on the move."
            ),
        ]
    )
    prompt = voiced_prompt(copy, script, seconds=12)
    assert "his own voice" in prompt and "audio: none" not in prompt
    assert '00:00-00:03  leans in: "Breaking news."' in prompt
    assert '00:03-00:12  straight to lens: "Player Alpha is on the move."' in prompt
    assert "lips synced to the dialogue, 12 seconds" in prompt
    assert "no on-screen text" in prompt
