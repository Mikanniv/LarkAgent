#!/bin/zsh
set -e
DESKTOP_DIR="${0:A:h}"
cd "$DESKTOP_DIR"

URL="${1:-}"
BRIDGE="http://127.0.0.1:17643"

if curl -sf --max-time 0.5 "$BRIDGE/bridge/state" >/dev/null 2>&1; then
  if [[ -z "$URL" || "$URL" == yunque://show-pet* ]]; then
    curl -sf --max-time 1 -X POST \
      -H "Origin: $BRIDGE" \
      -H "Content-Type: application/json" \
      -d '{"action":"set-visible","value":true}' \
      "$BRIDGE/bridge/command" >/dev/null 2>&1 || true
  fi
  exit 0
fi

ELECTRON_BIN="$DESKTOP_DIR/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
if [[ -x "$ELECTRON_BIN" ]]; then
  nohup "$ELECTRON_BIN" "$DESKTOP_DIR" --show-pet >/tmp/yunque-desktop.log 2>&1 </dev/null &
  exit 0
fi

# First-time setup: open Terminal to install Electron via 启动云雀.command
open -a Terminal "$DESKTOP_DIR/启动云雀.command"
