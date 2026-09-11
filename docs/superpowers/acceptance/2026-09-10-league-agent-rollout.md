# League Agent two-chat rollout

## Current state

Activated on 2026-09-10 in both registered test and league chats, as Ben authorized.
Main was fast-forwarded to reviewed integration commit `f727a21`. The listener was
stopped while the checkout and profile were updated, then started through launchd.
The new process reported running and `/healthz` returned `{"ok":true}`.

## Verified before activation

- Completed main changes committed as `ad3466e`; League Agent changes committed as `3ea1688`.
- Both registered delivery targets match configuration. The league target's current
  participants match the production fingerprint. No messages were sent by this check.
- Two-chat routing uses one worker. Test and production follow-ups remain isolated,
  including replies to acknowledgements before the original answer is complete.
- Explicit video requests are owned by the existing registered video handler, not
  also answered by the League Agent. Combined regressions cover both chats and
  video requests replying to Agent receipts.
- The exact immediate receipt is `Got it, kitten. Daddy's on it.`
- Rental guidance compares short-term costs with buying, holding and waivers, and
  includes return terms, elimination risk and FAAB preservation.
- Only `20260910180000_league_agent.sql` was applied to the hosted database, with
  its migration-history row in the same transaction. Unrelated migrations were not run.
- Actual worker-role session, run and answer writes/reads passed inside a rolled-back
  transaction. Chat-scoped outbound lookups passed for sending and sent records in
  both directions. Probe rows were rolled back; anonymous/authenticated access remains denied.
- The existing authenticated isolated profile retains its credentials in place. Its
  default model is `gpt-6-astra`; the effective tools are web and eleven read-only league tools.
- A real fixture question using the profile's default model returned the correct
  960 FAAB answer and reported Astra. It sent no chat messages.
- Combined integration tests passed: 1,495 backend tests, 194 gated skips, one known
  dependency warning; 965 web tests across 66 files. Ruff and whitespace checks passed.

## Runtime paths

The listener runs from `/Users/benray/Documents/ultimate-guillotine`.
The ignored main `.env` selects the authenticated profile at
`/Users/benray/Documents/ultimate-guillotine/.claude/worktrees/league-agent/.superpowers/sdd/2026-09-10-league-agent/hermes-live-profile`.
Keep the existing worktree and its ignored evidence. Removing it would remove the
configured profile and its authentication. The ops profile is unchanged.

## Remaining evidence

Final integration review approved the merge and video-dispatch fix. A read-only
registry check using real target rows confirmed question/video routing in both chats
and one shared worker. The profile was reinstalled from main, preserving its existing
authentication. The real MCP audit again verified web plus all eleven league tools;
the installed launcher points to the live main checkout and the profile uses Astra.

An installed-main dry run asked `@daddy how many two time champions are there` as
Ben R. It returned `succeeded` and `answer`, model `gpt-6-astra`, session
`20260910_190323_357954`. The answer identified Michael, Nick Nifty and Ben R when
the shared 2022 title is counted, or two champions with two outright titles.
No model override or test adapter was used. This was a dry run, not a Messages send.

Actual Messages delivery after activation and an iPhone HTML rendering check are
not yet verified by this rollout record. Send a fresh tagged question to exercise
the listener; the earlier ignored question already has a webhook receipt and was
not replayed or deleted during deployment.
The earlier five-question acceptance remains partial for the reasons recorded in
[the acceptance report](2026-09-10-league-agent.md). Prompt changes and deployment do
not retroactively turn those unrun checks into passes. No push was performed, and
the original worktree and ignored evidence remain intact.
