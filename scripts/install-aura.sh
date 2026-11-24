#!/usr/bin/env bash
# Install the Aura nightly pinned by baseline/aura-baseline.json.
# The archive must match the recorded per-arch sha256; the only stdout
# line is the directory that contains bin/aura.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
baseline="$root/baseline/aura-baseline.json"
[[ -f "$baseline" ]] || { echo "missing $baseline" >&2; exit 1; }

arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) arch="x86_64" ;;
  aarch64|arm64) arch="arm64" ;;
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;;
esac

key="linux-${arch}"
name="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["aura"]["assets"][sys.argv[2]]["name"])' "$baseline" "$key")"
want="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["aura"]["assets"][sys.argv[2]]["sha256"])' "$baseline" "$key")"
commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["aura"]["commit_sha"])' "$baseline")"
AURA_VERSION="${AURA_VERSION:-nightly}"
base="${AURA_DOWNLOAD_BASE:-https://github.com/cybrid-systems/aura/releases/download/${AURA_VERSION}}"
cache="${AURA_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/aura-pinned}/${commit:0:9}/${arch}"

if [[ ! -x "$cache/bin/aura" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL --retry 3 --retry-delay 1 -o "$tmp/$name" "$base/$name"
  printf '%s  %s\n' "$want" "$tmp/$name" | sha256sum -c - >&2
  tar -xzf "$tmp/$name" -C "$tmp"
  top=""
  for d in "$tmp"/*; do
    if [[ -d "$d/bin" ]]; then top="$d"; break; fi
  done
  [[ -n "$top" ]] || { echo "Aura archive has no bin/aura" >&2; exit 1; }
  rm -rf "$cache"
  mkdir -p "$(dirname "$cache")"
  mv "$top" "$cache"
fi

printf '%s\n' "$cache/bin"
"$cache/bin/aura" --version >&2
