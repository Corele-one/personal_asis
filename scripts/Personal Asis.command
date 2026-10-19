#!/bin/sh
ASIS_INSTALLED="$HOME/Library/Application Support/PersonalAsis/launchers/asis-pi"
if [ -x "$ASIS_INSTALLED" ]; then
  exec "$ASIS_INSTALLED" "$@"
fi
ASIS_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$ASIS_SCRIPT_DIR/asis-pi" "$@"
