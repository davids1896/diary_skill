#!/usr/bin/env bash
set -euo pipefail

TARGET_DATE="${1:-}"
python3 -c 'import datetime, sys
d = datetime.date.fromisoformat(sys.argv[1])
assert d.isoformat() == sys.argv[1]' "$TARGET_DATE" || {
  echo "usage: $0 YYYY-MM-DD" >&2
  exit 2
}
REPO="${DIARY_REPO:?Set DIARY_REPO to the diary repository}"
REPO="$(cd "$REPO" && pwd -P)"
GENERATOR="$(cd "$(dirname "$0")" && pwd -P)/generate_diary_pdf.py"
REMOTE="${DIARY_REMOTE:-origin}"
BRANCH="${DIARY_BRANCH:-main}"
PUBLISH="${DIARY_PUBLISH:-0}"
[[ "$PUBLISH" == 0 || "$PUBLISH" == 1 ]] || {
  echo "DIARY_PUBLISH must be 0 or 1" >&2
  exit 2
}
REL="${TARGET_DATE:0:4}/${TARGET_DATE:5:2}/$TARGET_DATE"
MARKDOWN="$REPO/$REL.md"
PDF="$REPO/$REL.pdf"
[[ -s "$MARKDOWN" ]] || { echo "Missing Markdown: $MARKDOWN" >&2; exit 3; }

# Lock the same repository across concurrent scheduled/manual publishers.
lock_key="$(printf '%s' "$REPO" | sha256sum | cut -d' ' -f1)"
exec 9>"${TMPDIR:-/tmp}/diary-publish-$lock_key.lock"
flock -n 9 || { echo "Another diary publisher is running" >&2; exit 4; }

unchanged=false
if [[ "$PUBLISH" == 1 ]]; then
  [[ "$(git -C "$REPO" rev-parse --show-toplevel)" == "$REPO" ]] || {
    echo "DIARY_REPO must be the Git root, not its parent workspace" >&2
    exit 5
  }
  [[ "$(git -C "$REPO" branch --show-current)" == "$BRANCH" ]] || {
    echo "Checkout the configured diary branch first" >&2
    exit 5
  }
  git -C "$REPO" check-ref-format --branch "$BRANCH" >/dev/null
  [[ "$REMOTE" != -* ]] || { echo "Invalid remote" >&2; exit 5; }
  git -C "$REPO" remote get-url "$REMOTE" >/dev/null
  remote_commit="$(git -C "$REPO" ls-remote --exit-code "$REMOTE" "refs/heads/$BRANCH" | cut -f1)"
  [[ "$(git -C "$REPO" rev-parse HEAD)" == "$remote_commit" ]] || {
    echo "Local HEAD differs from remote; inspect pending commits before publishing" >&2
    exit 5
  }
  if [[ -s "$PDF" ]] \
    && git -C "$REPO" ls-files --error-unmatch "$REL.md" "$REL.pdf" >/dev/null 2>&1 \
    && git -C "$REPO" diff --quiet HEAD -- "$REL.md" "$REL.pdf"; then
    unchanged=true
  fi
fi

if [[ "$unchanged" == true ]]; then
  python3 "$GENERATOR" "$MARKDOWN" --verify-only >/dev/null
else
  python3 "$GENERATOR" "$MARKDOWN" >/dev/null
fi

status=validated
commit=""
changed=false
if [[ "$PUBLISH" == 1 ]]; then
  if [[ "$unchanged" != true ]]; then
    git -C "$REPO" add -- "$REL.md" "$REL.pdf"
    git -C "$REPO" diff --cached --check -- "$REL.md" "$REL.pdf"
    if ! git -C "$REPO" diff --cached --quiet -- "$REL.md" "$REL.pdf"; then
      git -C "$REPO" commit --only -m "Diary: $TARGET_DATE" -- "$REL.md" "$REL.pdf" >/dev/null
      changed=true
    fi
    git -C "$REPO" push "$REMOTE" "HEAD:refs/heads/$BRANCH" >/dev/null
  fi
  commit="$(git -C "$REPO" rev-parse HEAD)"
  verified="$(git -C "$REPO" ls-remote --exit-code "$REMOTE" "refs/heads/$BRANCH" | cut -f1)"
  [[ "$verified" == "$commit" ]] || { echo "Remote verification failed" >&2; exit 6; }
  status=published
fi
python3 -c 'import json, sys
print(json.dumps(dict(status=sys.argv[1], date=sys.argv[2], markdown=sys.argv[3],
                     pdf=sys.argv[4], commit=sys.argv[5], changed=sys.argv[6] == "true")))' \
  "$status" "$TARGET_DATE" "$MARKDOWN" "$PDF" "$commit" "$changed"
