#!/usr/bin/env bash
set -euo pipefail

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)
    arch=x86_64
    actionlint_arch=amd64
    ruff_sha=a293ac937715ae6fb6b64da86761598379e6149f40fbc00fde9ba8a2a562ac65
    actionlint_sha=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
    zizmor_sha=d185f726bdaf92df78273217dfdd24ebcd6b0ef48cf3ce776ff5762b6e138c99
    shellcheck_sha=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
    ;;
  Linux-aarch64)
    arch=aarch64
    actionlint_arch=arm64
    ruff_sha=d3ead1f0ed779e777a034ccd9286be6bd9bd3cdaba732ff9797f8288a283e9e2
    actionlint_sha=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6
    zizmor_sha=37eebbd5762a44f262d94875431b14a6d2402991e90a685113ea97b8b41be833
    shellcheck_sha=12b331c1d2db6b9eb13cfca64306b1b157a86eb69db83023e261eaa7e7c14588
    ;;
  *)
    echo "CI tool installer supports Linux x86_64 and aarch64 only" >&2
    exit 2
    ;;
esac
[[ "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" == 3.12 ]] || {
  echo "CI tool installer requires Python 3.12 for the hash-locked Bandit wheel set" >&2
  exit 2
}

DEST="${1:?usage: install-ci-tools.sh DEST}"
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DEST/bin" "$DEST/venv"

fetch() {
  local url="$1" expected="$2" output="$3"
  curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --output "$output" "$url"
  printf '%s  %s\n' "$expected" "$output" | sha256sum --check --strict
}

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
fetch "https://github.com/astral-sh/ruff/releases/download/0.17.1/ruff-${arch}-unknown-linux-gnu.tar.gz" \
  "$ruff_sha" "$tmp/ruff.tgz"
tar -xzf "$tmp/ruff.tgz" -C "$tmp"
install -m 0755 "$tmp/ruff-${arch}-unknown-linux-gnu/ruff" "$DEST/bin/ruff"

fetch "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_${actionlint_arch}.tar.gz" \
  "$actionlint_sha" "$tmp/actionlint.tgz"
tar -xzf "$tmp/actionlint.tgz" -C "$tmp" actionlint
install -m 0755 "$tmp/actionlint" "$DEST/bin/actionlint"

fetch "https://github.com/zizmorcore/zizmor/releases/download/v1.31.1/zizmor-${arch}-unknown-linux-gnu.tar.gz" \
  "$zizmor_sha" "$tmp/zizmor.tgz"
tar -xzf "$tmp/zizmor.tgz" -C "$tmp" zizmor
install -m 0755 "$tmp/zizmor" "$DEST/bin/zizmor"

fetch "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.${arch}.tar.xz" \
  "$shellcheck_sha" "$tmp/shellcheck.tar.xz"
tar -xJf "$tmp/shellcheck.tar.xz" -C "$tmp"
install -m 0755 "$tmp/shellcheck-v0.11.0/shellcheck" "$DEST/bin/shellcheck"

python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --disable-pip-version-check --require-hashes \
  -r "$TOOLS_DIR/ci/bandit-requirements-linux-${arch}.txt"
ln -sf "$DEST/venv/bin/bandit" "$DEST/bin/bandit"

mkdir -p "$DEST/pyright"
cp "$TOOLS_DIR/ci/package.json" "$TOOLS_DIR/ci/package-lock.json" "$DEST/pyright/"
(cd "$DEST/pyright" && npm ci --ignore-scripts --no-audit --no-fund)
ln -sf "$DEST/pyright/node_modules/.bin/pyright" "$DEST/bin/pyright"
