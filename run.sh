#!/usr/bin/env bash
# run.sh — 自动建 venv、装依赖，然后执行 wg_add_peer.py
# 用法:
#   ./run.sh --name phone-pixel9
#   ./run.sh --name phone-pixel9 --split-tunnel
#   ./run.sh --name phone-pixel9 --dns 8.8.8.8
#   ./run.sh --name ios18.5 --dns 1.1.1.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

# 首次运行自动建 venv
if [[ ! -f "$VENV/bin/activate" ]]; then
    echo "[+] 创建虚拟环境 ..."
    python3 -m venv "$VENV"
    echo "[+] 安装依赖 ..."
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
    echo "[+] 依赖安装完毕。"
fi

source "$VENV/bin/activate"
python3 "$SCRIPT_DIR/wg_add_peer.py" "$@"
