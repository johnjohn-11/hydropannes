# Justfile for Hydro-Pannes development
# Install just: https://github.com/casey/just

# Default recipe
default:
    @just --list

# Run all quality checks
qa: lint format-check type-check validate

# Run ruff linter
lint:
    ruff check custom_components/hydropannes

# Check formatting without modifying
format-check:
    ruff format --check custom_components/hydropannes

# Format code
format:
    ruff format custom_components/hydropannes

# Fix linting issues automatically
fix:
    ruff check --fix custom_components/hydropannes

# Run type checking
type-check:
    mypy custom_components/hydropannes

# Validate JSON files
validate:
    python -m json.tool custom_components/hydropannes/manifest.json > /dev/null
    python -m json.tool custom_components/hydropannes/strings.json > /dev/null
    python -m json.tool custom_components/hydropannes/translations/en.json > /dev/null
    python -m json.tool custom_components/hydropannes/translations/fr.json > /dev/null
    @echo "✅ JSON files are valid"

# Install development dependencies and git hooks
install:
    pip install ruff mypy pre-commit homeassistant
    pre-commit install

# Clean cache files
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

# Bump version locally (usage: just bump 1.1.5)
# Note: for releases, prefer `just release <version>` which bumps via CI.
bump version:
    @echo "Updating version to {{version}}"
    sed -i 's/"version": "[^"]*"/"version": "{{version}}"/' custom_components/hydropannes/manifest.json
    sed -i 's/^version = "[^"]*"/version = "{{version}}"/' pyproject.toml
    @echo "✅ Version updated to {{version}}"

# Publish a release: triggers the Release workflow on GitHub
# (bumps versions, commits, tags, builds the zip, publishes the release).
# Requires the GitHub CLI: https://cli.github.com
release version:
    gh workflow run release.yml -f version={{version}}
    @echo "🚀 Release {{version}} déclenchée — suivre: gh run watch"
