#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(git -C "$script_dir/.." rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Not inside a Git repository." >&2
  exit 1
}
cd "$repo_root"

if (( $# != 0 )); then
  echo "Usage: scripts/release.sh (no arguments; version is calculated automatically)." >&2
  exit 1
fi

branch="$(git symbolic-ref --quiet --short HEAD)" || {
  echo "Cannot create a release from a detached HEAD." >&2
  exit 1
}
if [[ "$branch" != "main" ]]; then
  echo "Releases must be created from main, not ${branch}." >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet ||
   [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  echo "Commit or remove working-tree changes before creating a release." >&2
  exit 1
fi

git remote get-url origin >/dev/null 2>&1 || {
  echo "Git remote 'origin' does not exist." >&2
  exit 1
}

changelog="CHANGELOG.md"
unreleased_heading='## [Unreleased]'
if [[ ! -f VERSION ]] || ! grep -qxF "$unreleased_heading" "$changelog" 2>/dev/null; then
  echo "VERSION and a '${unreleased_heading}' section in ${changelog} are required." >&2
  exit 1
fi
unreleased_items="$(awk -v heading="$unreleased_heading" '
  $0 == heading { inside = 1; next }
  inside && /^## \[/ { exit }
  inside && /^- [^[:space:]]/ { count++ }
  END { print count + 0 }
' "$changelog")"
if (( unreleased_items == 0 )); then
  echo "Nothing under '${unreleased_heading}' in ${changelog}: describe the release before shipping it." >&2
  exit 1
fi

year="$(date +%G)"
week_raw="$(date +%V)"
if [[ ! "$year" =~ ^[0-9]{4}$ ]] ||
   [[ ! "$week_raw" =~ ^(0[1-9]|[1-4][0-9]|5[0-3])$ ]]; then
  echo "Unable to determine the current ISO year and week." >&2
  exit 1
fi
week="$((10#$week_raw))"
local_tags="$(git tag --list)"
remote_tags="$(git ls-remote --tags --refs origin | awk '{ sub(/^refs\/tags\//, "", $2); print $2 }')"
max_id=0
while IFS= read -r existing_tag; do
  if [[ "$existing_tag" =~ ^${year}\.${week}\.([1-9][0-9]*)$ ]]; then
    current_id="$((10#${BASH_REMATCH[1]}))"
    if (( current_id > max_id )); then
      max_id="$current_id"
    fi
  fi
done < <(printf '%s\n%s\n%s\n' "$local_tags" "$remote_tags" "$(cat VERSION)" | sort -u)
tag="${year}.${week}.$((max_id + 1))"

echo "Creating release ${tag} from branch ${branch} (${unreleased_items} changelog entries)."
release_date="$(date +%F)"
changelog_tmp="$(mktemp "$repo_root/.changelog.XXXXXX")"
trap 'rm -f -- "$changelog_tmp"' EXIT
awk -v heading="$unreleased_heading" -v release="## [${tag}] — ${release_date}" '
  $0 == heading && !done { print heading; print ""; print release; done = 1; next }
  { print }
' "$changelog" > "$changelog_tmp"
cat "$changelog_tmp" > "$changelog"
printf '%s\n' "$tag" > VERSION
rm -f -- "$changelog_tmp"

git add -- VERSION CHANGELOG.md
git commit -m "Release ${tag}"
git tag -a "$tag" -m "Release ${tag}"
git push --atomic origin "HEAD:refs/heads/${branch}" "refs/tags/${tag}"
echo "Release ${tag} pushed to origin from branch ${branch}."
