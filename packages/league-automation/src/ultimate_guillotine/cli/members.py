"""`ug members` subcommands: list, aliases load.

Nicknames are the one piece of league knowledge the model cannot infer, and
they are also personal: the alias file is git-ignored and nothing here prints an
alias back out -- except the nickname, the first alias, which the league already
publishes on the board as each owner's label. Every other alias stays in
``private.member_aliases``, and the loader reports counts only, so a run of it
can be pasted into ops without leaking who else is called what.
"""

import argparse
import json
import sys
from pathlib import Path

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.data.repositories import MemberAliasRepository


def register(subparsers) -> None:
    parser = subparsers.add_parser("members", help="league member and alias commands")
    members_sub = parser.add_subparsers(dest="command", required=True)

    listing = members_sub.add_parser("list", help="show each member and how many aliases they have")
    listing.set_defaults(handler=cmd_list)

    aliases = members_sub.add_parser("aliases", help="manage member nicknames")
    aliases_sub = aliases.add_subparsers(dest="subcommand", required=True)
    load = aliases_sub.add_parser("load", help="replace every member's aliases from a JSON file")
    load.add_argument("path")
    load.set_defaults(handler=cmd_aliases_load)


def cmd_list(args: argparse.Namespace) -> int:
    deps = build_deps()
    for member in MemberAliasRepository(deps.conn).all_members():
        print(f"{member.display_name}  {len(member.aliases)}  {member.nickname or '-'}")
    return 0


def cmd_aliases_load(args: argparse.Namespace) -> int:
    """Replace every listed member's aliases, wholesale.

    Members in ``public.members`` are keyed by their Sleeper username, which is
    what the file's ``sleeper_username`` matches. An entry naming somebody who
    is not in the league is reported on stderr and skipped rather than failing
    the load: a typo in one row should not block the other fifteen.

    Every entry being skipped is a different thing -- the file is for another
    league, or the members table has not been synced -- and nothing was loaded,
    so that exits 1.
    """
    deps = build_deps()
    repo = MemberAliasRepository(deps.conn)
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    members = 0
    aliases = 0
    skipped = 0
    # Only the members the file names are touched. Anyone absent keeps the
    # aliases and the nickname they already have, by design: the file is the
    # whole roster's alias list, so a full reload lists everyone, and a partial
    # file is a deliberate edit to those members rather than a league-wide wipe.
    for entry in document.get("members", []):
        username = entry.get("sleeper_username", "")
        try:
            aliases += repo.replace_aliases(username, entry.get("aliases", []))
        except ValueError as exc:
            # An alias claimed by two members is a real conflict and must stop
            # the load; a name that is not in the league is just a stale row.
            if not str(exc).startswith("unknown member"):
                raise
            print(f"unknown member: {username}", file=sys.stderr)
            skipped += 1
            continue
        members += 1
    deps.conn.commit()
    print(f"aliases: {members} members, {aliases} aliases")
    if skipped:
        print(f"skipped: {skipped}")
    return 1 if skipped and members == 0 else 0
