"""The on-air read: what the generated insider says.

Written by the league's model backend in the cadence of an ESPN breaking-news
hit and sized to the clip: Seedance holds about 2.6 spoken words per second,
and a read that runs long outruns the video and breaks the lip sync. A template
read stands in when no model is reachable, so a render never waits on one.
"""

from pydantic import BaseModel

from ultimate_guillotine.ai.structured import StructuredOutputClient
from ultimate_guillotine.video.copy import TradeCopy

WORDS_PER_SECOND = 2.6
#: How far over the budget a read may run before it is sent back.
SLACK = 1.15
SCHEMA_NAME = "AnnouncementScript"

SYSTEM = (
    "You write the on-air read for an ESPN NFL insider breaking a fantasy football trade on "
    'live television, in the cadence of a real breaking-news hit: open on "Breaking news" '
    'or "Sources tell ESPN", short declarative sentences, the key detail landed with a beat '
    "of disbelief, an abrupt ending. The league is the Sovereign Guillotine League; the "
    "parties are league members, not NFL teams; FAAB is the league's waiver budget. State "
    "only the facts you are given: never invent contract terms, injuries, or reactions from "
    "real people. Keep the read at or under the word limit. Fill the whole clip: beats run "
    "from 0.0 to the clip length in order with no gaps, each with a one-phrase delivery "
    "direction (how he says it, where he looks, a pause, a small self-correction)."
)


class Beat(BaseModel):
    start: float
    end: float
    direction: str
    text: str


class Script(BaseModel):
    beats: list[Beat]

    @property
    def read(self) -> str:
        return " ".join(beat.text.strip() for beat in self.beats)

    @property
    def words(self) -> int:
        return len(self.read.split())


def word_budget(seconds: float) -> int:
    return int(seconds * WORDS_PER_SECOND)


def normalize(script: Script, seconds: float) -> Script:
    """Beats in order, clamped to the clip, the last one running to its end."""
    beats = sorted((b for b in script.beats if b.text.strip()), key=lambda b: b.start)
    fixed: list[Beat] = []
    for beat in beats:
        start = min(max(beat.start, 0.0), seconds)
        end = min(max(beat.end, start), seconds)
        fixed.append(Beat(start=start, end=end, direction=beat.direction, text=beat.text.strip()))
    if fixed:
        last = fixed[-1]
        fixed[-1] = Beat(start=last.start, end=seconds, direction=last.direction, text=last.text)
    return Script(beats=fixed)


def _sentence(copy: TradeCopy) -> str:
    """The headline as spoken prose: ``SOURCES: JOSH JACOBS TRADED TO CHARLIE``
    becomes ``Josh Jacobs traded to Charlie``."""
    body = copy.headline.removeprefix("SOURCES: ").title()
    for stiff, spoken in (
        (" Traded To ", " traded to "),
        (" And ", " and "),
        (" Agree To A Trade", " agree to a trade"),
        (" On The Move", " on the move"),
        ("Trade Agreed In The ", "trade agreed in the "),
    ):
        body = body.replace(stiff, spoken)
    return body


def template_script(copy: TradeCopy, seconds: float) -> Script:
    """A read built from the lower third alone, for when no model is reachable."""
    terms = ", ".join(part for part in copy.subline.split(" · ") if not part.startswith("Week "))
    beats = [
        Beat(start=0.0, end=seconds * 0.2, direction="leans in, urgent", text="Breaking news."),
        Beat(
            start=seconds * 0.2,
            end=seconds * 0.7,
            direction="straight to lens, measured",
            text=f"Sources tell ESPN: {_sentence(copy)}. {terms}.",
        ),
        Beat(
            start=seconds * 0.7,
            end=seconds,
            direction="small shake of the head, ends abruptly",
            text="The whole league is shaking.",
        ),
    ]
    script = Script(beats=beats)
    if script.words > word_budget(seconds):
        script = Script(beats=beats[:2])
    return normalize(script, seconds)


def script_from_text(text: str, seconds: float) -> Script:
    """A read Ben typed himself, as one beat across the clip."""
    return normalize(
        Script(beats=[Beat(start=0.0, end=seconds, direction="straight to lens", text=text)]),
        seconds,
    )


def _brief(copy: TradeCopy, seconds: float) -> str:
    return (
        f"Clip length: {seconds:g} seconds. Word limit: {word_budget(seconds)} words in total.\n"
        f"Lower third headline: {copy.headline}\n"
        f"Terms: {copy.subline}\n"
        f"Caption on screen, for context only: {copy.caption}"
    )


def generate_script(
    client: StructuredOutputClient, copy: TradeCopy, seconds: float, attempts: int = 2
) -> Script:
    """Ask the model for the read, sending it back once if it runs long."""
    budget = word_budget(seconds)
    user = _brief(copy, seconds)
    script = Script(beats=[])
    for _ in range(attempts):
        script, _usage = client.parse(SYSTEM, user, Script, SCHEMA_NAME)
        if script.beats and script.words <= budget * SLACK:
            break
        user += (
            f"\n\nYour previous read was {script.words} words; the limit is {budget}. "
            "Cut it down and keep the beats covering the whole clip."
        )
    return normalize(script, seconds)


def format_script(script: Script, seconds: float) -> str:
    """The read as the operator sees it: one beat per line, then the count."""
    lines = [
        f"{_stamp(beat.start)}-{_stamp(beat.end)}  ({beat.direction}) {beat.text}"
        for beat in script.beats
    ]
    lines.append(f"{script.words} words for {seconds:g} s (budget {word_budget(seconds)})")
    return "\n".join(lines)


def _stamp(seconds: float) -> str:
    return f"00:{round(seconds):02d}"
