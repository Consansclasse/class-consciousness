#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
msg_file="${1:-}"
if [ -n "$msg_file" ] && [ -f "$msg_file" ]; then
  msg="$(cat "$msg_file")"
else
  msg="$(git log -1 --pretty=%B)"
fi
if ! grep -qE "^Signed-off-by: " <<<"$msg"; then
  echo "Missing Signed-off-by (DCO). Use 'git commit -s'." >&2
  exit 1
fi
