"""`ug members` subcommands: list, aliases load, handles load.

Nicknames are the one piece of league knowledge the model cannot infer, and
they are also personal: the alias file is git-ignored and nothing here prints an
alias back out -- except the nickname, the first alias, which the league already
publishes on the board as each owner's label. Every other alias stays in
``private.member_aliases``, and the loader reports counts only, so a run of it
can be pasted into ops without leaking who else is called what.

Handles are stricter still. `handles load` hashes each Apple handle on the way
in and stores nothing else, so `private.member_contacts` never holds an address
even in a column nobody reads. Usernames appear in this module's output;
handles, hashed or not, never do.
"""

import argparse
import json
import sys
from pathlib import Path

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.data.repositories import (
    MemberAliasRepository,
    MemberContactRepository,
    handle_hash,
    normalize_handle,
)


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

    handles = members_sub.add_parser("handles", help="manage hashed member handles")
    handles_sub = handles.add_subparsers(dest="subcommand", required=True)
    handles_load = handles_sub.add_parser(
        "load", help="replace every member's hashed handles from a JSON file"
    )
    handles_load.add_argument("path")
    handles_load.set_defaults(handler=cmd_handles_load)


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


def cmd_handles_load(args: argparse.Namespace) -> int:
    """Hash every handle in the file and replace each member's contact rows.

    The file (`data/private/member-handles.json`, git-ignored) looks like
    `{"members": [{"sleeper_username": "...", "handles": ["+15555550100"]}]}`.
    Handles are hashed here and thrown away; nothing is printed but counts, so a
    run of this can be pasted into ops.

    An entry naming somebody who is not in the league is reported on stderr and
    skipped, matching `aliases load`: a typo in one row should not block the
    rest. Every entry being skipped means nothing was loaded, so that exits 1.

    A handle that is blank once normalized is not a handle, and an entry left
    with none of them is skipped as an unfinished row rather than loaded.

    The whole file lands in one transaction. A conflicting handle aborts the
    load part-way through, and a database holding the first half of an edited
    handle file is worse than one still holding yesterday's: the commissioner
    fixes the file and runs it again, from a known state.
    """
    deps = build_deps()
    repo = MemberContactRepository(deps.conn)
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    members = 0
    handles = 0
    skipped = 0
    with deps.conn.transaction():
        for entry in document.get("members", []):
            username = entry.get("sleeper_username", "")
            # Filtered on the *normalized* handle, because that is what would
            # be hashed: `" "` is truthy and normalizes to nothing, and hashing
            # it would store the digest of the empty string as a contact row --
            # a row every future blank handle in the file would then collide
            # with, reported as a member claiming another member's handle.
            digests = [
                handle_hash(h)
                for h in entry.get("handles") or []
                if h and normalize_handle(h)
            ]
            if not digests:
                # `replace_handles` is wholesale, so an empty list would wipe
                # this member's handles. A row with no handles is an unfinished
                # file, not an instruction to unmap somebody.
                print(f"no handles: {username}", file=sys.stderr)
                skipped += 1
                continue
            try:
                handles += repo.replace_handles(username, digests)
            except ValueError as exc:
                # A handle claimed by two members is a real conflict and must
                # stop the load; a name that is not in the league is just a
                # stale row.
                if not str(exc).startswith("unknown member"):
                    raise
                print(f"unknown member: {username}", file=sys.stderr)
                skipped += 1
                continue
            members += 1
    deps.conn.commit()
    print(f"handles: {members} members, {handles} handles")
    if skipped:
        print(f"skipped: {skipped}")
    return 1 if skipped and members == 0 else 0
