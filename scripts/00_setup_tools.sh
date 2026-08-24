#!/usr/bin/env bash
# Downloads the vendored binaries that are deliberately not committed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/tools"

EZKL_VERSION="v23.0.5"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ASSET="ezkl-windows-msvc.tar.gz"; BIN="ezkl.exe" ;;
  Darwin)               ASSET="ezkl-macos-aarch64.tar.gz"; BIN="ezkl" ;;
  *)                    ASSET="ezkl-linux-gnu.tar.gz";     BIN="ezkl" ;;
esac

if [ ! -f "$ROOT/tools/$BIN" ]; then
  echo "Downloading ezkl $EZKL_VERSION ($ASSET) ..."
  curl -sL -o "$ROOT/tools/ezkl.tar.gz" \
    "https://github.com/zkonduit/ezkl/releases/download/$EZKL_VERSION/$ASSET"
  tar -xzf "$ROOT/tools/ezkl.tar.gz" -C "$ROOT/tools"
  [ -f "$ROOT/tools/ezkl" ] && [ "$BIN" = "ezkl.exe" ] && mv "$ROOT/tools/ezkl" "$ROOT/tools/ezkl.exe"
  rm -f "$ROOT/tools/ezkl.tar.gz"
fi
"$ROOT/tools/$BIN" --version

echo
echo "Foundry: install via https://getfoundry.sh (forge/anvil/cast must be on PATH)."
