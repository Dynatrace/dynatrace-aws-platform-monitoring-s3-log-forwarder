#!/bin/bash

# Copyright 2024 Dynatrace LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#      https://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Creates a GitHub release for the given tag and attaches CloudFormation templates.
#
# Prerequisites:
#   - GitHub CLI (gh) installed and authenticated (gh auth login)
#
# Usage:
#   ./scripts/publish_github_release.sh --patch                        # Increment patch version (e.g. v1.2.3 -> v1.2.4)
#   ./scripts/publish_github_release.sh --minor                        # Increment minor version (e.g. v1.2.3 -> v1.3.0)
#   ./scripts/publish_github_release.sh --major                        # Increment major version (e.g. v1.2.3 -> v2.0.0)
#   ./scripts/publish_github_release.sh <tag>                          # Use explicit tag, e.g. v1.2.3
#
#   Any of the above can be combined with:
#   ./scripts/publish_github_release.sh --minor --draft                # Create as draft
#   ./scripts/publish_github_release.sh --minor --notes "..."          # Custom release notes
#   ./scripts/publish_github_release.sh <tag> --draft --notes "..."    # Explicit tag with draft and notes

set -e

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed. See https://cli.github.com for installation instructions." >&2
    exit 1
fi
echo "GitHub CLI found: $(gh --version | head -n1)"

if ! gh auth status &> /dev/null; then
    echo "Error: GitHub CLI is not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi
echo "GitHub CLI authenticated."

echo "Fetching tags from remote..."
git -C "$REPO_ROOT" fetch --tags --quiet
echo "Tags fetched."

# ---------------------------------------------------------------------------
# Resolve tag — auto-increment semver (major/minor/patch) from the latest tag if not explicitly provided
# ---------------------------------------------------------------------------

resolve_tag() {
    local bump="$1" latest major minor patch all_tags


    all_tags=$(git -C "$REPO_ROOT" tag --list 'v*.*.*' --sort=-version:refname)
    latest=$(echo "$all_tags" | head -n1)

    if [[ -z "$latest" ]]; then
        echo "No existing semver tags found, starting from v0.0.0." >&2
        major=0; minor=0; patch=0
    else
        echo "Found semver tags:" >&2
        echo "$all_tags" | while IFS= read -r t; do echo "  $t" >&2; done

        if [[ ! "$latest" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
            echo "Error: latest tag '$latest' does not follow semver (vMAJOR.MINOR.PATCH)" >&2
            exit 1
        fi
        major="${BASH_REMATCH[1]}"
        minor="${BASH_REMATCH[2]}"
        patch="${BASH_REMATCH[3]}"
        echo "Latest semver tag: $latest" >&2
    fi

    case "$bump" in
        major) echo "v$((major + 1)).0.0" ;;
        patch) echo "v${major}.${minor}.$((patch + 1))" ;;
        *)     echo "v${major}.$((minor + 1)).0" ;;  # default: minor
    esac
}

print_usage() {
    echo "Usage: $0 (--major | --minor | --patch | <tag>) [--draft] [--notes <text>]"
    echo ""
    echo "Tag selection (exactly one required):"
    echo "  --patch          Increment patch version (e.g. v1.2.3 -> v1.2.4)"
    echo "  --minor          Increment minor version (e.g. v1.2.3 -> v1.3.0)"
    echo "  --major          Increment major version (e.g. v1.2.3 -> v2.0.0)"
    echo "  <tag>            Use an explicit tag, e.g. v1.2.3"
    echo ""
    echo "Options:"
    echo "  --draft          Create the release as a draft"
    echo "  --notes <text>   Custom release notes (default: auto-generated from merged PRs)"
    echo "  -h, --help       Print this help message"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

# First argument is the tag only if it looks like a version (starts with v or digit)
if [[ $# -gt 0 && ( "$1" == v*.*.* || "$1" =~ ^[0-9] ) ]]; then
    TAG="$1"
    shift
fi

DRAFT=false
NOTES=""
BUMP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --major|--minor|--patch)
            if [[ -n "$BUMP" ]]; then
                echo "Error: --major, --minor and --patch are mutually exclusive." >&2
                exit 1
            fi
            BUMP="${1#--}"
            ;;
        --draft)
            DRAFT=true
            ;;
        --notes)
            NOTES="${2:?--notes requires a value}"
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo ""
            print_usage
            exit 1
            ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Validate tag — must follow vMAJOR.MINOR.PATCH and be unique in the repo
# ---------------------------------------------------------------------------

validate_tag() {
    local tag="$1"
    echo "Validating tag: $tag"

    if [[ ! "$tag" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        echo "Error: tag '$tag' is not valid. Expected format: vMAJOR.MINOR.PATCH (e.g. v1.2.3)." >&2
        exit 1
    fi
    echo "Tag format is valid."

    if git -C "$REPO_ROOT" tag --list | grep -qxF "$tag"; then
        echo "Error: tag '$tag' already exists in the repository." >&2
        exit 1
    fi
    echo "Tag is unique."
}

# ---------------------------------------------------------------------------
# Resolve tag from semver bump if not explicitly provided
if [[ -z "${TAG:-}" && -z "$BUMP" ]]; then
    echo "Error: provide an explicit tag (e.g. v1.2.3) or a bump flag (--major, --minor, --patch)." >&2
    echo "" >&2
    print_usage >&2
    exit 1
elif [[ -z "${TAG:-}" ]]; then
    TAG=$(resolve_tag "$BUMP")
    echo "New tag: $TAG"
elif [[ -n "$BUMP" ]]; then
    echo "Error: --major/--minor/--patch cannot be used together with an explicit tag." >&2
    exit 1
fi

validate_tag "$TAG"

# ---------------------------------------------------------------------------
# Validate assets
# ---------------------------------------------------------------------------

echo "Validating assets..."

ASSETS=(
    "$REPO_ROOT/template.yaml"
    "$REPO_ROOT/dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml"
    "$REPO_ROOT/dynatrace-aws-s3-log-forwarder-appconfig.yaml"
    "$REPO_ROOT/eventbridge-cross-region-or-account-forward-rules.yaml"
    "$REPO_ROOT/dynatrace-aws-s3-log-forwarder-layer.yaml"
)

for asset in "${ASSETS[@]}"; do
    if [[ ! -f "$asset" ]]; then
        echo "Error: asset not found: $asset" >&2
        exit 1
    fi
    echo "  Found: $(basename "$asset")"
done
echo "All assets validated."

# ---------------------------------------------------------------------------
# Build gh release create command
# ---------------------------------------------------------------------------

ZIP_NAME="dynatrace-aws-s3-log-forwarder-${TAG}.zip"

GH_ARGS=(
    release create "$TAG"
    --title "Release $TAG"
)

if [[ "$DRAFT" == true ]]; then
    GH_ARGS+=(--draft)
fi

if [[ -n "$NOTES" ]]; then
    GH_ARGS+=(--notes "$NOTES")
else
    GH_ARGS+=(--generate-notes)
fi

# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

echo "============================================"
echo "  GitHub Release Summary"
echo "============================================"
echo "  Tag:    $TAG"
echo "  Bump:   ${BUMP:-custom tag}"
echo "  Draft:  $DRAFT"
if [[ -n "$NOTES" ]]; then
    echo "  Notes:  $NOTES"
else
    echo "  Notes:  (auto-generated)"
fi
echo "  Upload: $ZIP_NAME"
echo "  Assets:"
for asset in "${ASSETS[@]}"; do
    echo "    - $(basename "$asset")"
done
echo "============================================"
echo ""
read -r -p "Proceed with release? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi
echo ""

ZIP_FILE="$(mktemp -d)/$ZIP_NAME"
echo "Packaging assets into $ZIP_NAME..."
zip -j "$ZIP_FILE" "${ASSETS[@]}" > /dev/null
echo "Assets packaged: $ZIP_FILE"

GH_ARGS+=("$ZIP_FILE")

printf 'Running: gh %s\n' "${GH_ARGS[*]}"
gh "${GH_ARGS[@]}"
rm -f "$ZIP_FILE"
echo "Temporary zip removed."

echo ""
echo "Release $TAG published successfully."
