"""The on-air read: what the generated insider says.

Written by the league's model backend in the cadence of an ESPN breaking-news
hit. The read decides the clip: Seedance holds about 2.6 spoken words per
second and renders 4 to 15 seconds, so the writer is asked for the shortest
read the trade allows and the clip is sized to it. A read that runs long for
its clip outruns the video and breaks the lip sync. A template read stands in
when no model is reachable, so a render never waits on one.
"""

import math
import re

from pydantic import BaseModel

from ultimate_guillotine.ai.structured import StructuredOutputClient
from ultimate_guillotine.video.copy import TradeCopy

WORDS_PER_SECOND = 2.6
#: How far over the budget a read may run before it is sent back.
SLACK = 1.15
SCHEMA_NAME = "AnnouncementScript"
#: Seedance renders 4 to 15 seconds. A simple swap is about 20 words and 8
#: seconds; the longest read that fits is 39 words.
MIN_SECONDS = 4
MAX_SECONDS = 15
#: What a plain two-side trade should come in at.
TYPICAL_WORDS = 20

SYSTEM = (
    "You write the on-air read for an ESPN NFL insider breaking a fantasy football trade on "
    'live television, in the cadence of a real breaking-news hit: open on "Breaking news" '
    'or "Sources tell ESPN", short declarative sentences, the key detail landed with a beat '
    "of disbelief, an abrupt ending. The league is the Sovereign Guillotine League; the "
    "parties are league members, not NFL teams. Waiver money is spoken as plain dollars "
    '("twenty dollars"); never say FAAB on air. State only the facts you are given: never '
    "invent contract terms, injuries, or reactions from real people. The brief lists the "
    "trade fact by fact under the announcement as it was posted, and the announcement wins "
    "any disagreement. A side can give a player, waiver dollars, real dollars, or an "
    "obligation: a favor, a duty, a place taken. In this league the gulag is where the "
    "week's two lowest scorers fight for survival, and a member may pay another to take his "
    "place in it: whoever takes the place goes to the gulag, whoever pays stays out. Say who "
    "does what for whom, and never swap the one who is paid with the one who pays. The "
    "commissioner is 'the Commish' on air, even where the announcement says Ben. Keep the "
    "read at or under the word limit, and as short as the facts allow: a plain two-side "
    "swap in about "
    "twenty words; a bigger deal condensed, never rushed. Fill the whole clip: beats run "
    "from 0.0 to the end of the read in order with no gaps, each with a one-phrase delivery "
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


def seconds_for(script: Script) -> int:
    """The clip length a read needs: its words at 2.6 a second, one second of
    air for the ending, inside what Seedance renders."""
    needed = math.ceil(script.words / WORDS_PER_SECOND) + 1
    return max(MIN_SECONDS, min(MAX_SECONDS, needed))


def script_seconds(script: Script) -> int:
    """The clip length a normalized read runs to: the end of its last beat."""
    return math.ceil(script.beats[-1].end) if script.beats else MIN_SECONDS


_FAAB = re.compile(r"\b(\d+) FAAB\b")


def spoken(text: str) -> str:
    """The terms as they are said on air: ``450 FAAB`` is ``450 dollars`` and
    ``Player + 20 dollars`` is ``Player and 20 dollars``. The lower third keeps
    the league's own wording; the voice model handles plain words better
    (Ben, 2026-09-10)."""
    return _FAAB.sub(r"\1 dollars", text).replace(" + ", " and ")


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
    for stiff, said in (
        (" Traded To ", " traded to "),
        (" And ", " and "),
        (" Agree To A Trade", " agree to a trade"),
        (" On The Move", " on the move"),
        ("Trade Agreed In The ", "trade agreed in the "),
    ):
        body = body.replace(stiff, said)
    return body


def template_script(copy: TradeCopy, seconds: float | None = None) -> Script:
    """A read built from the lower third alone, for when no model is reachable.
    With no ``seconds`` the clip is sized to the read."""
    terms = spoken(
        ", ".join(part for part in copy.subline.split(" · ") if not part.startswith("Week "))
    )
    lines = [
        ("leans in, urgent", "Breaking news."),
        ("straight to lens, measured", f"Sources tell ESPN: {_sentence(copy)}. {terms}."),
        ("small shake of the head, ends abruptly", "The whole league is shaking."),
    ]
    words = len(" ".join(text for _direction, text in lines).split())
    if seconds is None:
        seconds = max(MIN_SECONDS, min(MAX_SECONDS, math.ceil(words / WORDS_PER_SECOND) + 1))
    elif words > word_budget(seconds):
        lines = lines[:2]
    shares = [(0.0, 0.2), (0.2, 0.7), (0.7, 1.0)][: len(lines)]
    beats = [
        Beat(start=seconds * a, end=seconds * b, direction=direction, text=text)
        for (a, b), (direction, text) in zip(shares, lines, strict=True)
    ]
    return normalize(Script(beats=beats), seconds)


def script_from_text(text: str, seconds: float | None = None) -> Script:
    """A read Ben typed himself, as one beat across the clip; with no ``seconds``
    the clip is sized to the words."""
    script = Script(beats=[Beat(start=0.0, end=0.0, direction="straight to lens", text=text)])
    if seconds is None:
        seconds = seconds_for(script)
    return normalize(script, seconds)


def _brief(copy: TradeCopy, seconds: float | None) -> str:
    if seconds is None:
        length = (
            f"Clip length: as short as the facts allow, up to {MAX_SECONDS} seconds. "
            f"Word limit: {word_budget(MAX_SECONDS)} words in total; a plain two-side swap "
            f"should be about {TYPICAL_WORDS}."
        )
    else:
        length = (
            f"Clip length: {seconds:g} seconds. Word limit: {word_budget(seconds)} words in total."
        )
    facts = "".join(f"- {spoken(fact)}\n" for fact in copy.facts)
    if facts:
        facts = f"The trade, fact by fact (state only these):\n{facts}"
    return (
        f"{length}\n"
        f"Lower third headline: {spoken(copy.headline)}\n"
        f"Terms, with waiver money in dollars: {spoken(copy.subline)}\n"
        f"{facts}"
        f"Caption on screen, for context only: {copy.caption}"
    )


def generate_script(
    client: StructuredOutputClient,
    copy: TradeCopy,
    seconds: float | None = None,
    attempts: int = 2,
) -> Script:
    """Ask the model for the read, sending it back once if it runs long.

    With no ``seconds`` the read decides the length: the writer is asked for the
    shortest read the trade allows and the clip is sized to it (``seconds_for``),
    so a two-player swap is an 8 s clip and a three-team blockbuster gets up to 15.
    """
    budget = word_budget(MAX_SECONDS if seconds is None else seconds)
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
    return normalize(script, seconds_for(script) if seconds is None else seconds)


def format_script(script: Script, seconds: float | None = None) -> str:
    """The read as the operator sees it: one beat per line, then the count."""
    seconds = script_seconds(script) if seconds is None else seconds
    lines = [
        f"{_stamp(beat.start)}-{_stamp(beat.end)}  ({beat.direction}) {beat.text}"
        for beat in script.beats
    ]
    lines.append(f"{script.words} words for {seconds:g} s (budget {word_budget(seconds)})")
    return "\n".join(lines)


def _stamp(seconds: float) -> str:
    return f"00:{round(seconds):02d}"
