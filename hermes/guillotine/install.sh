#!/bin/bash
# Idempotent: creates the guillotine Hermes profile, syncs SOUL/skills/scripts, registers cron jobs.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE=guillotine
export HERMES_HOME="$HOME/.hermes/profiles/$PROFILE"

if [ ! -d "$HERMES_HOME" ]; then
  hermes profile create "$PROFILE" --no-skills --description "Ultimate Guillotine league operations: runs league CLIs, reports status to Ben in Discord"
fi
mkdir -p "$HERMES_HOME/skills/guillotine-ops" "$HERMES_HOME/scripts"
cp "$REPO/hermes/guillotine/SOUL.md" "$HERMES_HOME/SOUL.md"
cp "$REPO/hermes/guillotine/skills/guillotine-ops/SKILL.md" "$HERMES_HOME/skills/guillotine-ops/SKILL.md"
REPO_SED=$(printf '%s\n' "$REPO" | sed -e 's/[\\&#]/\\&/g')
for template in "$REPO"/hermes/guillotine/scripts/*.sh.template; do
  target="$HERMES_HOME/scripts/$(basename "${template%.template}")"
  sed "s#__REPO__#$REPO_SED#g" "$template" > "$target"
  chmod 755 "$target"
done
cd "$REPO"
uv run --project packages/league-automation python hermes/guillotine/register_cron.py hermes/guillotine/cron.yaml
uv run --project packages/league-automation ug ops sync-expected-runs hermes/guillotine/cron.yaml
echo "Profile $PROFILE installed. Next: paste DISCORD_BOT_TOKEN into $HERMES_HOME/.env, then run: HERMES_HOME=$HERMES_HOME hermes gateway install"
