#!/usr/bin/env bash
# Publish RedGreen and open the plugin-catalog PR.
# Run only after the owner has approved publication.
set -euo pipefail

REPO_DIR="/Users/efi/Hackathons/hermes-redgreen"
CATALOG_ENTRY="/tmp/catalog-redgreen.yaml"
PR_BODY="/Users/efi/Hackathons/hermes-redgreen/submission/CATALOG_PR.md"
BRANCH="add-redgreen"
FORK="shahaman098/hermes-agent"
UPSTREAM="NousResearch/hermes-agent"

cd "$REPO_DIR"

echo "== 1. create/push the public repo =="
if gh repo view shahaman098/hermes-redgreen >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/shahaman098/hermes-redgreen.git
  git push -u origin HEAD:main
else
  gh repo create shahaman098/hermes-redgreen --public --source=. --remote=origin --push \
    --description "A test only proves a fix when it fails without the fix. Hermes plugin."
fi

echo "== 2. fork the catalog repo =="
gh repo fork "$UPSTREAM" --clone=false --remote=false >/dev/null 2>&1 || true
MAIN_SHA=$(gh api "repos/$UPSTREAM/git/ref/heads/main" --jq .object.sha)
echo "upstream main: $MAIN_SHA"

echo "== 3. create the branch =="
gh api -X POST "repos/$FORK/git/refs" \
  -f ref="refs/heads/$BRANCH" -f sha="$MAIN_SHA" >/dev/null 2>&1 || true

echo "== 4. add plugin-catalog/redgreen.yaml =="
CONTENT=$(base64 < "$CATALOG_ENTRY" | tr -d '\n')
gh api -X PUT "repos/$FORK/contents/plugin-catalog/redgreen.yaml" \
  -f message="feat(plugin-catalog): add redgreen" \
  -f content="$CONTENT" \
  -f branch="$BRANCH" >/dev/null

echo "== 5. open the PR =="
gh pr create --repo "$UPSTREAM" \
  --head "shahaman098:$BRANCH" \
  --title "feat(plugin-catalog): add redgreen" \
  --body-file "$PR_BODY" || true

echo "== done =="
gh pr list --repo "$UPSTREAM" --head "shahaman098:$BRANCH" --json url,title --jq '.[] | "\(.title) \(.url)"'
