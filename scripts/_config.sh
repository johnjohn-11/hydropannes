#!/usr/bin/env bash
# Ensures a minimal Home Assistant config for developing the hydropannes
# integration. Shared by scripts/setup and scripts/develop.
# Usage: scripts/_config.sh <config_dir>
set -e

CONFIG_DIR="$1"
mkdir -p "${CONFIG_DIR}"

# Establish a valid config skeleton (secrets.yaml, .storage, etc.) the first time.
if [[ ! -f "${CONFIG_DIR}/configuration.yaml" ]]; then
    hass --config "${CONFIG_DIR}" --script ensure_config
fi

CONFIG="${CONFIG_DIR}/configuration.yaml"

# Write the minimal config only on first creation or while it is still the
# stock default_config one. This preserves any later manual edits.
if [[ ! -s "${CONFIG}" ]] || grep -q "^default_config:" "${CONFIG}"; then
    cat > "${CONFIG}" <<'EOF'
# Minimal config for developing the hydropannes integration.
#
# default_config is intentionally NOT used here: it pulls in camera / stream /
# go2rtc / ffmpeg / dhcp components that need system binaries absent from this
# prebuilt image (harmless errors, but noisy logs). `frontend` alone provides
# the UI, onboarding and the integrations panel needed to add the integration
# via its config flow; `recorder` gives entity history.
#
# Want the full Home Assistant experience? Replace the two lines below with:
#   default_config:
# (and accept the harmless ffmpeg/go2rtc/dhcp warnings, or install those system
#  packages — see the project README / scripts).
frontend:
recorder:

logger:
  default: info
  logs:
    custom_components.hydropannes: debug
EOF
fi
