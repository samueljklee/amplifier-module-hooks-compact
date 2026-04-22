#!/usr/bin/env bash
# Atomically bump the canary tag across all 5 intentional reference locations.
#
# Usage: ./scripts/bump-canary.sh <new-tag> [options]
#
# Files updated (5 lines across 4 files):
#   behaviors/compact.yaml:8              — @vX.Y.Z-canary.N
#   README.md:10                          — @vX.Y.Z-canary.N
#   eval/profiles/hooks-compact-with.yaml:72,74  — @vX.Y.Z-canary.N (x2)
#   tests/test_dtu_profiles.py:15         — CANARY_TAG = "vX.Y.Z-canary.N"
#
# Source of truth for current tag: behaviors/compact.yaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DRY_RUN=false
NO_PUSH=false
REPLACE_TAG=false
NEW_TAG=""

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<'EOF'
Usage: ./scripts/bump-canary.sh <new-tag> [options]

Atomically bump the canary tag across all 5 intentional reference locations.

Arguments:
  <new-tag>    New tag — must match v[0-9]+.[0-9]+.[0-9]+-canary.[0-9]+

Options:
  --replace    Delete the old tag (locally + from origin if pushing) before
               creating the new one. Without this flag, fails if <new-tag>
               already exists.
  --no-push    Leave changes local; don't push branch or tag to origin.
  --dry-run    Print every step and resulting state — make no changes.
  -h, --help   Show this usage message.

Example:
  ./scripts/bump-canary.sh v0.1.0-canary.2
  → current tag: v0.1.0-canary.1
  → new tag:     v0.1.0-canary.2
  → running pytest baseline... 317 passed
  → editing 5 references across 4 files...
  → verifying: 0 old references remain, 5 new references present
  → committing: chore: bump canary tag v0.1.0-canary.1 → v0.1.0-canary.2
  → creating annotated tag v0.1.0-canary.2 on HEAD
  → pushing branch fix/pre-canary-hygiene to origin
  → pushing tag v0.1.0-canary.2 to origin
  ✓ canary tag bumped. PR #2 will auto-update.
EOF
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
if [ $# -eq 0 ]; then
    usage >&2
    exit 1
fi

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-push)
            NO_PUSH=true
            shift
            ;;
        --replace)
            REPLACE_TAG=true
            shift
            ;;
        -*)
            echo "Error: unknown flag '$1'" >&2
            exit 1
            ;;
        *)
            if [ -n "$NEW_TAG" ]; then
                echo "Error: unexpected argument '$1'" >&2
                exit 1
            fi
            NEW_TAG="$1"
            shift
            ;;
    esac
done

if [ -z "$NEW_TAG" ]; then
    echo "Error: <new-tag> is required" >&2
    usage >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Validate new-tag format
# ---------------------------------------------------------------------------
if ! echo "$NEW_TAG" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+-canary\.[0-9]+$'; then
    echo "Error: tag '$NEW_TAG' doesn't match required format v[0-9]+.[0-9]+.[0-9]+-canary.[0-9]+" >&2
    echo "Example: v0.1.0-canary.2" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Auto-detect current tag from behaviors/compact.yaml (source of truth)
# ---------------------------------------------------------------------------
CURRENT_TAG=$(grep -oE '@v[0-9]+\.[0-9]+\.[0-9]+-canary\.[0-9]+' \
    "$REPO_ROOT/behaviors/compact.yaml" | head -1 | sed 's/@//')

if [ -z "$CURRENT_TAG" ]; then
    echo "Error: could not detect current canary tag from behaviors/compact.yaml" >&2
    echo "Expected a line containing @vX.Y.Z-canary.N" >&2
    exit 1
fi

echo "→ current tag: $CURRENT_TAG"
echo "→ new tag:     $NEW_TAG"

# ---------------------------------------------------------------------------
# 3. Fail fast if working tree is dirty
# ---------------------------------------------------------------------------
if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    echo "Error: working tree is dirty. Commit or stash changes before bumping." >&2
    exit 1
fi

# Capture current branch for push step
CURRENT_BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)

# ---------------------------------------------------------------------------
# 4. Run pytest baseline (skipped in --dry-run)
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    echo "→ [dry-run] would run: uv run pytest tests/ -q"
else
    echo "→ running pytest baseline..."
    (cd "$REPO_ROOT" && uv run pytest tests/ -q)
fi

# ---------------------------------------------------------------------------
# 5. Edit the 5 lines across 4 files
#    Trap ensures atomic rollback if any edit fails mid-sequence.
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    echo "→ [dry-run] would edit 5 references across 4 files (${CURRENT_TAG} → ${NEW_TAG})"
else
    # Install rollback trap before the first file is touched
    trap 'echo "→ error during edits — rolling back all file changes" >&2
          git -C "$REPO_ROOT" checkout -- .
          exit 1' ERR

    # 1. behaviors/compact.yaml
    sed -i '' \
        "s|amplifier-module-hooks-compact@${CURRENT_TAG}|amplifier-module-hooks-compact@${NEW_TAG}|g" \
        "$REPO_ROOT/behaviors/compact.yaml"
    echo "  ✓ behaviors/compact.yaml"

    # 2. README.md
    sed -i '' \
        "s|amplifier-module-hooks-compact@${CURRENT_TAG}|amplifier-module-hooks-compact@${NEW_TAG}|g" \
        "$REPO_ROOT/README.md"
    echo "  ✓ README.md"

    # 3+4. eval/profiles/hooks-compact-with.yaml (2 occurrences on separate lines)
    sed -i '' \
        "s|amplifier-module-hooks-compact@${CURRENT_TAG}|amplifier-module-hooks-compact@${NEW_TAG}|g" \
        "$REPO_ROOT/eval/profiles/hooks-compact-with.yaml"
    echo "  ✓ eval/profiles/hooks-compact-with.yaml (x2)"

    # 5. tests/test_dtu_profiles.py
    sed -i '' \
        "s|CANARY_TAG = \"${CURRENT_TAG}\"|CANARY_TAG = \"${NEW_TAG}\"|" \
        "$REPO_ROOT/tests/test_dtu_profiles.py"
    echo "  ✓ tests/test_dtu_profiles.py"

    # All 5 edits succeeded — disarm the rollback trap
    trap - ERR
fi

# ---------------------------------------------------------------------------
# 6. Verify completeness
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    echo "→ [dry-run] would verify: 0 old references remain, 5 new references present"
else
    echo "→ verifying replacement completeness..."

    OLD_HITS=$(grep -rF "$CURRENT_TAG" \
        --exclude-dir='.git' \
        --exclude-dir='plans' \
        --exclude-dir='results' \
        "$REPO_ROOT" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$OLD_HITS" -ne 0 ]; then
        echo "Error: $OLD_HITS reference(s) to old tag '${CURRENT_TAG}' still remain:" >&2
        grep -rF "$CURRENT_TAG" \
            --exclude-dir='.git' \
            --exclude-dir='plans' \
            --exclude-dir='results' \
            "$REPO_ROOT" >&2 || true
        exit 1
    fi

    NEW_HITS=$(grep -rF "$NEW_TAG" \
        --exclude-dir='.git' \
        --exclude-dir='plans' \
        --exclude-dir='results' \
        "$REPO_ROOT" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$NEW_HITS" -ne 5 ]; then
        echo "Error: expected exactly 5 references to '${NEW_TAG}', found ${NEW_HITS}" >&2
        exit 1
    fi

    echo "→ verifying: 0 old references remain, 5 new references present"
fi

# ---------------------------------------------------------------------------
# 7. Commit
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    echo "→ [dry-run] would commit: chore: bump canary tag ${CURRENT_TAG} → ${NEW_TAG}"
else
    echo "→ committing: chore: bump canary tag ${CURRENT_TAG} → ${NEW_TAG}"
    git -C "$REPO_ROOT" add \
        behaviors/compact.yaml \
        README.md \
        eval/profiles/hooks-compact-with.yaml \
        tests/test_dtu_profiles.py
    git -C "$REPO_ROOT" commit -m "chore: bump canary tag ${CURRENT_TAG} → ${NEW_TAG}

Updated references in:
- behaviors/compact.yaml
- README.md
- eval/profiles/hooks-compact-with.yaml (x2)
- tests/test_dtu_profiles.py"
fi

# ---------------------------------------------------------------------------
# 8. Handle old tag
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    if [ "$REPLACE_TAG" = true ]; then
        echo "→ [dry-run] would delete old tag ${CURRENT_TAG} locally"
        if [ "$NO_PUSH" = false ]; then
            echo "→ [dry-run] would delete old tag ${CURRENT_TAG} from origin"
        fi
    fi
else
    if [ "$REPLACE_TAG" = true ]; then
        git -C "$REPO_ROOT" tag -d "$CURRENT_TAG" 2>/dev/null || true
        echo "→ deleted old tag ${CURRENT_TAG} locally"
        if [ "$NO_PUSH" = false ]; then
            git -C "$REPO_ROOT" push --delete origin "$CURRENT_TAG" || true
            echo "→ deleted old tag ${CURRENT_TAG} from origin"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 9. Create new annotated tag
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    if git -C "$REPO_ROOT" tag -l "$NEW_TAG" | grep -q "^${NEW_TAG}$" 2>/dev/null; then
        echo "→ [dry-run] note: tag ${NEW_TAG} already exists (use --replace to overwrite)"
    else
        echo "→ [dry-run] would create annotated tag ${NEW_TAG} on HEAD"
    fi
else
    # Check for existing tag when --replace was not requested
    if git -C "$REPO_ROOT" tag -l "$NEW_TAG" | grep -q "^${NEW_TAG}$" 2>/dev/null; then
        if [ "$REPLACE_TAG" = false ]; then
            echo "Error: tag '${NEW_TAG}' already exists. Use --replace to overwrite." >&2
            exit 1
        fi
    fi
    echo "→ creating annotated tag ${NEW_TAG} on HEAD"
    git -C "$REPO_ROOT" tag -a "$NEW_TAG" -m "Canary tag ${NEW_TAG}

Bumped from ${CURRENT_TAG} via scripts/bump-canary.sh"
fi

# ---------------------------------------------------------------------------
# 10. Push
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    if [ "$NO_PUSH" = false ]; then
        echo "→ [dry-run] would push branch ${CURRENT_BRANCH} to origin"
        echo "→ [dry-run] would push tag ${NEW_TAG} to origin"
    else
        echo "→ [dry-run] --no-push: skipping push"
    fi
elif [ "$NO_PUSH" = false ]; then
    echo "→ pushing branch ${CURRENT_BRANCH} to origin"
    git -C "$REPO_ROOT" push origin "$CURRENT_BRANCH"
    echo "→ pushing tag ${NEW_TAG} to origin"
    git -C "$REPO_ROOT" push origin "$NEW_TAG"
fi

echo "✓ canary tag bumped. PR #2 will auto-update."
