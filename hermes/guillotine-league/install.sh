#!/bin/bash
# Install only this profile; never create or modify the global ops profile.
set -euo pipefail
umask 077
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export HERMES_HOME="${HERMES_LEAGUE_PROFILE_HOME:-$HOME/.hermes/profiles/guillotine-league}"
cd "$REPO"
exec uv run --project packages/league-automation python \
  "$REPO/hermes/guillotine-league/install_profile.py"
