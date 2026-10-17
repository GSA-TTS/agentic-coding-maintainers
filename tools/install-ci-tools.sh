#!/usr/bin/env bash
set -euo pipefail

[[ "$(uname -s)-$(uname -m)" == Linux-x86_64 ]] || {
  echo "CI tool installer supports Linux x86_64 only" >&2
  exit 2
}

DEST="${1:?usage: install-ci-tools.sh DEST}"
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DEST/bin" "$DEST/venv"

fetch() {
  local url="$1" expected="$2" output="$3"
  curl --fail --location --proto '=https' --tlsv1.2 --output "$output" "$url"
  printf '%s  %s\n' "$expected" "$output" | sha256sum --check --strict
}

tmp="$(mktemp -d)"
fetch https://github.com/astral-sh/ruff/releases/download/0.17.1/ruff-x86_64-unknown-linux-gnu.tar.gz \
  a293ac937715ae6fb6b64da86761598379e6149f40fbc00fde9ba8a2a562ac65 "$tmp/ruff.tgz"
tar -xzf "$tmp/ruff.tgz" -C "$tmp"
install -m 0755 "$tmp/ruff-x86_64-unknown-linux-gnu/ruff" "$DEST/bin/ruff"

fetch https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz \
  8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 "$tmp/actionlint.tgz"
tar -xzf "$tmp/actionlint.tgz" -C "$tmp" actionlint
install -m 0755 "$tmp/actionlint" "$DEST/bin/actionlint"

fetch https://github.com/zizmorcore/zizmor/releases/download/v1.31.1/zizmor-x86_64-unknown-linux-gnu.tar.gz \
  d185f726bdaf92df78273217dfdd24ebcd6b0ef48cf3ce776ff5762b6e138c99 "$tmp/zizmor.tgz"
tar -xzf "$tmp/zizmor.tgz" -C "$tmp" zizmor
install -m 0755 "$tmp/zizmor" "$DEST/bin/zizmor"

fetch https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.x86_64.tar.xz \
  8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198 "$tmp/shellcheck.tar.xz"
tar -xJf "$tmp/shellcheck.tar.xz" -C "$tmp"
install -m 0755 "$tmp/shellcheck-v0.11.0/shellcheck" "$DEST/bin/shellcheck"

python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --disable-pip-version-check --require-hashes \
  -r "$TOOLS_DIR/ci/bandit-requirements-linux-x86_64.txt"
ln -sf "$DEST/venv/bin/bandit" "$DEST/bin/bandit"

(cd "$TOOLS_DIR/ci" && npm ci --ignore-scripts --no-audit --no-fund)
ln -sf "$TOOLS_DIR/ci/node_modules/.bin/pyright" "$DEST/bin/pyright"
