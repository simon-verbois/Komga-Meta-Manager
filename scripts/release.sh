#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <version> (example: $0 2026.32.1)" >&2
  exit 1
fi

version="$1"
if [[ ! "$version" =~ ^[0-9]{4}\.([1-9]|[1-4][0-9]|5[0-3])\.[1-9][0-9]*$ ]]; then
  echo "Invalid version: '$1' (expected YYYY.WEEK.ID, for example 2026.32.1)" >&2
  exit 1
fi

tag="$version"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git symbolic-ref --quiet --short HEAD)" || {
  echo "Cannot create a release from a detached HEAD." >&2
  exit 1
}

git remote get-url origin >/dev/null

if git rev-parse --quiet --verify "refs/tags/${tag}" >/dev/null; then
  echo "Tag ${tag} already exists locally." >&2
  exit 1
fi

printf '%s\n' "$version" > VERSION

git add -A
git commit -m "Release ${tag}"
git tag -a "$tag" -m "Release ${tag}"
git push --atomic origin "HEAD:refs/heads/${branch}" "refs/tags/${tag}"

echo "Release ${tag} pushed to origin from branch ${branch}."
