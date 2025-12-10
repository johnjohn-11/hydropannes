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
    mypy custom_components/hydropannes --ignore-missing-imports

# Validate JSON files
validate:
    python -m json.tool custom_components/hydropannes/manifest.json > /dev/null
    @echo "✅ manifest.json is valid"

# Install development dependencies
install:
    pip install ruff mypy homeassistant

# Clean cache files
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

# Bump version (usage: just bump 1.1.5)
bump version:
    @echo "Updating version to {{version}}"
    sed -i 's/"version": "[^"]*"/"version": "{{version}}"/' custom_components/hydropannes/manifest.json
    sed -i 's/^version = "[^"]*"/version = "{{version}}"/' pyproject.toml
    @echo "✅ Version updated to {{version}}"
