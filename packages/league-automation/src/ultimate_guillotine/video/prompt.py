"""The Seedance prompt for generated footage.

Shot-breakdown form, like ugc-studio's ``prompts/seedance.md``. The words of
the trade go in as context only: the text layer is ours, so the model is told
to render no text at all -- generated captions are never right.
"""

from ultimate_guillotine.video.copy import TradeCopy


def footage_prompt(copy: TradeCopy, seconds: int) -> str:
    end = f"00:{seconds:02d}"
    return (
        "subject: a veteran NFL insider in a navy blazer and open collar, reporting from his "
        "home office, floor-to-ceiling bookshelves behind him, a football helmet on a shelf\n"
        "camera: static broadcast framing, chest-up, centred, 9:16 vertical\n"
        "audio: none\n"
        f"00:00-{end}  he delivers breaking news straight to lens with urgency, small emphatic "
        "hand gestures, eyebrows up on the key line, a beat of disbelief near the end\n"
        f"context, not to be shown: he is reporting that {copy.subline.lower()}\n"
        "no on-screen text, no lower third, no captions, no logos, no ticker; "
        "match the framing, lighting and pacing of the reference video; realistic skin, "
        "no beauty filter"
    )
