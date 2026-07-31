#!/usr/bin/env bash
set -euo pipefail

python_dir="$NANOKVM_APP_DIR/python"
mkdir -p "$python_dir"
install_tmp="$NANOKVM_APP_DIR/.install-tmp"
rm -rf "$install_tmp"
mkdir -p "$install_tmp"
trap 'rm -rf "$install_tmp"' EXIT
export TMPDIR="$install_tmp"

dependencies_ready() {
  PYTHONPATH="$python_dir" python3 - <<'PY'
import aiortc
import av
import cryptography
import google_crc32c
import pylibsrtp
import websockets
PY
}

if dependencies_ready; then
  echo "Voice Bridge Python dependencies are already available."
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  gcc python3-dev python3-pip libsrtp2-dev libffi-dev libssl-dev pkg-config

# PyPI's CDN can be extremely slow over the device's default route. Use a
# nearby mirror by default while still allowing deployments to select another
# index through the standard pip environment variable.
: "${PIP_INDEX_URL:=https://mirrors.aliyun.com/pypi/simple}"
export PIP_INDEX_URL

pip_common=(--disable-pip-version-check --no-cache-dir --timeout 60 --retries 10)
python3 -m pip install "${pip_common[@]}" --break-system-packages \
  --target "$python_dir" google-crc32c==1.8.0
python3 -m pip install "${pip_common[@]}" --break-system-packages \
  --target "$python_dir" pylibsrtp==1.0.0
python3 -m pip install "${pip_common[@]}" --break-system-packages \
  --target "$python_dir" --only-binary=:all: --no-deps \
  aioice==0.10.2 av==17.1.0 cryptography==49.0.0 pyee==13.0.1 \
  pyopenssl==26.3.0 websockets==16.0 dnspython==2.8.0 ifaddr==0.2.0 \
  typing-extensions==4.15.0
python3 -m pip install "${pip_common[@]}" --break-system-packages \
  --target "$python_dir" --only-binary=:all: --no-deps aiortc==1.15.0

dependencies_ready
