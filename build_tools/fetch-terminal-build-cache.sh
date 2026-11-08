#!/usr/bin/env bash
set -euo pipefail

path=$1
pin=zmala_images/terminal-build-cache.json
draft=$(jq -er .draft_id "$pin")
asset=$(jq -er .asset_id "$pin")
digest=$(jq -er .sha256 "$pin")
[[ $draft =~ ^[1-9][0-9]*$ && $asset =~ ^[1-9][0-9]*$ && $digest =~ ^[a-f0-9]{64}$ ]]
api="repos/$GITHUB_REPOSITORY/releases/$draft"
[[ $(gh api "$api" --jq .draft) == true ]]
name=ZmalaTerminal-Package-Cache.tar
[[ $(gh api "$api" --jq ".assets[] | select(.name == \"$name\" and .state == \"uploaded\") | .id") == "$asset" ]]
gh api "repos/$GITHUB_REPOSITORY/releases/assets/$asset" -H 'Accept: application/octet-stream' > "$path"
printf '%s  %s\n' "$digest" "$path" | sha256sum --check --strict
