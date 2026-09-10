"""`ug video` subcommands: the trade announcement video pipeline.

``assets`` checks the archived reference media and the tools; ``card`` draws
the text layer alone so the words can be checked; ``cost`` asks Higgsfield
what one generated clip would charge; ``render`` makes the whole video, over
the archived ESPN footage, over footage Seedance 2.5 generates from the
reference, or over a clip Ben points at.
"""

import argparse
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.ai.structured import StructuredOutputClient
from ultimate_guillotine.cli.deps import build_delivery, build_deps, run_scheduled
from ultimate_guillotine.config import load_settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.data.repositories import MemberAliasRepository, RunRepository
from ultimate_guillotine.trades.format import party_labels
from ultimate_guillotine.trades.models import TradeProposal
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.video import higgsfield as hf
from ultimate_guillotine.video.assets import (
    REFERENCE_DURATION,
    ToolMissing,
    find_tool,
    load_assets,
)
from ultimate_guillotine.video.card import CANVAS, Layout, render_card
from ultimate_guillotine.video.copy import TradeCopy, default_caption, trade_copy
from ultimate_guillotine.video.jobs import VideoJobRepository
from ultimate_guillotine.video.pipeline import RenderError, RenderRequest, prepare, render
from ultimate_guillotine.video.prompt import footage_prompt, voiced_prompt
from ultimate_guillotine.video.script import (
    Script,
    format_script,
    generate_script,
    script_from_text,
    template_script,
)
from ultimate_guillotine.video.worker import Worker

TOOLS = ("ffmpeg", "ffprobe", "higgsfield")
#: The ESPN source clip's frame; a card for manual copy is laid out for it.
SOURCE_FRAME = (1280, 720)
RESOLUTIONS = ("480p", "720p", "1080p")
#: Music under a spoken read; the reference has no voice, so its music sits at 0 dB.
VOICED_MUSIC_GAIN_DB = -12.0


def register(subparsers) -> None:
    parser = subparsers.add_parser("video", help="trade announcement video pipeline")
    video_sub = parser.add_subparsers(dest="command", required=True)

    assets = video_sub.add_parser("assets", help="check the reference media and tools are in place")
    assets.set_defaults(handler=cmd_assets)

    card = video_sub.add_parser("card", help="render only the text layer, to check the words")
    add_copy_args(card)
    card.add_argument("--out", required=True, type=Path, help="where to write the PNG")
    card.set_defaults(handler=cmd_card, parser=card)

    cost = video_sub.add_parser("cost", help="what Higgsfield charges for one generated clip")
    add_copy_args(cost)
    cost.add_argument("--duration", type=int, default=8, help="seconds of generated footage")
    cost.add_argument("--resolution", default="720p", choices=RESOLUTIONS)
    cost.add_argument("--voiced", action="store_true", help="price a clip that speaks")
    cost.set_defaults(handler=cmd_cost, parser=cost)

    script = video_sub.add_parser("script", help="write the on-air read without rendering")
    add_copy_args(script)
    add_script_args(script)
    script.set_defaults(handler=cmd_script, parser=script)

    rend = video_sub.add_parser("render", help="render a trade announcement video")
    add_copy_args(rend)
    rend.add_argument(
        "--base",
        default="source",
        help="source (the ESPN clip), generated (Seedance 2.5, costs credits), or footage path",
    )
    rend.add_argument(
        "--duration",
        type=float,
        default=REFERENCE_DURATION,
        help="seconds; the default matches the reference",
    )
    rend.add_argument(
        "--keep-voice", action="store_true", help="keep the footage's own audio under the music"
    )
    rend.add_argument(
        "--music-gain",
        type=float,
        default=None,
        help="music level in dB; 0 like the reference, -12 under a voiced read",
    )
    rend.add_argument("--resolution", default="720p", choices=RESOLUTIONS)
    rend.add_argument(
        "--voiced",
        action="store_true",
        help="generate footage that speaks a breaking-news read (implies --base generated)",
    )
    add_script_args(rend)
    rend.add_argument(
        "--dry-run",
        action="store_true",
        help="print the ffmpeg command; encode and generate nothing",
    )
    rend.set_defaults(handler=cmd_render, parser=rend)

    jobs = video_sub.add_parser("jobs", help="the queue of requested trade videos")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    listing = jobs_sub.add_parser("list", help="the most recent jobs")
    listing.add_argument("--limit", type=int, default=10)
    listing.set_defaults(handler=cmd_jobs_list)
    run_one = jobs_sub.add_parser("run", help="render the next queued video and deliver it")
    run_one.add_argument("--seconds", type=int, default=12, help="length of the voiced clip")
    run_one.add_argument(
        "--verbose", action="store_true", help="say so when there is nothing to do"
    )
    run_one.set_defaults(handler=cmd_jobs_run)
    watch = jobs_sub.add_parser("watch", help="keep rendering queued videos until stopped")
    watch.add_argument("--seconds", type=int, default=12)
    watch.add_argument("--interval", type=int, default=30, help="seconds between looks")
    watch.set_defaults(handler=cmd_jobs_watch)
    add = jobs_sub.add_parser("add", help="queue a video for a trade code by hand")
    add.add_argument("trade_code")
    add.set_defaults(handler=cmd_jobs_add)


def add_script_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--script", metavar="TEXT", help="the read, verbatim, instead of writing one"
    )
    parser.add_argument(
        "--no-ai", action="store_true", help="use the template read instead of the model"
    )
    parser.add_argument(
        "--generate-seconds", type=int, default=8, help="length of the generated clip"
    )


def add_copy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--trade", metavar="TRADE_CODE", help="a logged trade to announce")
    parser.add_argument("--headline", help="lower-third headline, instead of a logged trade")
    parser.add_argument("--subline", help="lower-third subline, instead of a logged trade")
    parser.add_argument("--caption", help="the centred caption; default is the pov: line")
    parser.add_argument("--aspect", choices=tuple(CANVAS), default="9:16")


def resolve_copy(args: argparse.Namespace) -> TradeCopy:
    """The words, from a logged trade or from the flags."""
    if args.trade:
        deps = build_deps()
        trade = TradeRepository(deps.conn).find_by_code(args.trade)
        if trade is None:
            raise SystemExit(f"no trade {args.trade} on file")
        labels = party_labels(MemberAliasRepository(deps.conn).all_members())
        return trade_copy(TradeProposal(**trade["terms"]), labels, caption=args.caption)
    if not (args.headline and args.subline):
        args.parser.error("give --trade or both --headline and --subline")
    return TradeCopy(
        caption=args.caption or default_caption([]),
        headline=args.headline,
        subline=args.subline,
    )


def generate_request(copy: TradeCopy, args: argparse.Namespace) -> hf.GenerateRequest:
    voiced = getattr(args, "voiced", False)
    if voiced:
        prompt = voiced_prompt(copy, template_script(copy, args.duration), args.duration)
    else:
        prompt = footage_prompt(copy, args.duration)
    return hf.GenerateRequest(
        prompt=prompt,
        reference_video=load_assets().reference_video,
        duration=args.duration,
        resolution=args.resolution,
        aspect_ratio=args.aspect,
        generate_audio=voiced,
    )


def build_script_ai() -> StructuredOutputClient:
    """The model that writes the read: Hermes on the league profile, no database."""
    if find_hermes_binary() is None:
        raise SystemExit("hermes CLI not found; pass --no-ai for the template read")
    settings = load_settings()
    return HermesStructuredClient(settings.hermes_profile_home, model=settings.hermes_model)


def resolve_script(copy: TradeCopy, args: argparse.Namespace) -> Script:
    """The read: typed by Ben, the template, or written by the model."""
    seconds = args.generate_seconds
    if args.script:
        return script_from_text(args.script, seconds)
    if args.no_ai:
        return template_script(copy, seconds)
    return generate_script(build_script_ai(), copy, seconds)


def cmd_assets(args: argparse.Namespace) -> int:
    assets = load_assets()
    missing = assets.missing()
    ok = True
    for path in (assets.reference_video, assets.source_video, assets.music):
        state = "MISSING" if path in missing else "ok"
        print(f"{state:8}{path}")
    for name in TOOLS:
        try:
            print(f"{'ok':8}{name}  {find_tool(name)}")
        except ToolMissing as exc:
            ok = False
            print(f"{'MISSING':8}{name}  {exc}")
    if missing:
        print(f"{len(missing)} reference file(s) missing; see data/media/reference/README.md")
    return 0 if ok and not missing else 1


def cmd_card(args: argparse.Namespace) -> int:
    copy = resolve_copy(args)
    layout = Layout.for_footage(*SOURCE_FRAME, args.aspect)
    print(render_card(copy, layout, args.out))
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    req = generate_request(resolve_copy(args), args)
    credits = hf.parse_credits(hf.run(hf.cost_command(req, find_tool("higgsfield"))))
    print(f"{credits} credits for one {req.duration} s {req.resolution} {req.aspect_ratio} clip")
    return 0


def cmd_script(args: argparse.Namespace) -> int:
    copy = resolve_copy(args)
    print(format_script(resolve_script(copy, args), args.generate_seconds))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    copy = resolve_copy(args)
    base = "generated" if args.voiced else args.base
    if args.music_gain is not None:
        music_gain = args.music_gain
    else:
        music_gain = VOICED_MUSIC_GAIN_DB if args.voiced else 0.0
    script = resolve_script(copy, args) if args.voiced else None
    if script is not None:
        print(format_script(script, args.generate_seconds))
    req = RenderRequest(
        copy=copy,
        base=base,
        aspect=args.aspect,
        duration=args.duration,
        keep_voice=args.keep_voice,
        music_gain_db=music_gain,
        name=args.trade or "manual",
        generate_seconds=args.generate_seconds,
        resolution=args.resolution,
        voiced=args.voiced,
        script=script,
    )
    if args.dry_run and req.base == "generated":
        args.parser.error("--dry-run cannot generate footage; use --base source or a path")
    try:
        ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
        if args.dry_run:
            job = prepare(req, load_assets(), ffmpeg=ffmpeg, ffprobe=ffprobe)
            print(" ".join(shlex.quote(part) for part in job.command))
            return 0
        job = render(req, load_assets(), ffmpeg=ffmpeg, ffprobe=ffprobe, report=print)
    except (RenderError, ToolMissing, hf.HiggsfieldError) as exc:
        print(f"ug video render: {exc}", file=sys.stderr)
        return 1
    print(job.composite.output)
    return 0


SCHEDULED_AGENT = "video-jobs"


def build_worker(args: argparse.Namespace, deps=None) -> Worker:
    deps = deps or build_deps()
    return Worker(
        conn=deps.conn,
        jobs=VideoJobRepository(deps.conn),
        trades=TradeRepository(deps.conn),
        members=MemberAliasRepository(deps.conn),
        runs=RunRepository(deps.conn),
        delivery=build_delivery(deps),
        notify=deps.notifier.ops,
        assets=load_assets(),
        script_ai=build_script_ai,
        ffmpeg=find_tool("ffmpeg"),
        ffprobe=find_tool("ffprobe"),
        seconds=args.seconds,
    )


def cmd_jobs_list(args: argparse.Namespace) -> int:
    deps = build_deps()
    jobs = VideoJobRepository(deps.conn).list_recent(args.limit)
    if not jobs:
        print("no video jobs")
        return 0
    print("id  status  trade  attempts  created  finished  output/error")
    for job in jobs:
        tail = job.output_path or job.error or ""
        finished = job.finished_at.strftime("%m-%d %H:%M") if job.finished_at else "-"
        print(
            f"{job.id}  {job.status}  {job.trade_code}  {job.attempts}  "
            f"{job.created_at.strftime('%m-%d %H:%M')}  {finished}  {tail}"
        )
    return 0


def cmd_jobs_run(args: argparse.Namespace) -> int:
    """One pass, quiet when idle: under cron, empty output means nothing to report.

    The pass is recorded as a scheduled run of ``video-jobs`` so `ug ops audit-runs`
    can tell a quiet queue from a worker that stopped firing.
    """
    deps = build_deps()
    try:
        worker = build_worker(args, deps)
    except ToolMissing as exc:
        print(f"ug video jobs run: {exc}", file=sys.stderr)
        return 1

    def action(_run_id: int) -> int:
        outcome = worker.run_once()
        if outcome.status != "idle" or args.verbose:
            print(outcome)
        return 1 if outcome.status == "failed" else 0

    exit_code = run_scheduled(deps.conn, SCHEDULED_AGENT, datetime.now(UTC), action)
    return 0 if exit_code is None else exit_code


def cmd_jobs_watch(args: argparse.Namespace) -> int:
    import time

    try:
        worker = build_worker(args)
    except ToolMissing as exc:
        print(f"ug video jobs watch: {exc}", file=sys.stderr)
        return 1
    try:
        while True:
            outcome = worker.run_once()
            if outcome.status != "idle":
                print(outcome, flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def cmd_jobs_add(args: argparse.Namespace) -> int:
    deps = build_deps()
    trade = TradeRepository(deps.conn).find_by_code(args.trade_code)
    if trade is None:
        print(f"no trade {args.trade_code} on file")
        return 1
    job_id, created = VideoJobRepository(deps.conn).enqueue(
        trade["trade_id"], trade["trade_code"], None
    )
    deps.conn.commit()
    print(f"job {job_id} {'queued' if created else 'already open'} for {trade['trade_code']}")
    return 0
