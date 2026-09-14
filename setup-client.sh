#!/usr/bin/env bash
# Run from a downloaded checkout; the Python installer explains and applies setup.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Instala Python 3.10 o posterior y vuelve a ejecutar este script." >&2
  exit 1
fi
exec python3 "$script_dir/logsentinel/client_setup.py" "$@"
