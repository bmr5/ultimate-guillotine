"""The Seedance prompts for generated footage.

Shot-breakdown form, like ugc-studio's ``prompts/seedance.md``. The words of
the trade go in as context only: the text layer is ours, so the model is told
to render no text at all -- generated captions are never right. The voiced
prompt adds the read as timed, quoted dialogue, which is how Seedance is told
what the character says and when.
"""

from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.script import Script

SUBJECT = (
    "subject: a veteran NFL insider in a navy blazer and open collar, reporting from his "
    "home office, floor-to-ceiling bookshelves behind him, a football helmet on a shelf\n"
    "camera: static broadcast framing, chest-up, centred, 9:16 vertical, one continuous shot\n"
)
NO_TEXT = (
    "no on-screen text, no lower third, no captions, no logos, no ticker, nothing written "
    "anywhere in frame; match the person, framing, lighting and pacing of the reference "
    "video; realistic skin, no beauty filter"
)


def _stamp(seconds: float) -> str:
    return f"00:{round(seconds):02d}"


def footage_prompt(copy: TradeCopy, seconds: int) -> str:
    """Silent footage: the insider delivering news, words supplied by our overlay."""
    return (
        SUBJECT + "audio: none\n"
        f"00:00-{_stamp(seconds)}  he delivers breaking news straight to lens with urgency, "
        "small emphatic hand gestures, eyebrows up on the key line, a beat of disbelief near "
        "the end\n"
        f"context, not to be shown: he is reporting that {copy.subline.lower()}\n" + NO_TEXT
    )


def voiced_prompt(copy: TradeCopy, script: Script, seconds: int) -> str:
    """Footage that speaks: each beat of the read as timed, quoted dialogue."""
    beats = "\n".join(
        f'{_stamp(beat.start)}-{_stamp(beat.end)}  {beat.direction}: "{beat.text}"'
        for beat in script.beats
    )
    return (
        SUBJECT + "audio: his own voice, clear broadcast microphone, urgent breaking-news "
        "delivery, no music, no other voices\n"
        f"{beats}\n"
        f"lips synced to the dialogue, {seconds} seconds, he finishes on the last word\n"
        f"context, not to be shown: the lower third reads {copy.headline}\n" + NO_TEXT
    )
