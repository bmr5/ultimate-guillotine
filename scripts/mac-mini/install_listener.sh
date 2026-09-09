#!/bin/bash
# Idempotent: renders the launchd plist, lints it, and (re)installs the agent.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.ultimateguillotine.listener
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/Logs/UltimateGuillotine" "$HOME/Library/LaunchAgents"
# Escape the characters sed treats specially in a replacement (\, &, and the #
# delimiter) so a path containing any of them substitutes literally.
REPO_SED=$(printf '%s\n' "$REPO" | sed -e 's/[\\&#]/\\&/g')
HOME_SED=$(printf '%s\n' "$HOME" | sed -e 's/[\\&#]/\\&/g')
sed -e "s#__REPO__#$REPO_SED#g" -e "s#__HOME__#$HOME_SED#g" "$REPO/scripts/mac-mini/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "listener installed; check $HOME/Library/Logs/UltimateGuillotine/listener.err.log"
