from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.prompt import footage_prompt


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
