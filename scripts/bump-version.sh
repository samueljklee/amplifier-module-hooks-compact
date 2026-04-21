#!/usr/bin/env bash
# Atomically update the version string across all three files that hardcode it.
#
# Usage: ./scripts/bump-version.sh <new-version>
#
# Files updated:
#   pyproject.toml:3      — version = "X.Y.Z"
#   bundle.md:4           — version: X.Y.Z
#   behaviors/compact.yaml:3 — version: X.Y.Z
#
# __init__.py is NOT in this list — it reads from pyproject.toml at runtime
# via importlib.metadata.version().

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <new-version>" >&2
    echo "Example: $0 0.2.0" >&2
    exit 1
fi

NEW_VERSION="$1"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Validate version looks reasonable (semver-ish)
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
    echo "Error: version '$NEW_VERSION' doesn't look like semver (X.Y.Z)" >&2
    exit 1
fi

echo "Bumping version to $NEW_VERSION in 3 files..."

# 1. pyproject.toml — line 3: version = "X.Y.Z"
sed -i '' "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$REPO_ROOT/pyproject.toml"
echo "  ✓ pyproject.toml"

# 2. bundle.md — line 4: version: X.Y.Z (under bundle: frontmatter)
sed -i '' "s/^  version: .*/  version: $NEW_VERSION/" "$REPO_ROOT/bundle.md"
echo "  ✓ bundle.md"

# 3. behaviors/compact.yaml — line 3: version: X.Y.Z
sed -i '' "s/^  version: .*/  version: $NEW_VERSION/" "$REPO_ROOT/behaviors/compact.yaml"
echo "  ✓ behaviors/compact.yaml"

echo ""
echo "Done. Verify with:"
echo "  grep -n 'version' pyproject.toml bundle.md behaviors/compact.yaml | head -6"
