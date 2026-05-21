#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Lock down the public GitHub repo for solo-maintainer phase :
#   - branch protection on main (no force-push, no deletion, linear history,
#     CI must be green, conversation resolution required)
#   - Dependabot security alerts + automated fixes
#   - Secret scanning + push protection
#
# Usage :
#   GITHUB_TOKEN=<fine-grained-PAT> ./ops/scripts/lock-down-repo.sh
#
# Token scopes requis (fine-grained, scope = ce repo uniquement) :
#   - Administration : Read & Write
#   - Contents       : Read
#   - Metadata       : Read
#
# Le flag `--with-signed-commits` ajoute l'exigence de signature GPG/SSH.
# À n'activer qu'après avoir configuré une clé de signature (cf. README ops).

set -euo pipefail

OWNER="${OWNER:-Consansclasse}"
REPO="${REPO:-class-consciousness}"
BRANCH="${BRANCH:-main}"
WITH_SIGNED_COMMITS="false"
[[ "${1:-}" == "--with-signed-commits" ]] && WITH_SIGNED_COMMITS="true"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERREUR : GITHUB_TOKEN absent. Crée un fine-grained PAT et exporte-le." >&2
  exit 1
fi

api() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -fsS -X "$method" \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $GITHUB_TOKEN" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com$path" \
      -d "$body"
  else
    curl -fsS -X "$method" \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $GITHUB_TOKEN" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com$path"
  fi
}

# required_status_checks : objet (CI requise) pour le repo de code ; passer
# REQUIRED_STATUS_CHECKS=null pour un repo sans CI (ex. class-consciousness-corpus,
# qui ne contient que des fichiers TEI). La protection anti-force-push et
# anti-suppression reste appliquée dans les deux cas.
if [[ -n "${REQUIRED_STATUS_CHECKS:-}" ]]; then
  status_checks="$REQUIRED_STATUS_CHECKS"
else
  status_checks='{"strict": true, "contexts": ["python", "node", "security", "docker-build", "dco"]}'
fi

echo "→ Branch protection sur $OWNER/$REPO@$BRANCH"
api PUT "/repos/$OWNER/$REPO/branches/$BRANCH/protection" "$(cat <<JSON
{
  "required_status_checks": $status_checks,
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_signatures": $WITH_SIGNED_COMMITS,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
JSON
)" >/dev/null
echo "  ✓ protection appliquée (signed_commits=$WITH_SIGNED_COMMITS)"

echo "→ Dependabot vulnerability alerts"
api PUT "/repos/$OWNER/$REPO/vulnerability-alerts" >/dev/null
echo "  ✓ alertes activées"

echo "→ Dependabot automated security fixes"
api PUT "/repos/$OWNER/$REPO/automated-security-fixes" >/dev/null
echo "  ✓ fixes auto activés"

echo "→ Secret scanning + push protection"
api PATCH "/repos/$OWNER/$REPO" "$(cat <<'JSON'
{
  "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" }
  },
  "allow_merge_commit": false,
  "allow_squash_merge": true,
  "allow_rebase_merge": true,
  "delete_branch_on_merge": true,
  "has_wiki": false,
  "has_projects": false,
  "has_discussions": true
}
JSON
)" >/dev/null
echo "  ✓ secret scanning + push protection actifs ; wiki off ; squash + rebase ; delete-on-merge"

echo
echo "Lockdown terminé. Vérifications recommandées dans l'UI :"
echo "  - Settings → Branches → vérifier la règle sur $BRANCH"
echo "  - Settings → Code security and analysis → tout vert"
echo "  - Si --with-signed-commits a été utilisé, tester un git commit -S"
