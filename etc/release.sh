#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PATH="$ROOT_DIR/scripts/weather.py"

usage() {
  echo "Usage: $0 <version>"
  echo "Example: $0 0.1.1"
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

VERSION="$1"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid version: $VERSION"
  echo "Expected format: X.Y.Z"
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Cannot find script: $SCRIPT_PATH"
  exit 1
fi

cd "$ROOT_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is not clean. Commit or stash changes first."
  exit 1
fi

if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  echo "Tag v$VERSION already exists."
  exit 1
fi

sed -i "s/^__version__ = \".*\"$/__version__ = \"$VERSION\"/" "$SCRIPT_PATH"

git add "$SCRIPT_PATH"
git commit -m "release: v$VERSION"
git tag -a "v$VERSION" -m "v$VERSION"

echo "Released v$VERSION"
echo "Next:"
echo "  git push"
echo "  git push --tags"
