#!/usr/bin/env bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ -z "$1" ]; then
    print_error "Usage: $0 <version>"
    print_error "Example: $0 0.2.0"
    exit 1
fi

VERSION=$1
TAG="v${VERSION}"

if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_error "Invalid version format. Please use semantic versioning (e.g., 0.2.0)"
    exit 1
fi

print_info "Preparing release ${TAG}..."

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    print_error "Not in a git repository"
    exit 1
fi

if ! git diff-index --quiet HEAD --; then
    print_error "Working directory is not clean. Please commit or stash your changes."
    exit 1
fi

CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    print_warn "You are not on the main branch (current: ${CURRENT_BRANCH})"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Aborted"
        exit 1
    fi
fi

# Fail before the slow checks rather than after them.
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null \
    || git ls-remote --exit-code --tags origin "refs/tags/${TAG}" >/dev/null 2>&1; then
    print_error "Tag ${TAG} already exists"
    exit 1
fi

print_info "Pulling latest changes..."
git pull origin "$CURRENT_BRANCH"

# The release dates the Unreleased section itself. Without one there is nothing
# to describe the release, which is a mistake to catch before the slow checks.
CHANGELOG_FILE="CHANGELOG.md"
if ! grep -q '^## Unreleased$' "$CHANGELOG_FILE" 2>/dev/null; then
    print_error "${CHANGELOG_FILE} has no '## Unreleased' section to release"
    exit 1
fi

# Tests and lint run before any file is touched, so a failure leaves the working
# tree exactly as it was.
VENV_PYTHON="venv/bin/python"
VENV_RUFF="venv/bin/ruff"

if [ ! -x "$VENV_PYTHON" ]; then
    print_error "Test environment not found at ./${VENV_PYTHON}"
    print_error "Run 'make install' first."
    exit 1
fi

print_info "Running tests..."
"$VENV_PYTHON" -m pytest tests/

if [ -x "$VENV_RUFF" ]; then
    print_info "Running linter..."
    "$VENV_RUFF" check custom_components/ tests/
else
    print_error "ruff not found at ./${VENV_RUFF}. Run 'make install' first."
    exit 1
fi

MANIFEST_FILE="custom_components/cover_control/manifest.json"
INIT_FILE="custom_components/cover_control/__init__.py"
if [ ! -f "$MANIFEST_FILE" ]; then
    print_error "Manifest file not found: $MANIFEST_FILE"
    exit 1
fi

# From here on the tree gets modified; put it back if we bail out.
restore_version_files() {
    local code=$?
    [ "$code" -eq 0 ] && return
    print_warn "Release failed, restoring version files..."
    git checkout -- "$MANIFEST_FILE" "$INIT_FILE" "$CHANGELOG_FILE" 2>/dev/null || true
}
trap restore_version_files EXIT

print_info "Updating version in manifest.json..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/\"version\": \"[^\"]*\"/\"version\": \"${VERSION}\"/" "$MANIFEST_FILE"
else
    sed -i "s/\"version\": \"[^\"]*\"/\"version\": \"${VERSION}\"/" "$MANIFEST_FILE"
fi

NEW_VERSION=$(grep -o '"version": "[^"]*"' "$MANIFEST_FILE" | cut -d'"' -f4)
if [ "$NEW_VERSION" != "$VERSION" ]; then
    print_error "Failed to update version in manifest.json"
    exit 1
fi
print_info "manifest.json → ${VERSION}"

# The dashboard strategy is served with ?v=<version>; bump it too or browsers
# keep running the copy they cached before the upgrade.
print_info "Updating STRATEGY_VERSION in ${INIT_FILE}..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^STRATEGY_VERSION = \"[^\"]*\"/STRATEGY_VERSION = \"${VERSION}\"/" "$INIT_FILE"
else
    sed -i "s/^STRATEGY_VERSION = \"[^\"]*\"/STRATEGY_VERSION = \"${VERSION}\"/" "$INIT_FILE"
fi

# Verified like the manifest is: a silent no-op here ships a release whose
# dashboard keeps serving the strategy browsers cached before the upgrade,
# which looks like the new dashboard code simply not working.
NEW_STRATEGY_VERSION=$(grep -o '^STRATEGY_VERSION = "[^"]*"' "$INIT_FILE" | cut -d'"' -f2)
if [ "$NEW_STRATEGY_VERSION" != "$VERSION" ]; then
    print_error "Failed to update STRATEGY_VERSION in ${INIT_FILE}"
    exit 1
fi
print_info "${INIT_FILE} → STRATEGY_VERSION ${VERSION}"

RELEASE_DATE=$(date +%Y-%m-%d)
print_info "Dating the Unreleased section in ${CHANGELOG_FILE}..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^## Unreleased$/## ${VERSION} - ${RELEASE_DATE}/" "$CHANGELOG_FILE"
else
    sed -i "s/^## Unreleased$/## ${VERSION} - ${RELEASE_DATE}/" "$CHANGELOG_FILE"
fi
print_info "${CHANGELOG_FILE} → ## ${VERSION} - ${RELEASE_DATE}"

git add "$MANIFEST_FILE" "$INIT_FILE" "$CHANGELOG_FILE"
# Releasing the version already in the manifest (the first release, say)
# changes nothing, and an empty commit would abort the whole release.
if git diff --cached --quiet; then
    print_info "Version files already at ${VERSION}, nothing to commit"
else
    print_info "Committing version bump..."
    git commit -m "chore: bump version to ${VERSION}"
fi

print_info "Creating tag ${TAG}..."
git tag -a "$TAG" -m "Release ${TAG}"

print_info "Pushing changes and tag..."
git push origin "$CURRENT_BRANCH"
git push origin "$TAG"

print_info ""
print_info "✓ Release ${TAG} created successfully!"
print_info ""
print_info "Next steps:"
print_info "  1. GitHub Actions will automatically create a release with the zip file"
print_info "  2. Go to https://github.com/josa42/homeassistant-cover-control/releases"
print_info "  3. Edit the release notes if needed"
print_info ""
print_info "The integration zip file will be available for HACS installation"
