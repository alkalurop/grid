#!/bin/bash
# Analyze one playlist and write the beat grid into rekordbox.xml or Traktor NML.
#
#   docs/examples/beatgrid.sh "Deep House" --xml
#   docs/examples/beatgrid.sh "Deep House" --nml --execute
#
# Dry-run is the default. --execute needs grid-analyse:
#   cargo build --release --manifest-path beatgrid/engine/Cargo.toml
#
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=beatgrid
exec python3 -u -m beatgrid "$@"
