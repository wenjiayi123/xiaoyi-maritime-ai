#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

XIAOYI_PROJECT_ROOT="$PWD"
XIAOYI_DESKTOP_ROOT="$(dirname "$XIAOYI_PROJECT_ROOT")"
PORT_CONTRACT_FILE="$XIAOYI_PROJECT_ROOT/config/local_ports.env"
REQUESTED_XIAOYI_PORT="${XIAOYI_PORT:-}"
if [[ -f "$PORT_CONTRACT_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$PORT_CONTRACT_FILE"
  set +a
fi
if [[ -n "$REQUESTED_XIAOYI_PORT" ]]; then
  XIAOYI_PORT="$REQUESTED_XIAOYI_PORT"
fi
export XIAOYI_PORT="${XIAOYI_PORT:-8010}"
export XIAOYI_SIMULATOR_URL="${XIAOYI_SIMULATOR_URL:-http://127.0.0.1:${PORT_DT_SERVER_PORT:-8000}/}"
export XIAOYI_PORT_DT_HEALTH_URL="${XIAOYI_PORT_DT_HEALTH_URL:-http://127.0.0.1:${PORT_DT_SERVER_PORT:-8000}/health/live}"
export XIAOYI_ENERGY_UI_URL="${XIAOYI_ENERGY_UI_URL:-http://127.0.0.1:${ENERGY_FRONTEND_PORT:-5173}/}"
export XIAOYI_ENERGY_HEALTH_URL="${XIAOYI_ENERGY_HEALTH_URL:-http://127.0.0.1:${ENERGY_BACKEND_PORT:-8808}/api/linkage/health}"
export XIAOYI_ENERGY_API_URL="${XIAOYI_ENERGY_API_URL:-http://127.0.0.1:${ENERGY_BACKEND_PORT:-8808}}"
export XIAOYI_MALACCA_UI_URL="${XIAOYI_MALACCA_UI_URL:-http://127.0.0.1:${MALACCA_PORT:-5174}/}"
export XIAOYI_MALACCA_HEALTH_URL="${XIAOYI_MALACCA_HEALTH_URL:-http://127.0.0.1:${MALACCA_PORT:-5174}/api/rl/health}"

if command -v lsof >/dev/null 2>&1 \
  && lsof -nP -iTCP:"$XIAOYI_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl --fail --silent --max-time 2 "http://127.0.0.1:${XIAOYI_PORT}/" \
    | grep -q "港航小懿AI"; then
    echo "小懿已在 http://127.0.0.1:${XIAOYI_PORT}/ 运行，直接复用。"
    exit 0
  fi
  echo "端口契约冲突：${XIAOYI_PORT} 已被非小懿服务占用，已拒绝重复启动。" >&2
  lsof -nP -iTCP:"$XIAOYI_PORT" -sTCP:LISTEN >&2 || true
  exit 2
fi
if [[ -z "${XIAOYI_SIMULATOR_ROOT:-}" && -d "$XIAOYI_DESKTOP_ROOT/模拟器/port-dt-multi" ]]; then
  export XIAOYI_SIMULATOR_ROOT="$XIAOYI_DESKTOP_ROOT/模拟器/port-dt-multi"
fi
if [[ -z "${XIAOYI_SIMULATOR_PYTHON:-}" && -x "${XIAOYI_SIMULATOR_ROOT:-}/.venv312/bin/python" ]]; then
  export XIAOYI_SIMULATOR_PYTHON="$XIAOYI_SIMULATOR_ROOT/.venv312/bin/python"
fi
if [[ -z "${XIAOYI_ENERGY_ROOT:-}" && -d "$XIAOYI_DESKTOP_ROOT/能碳驾驶舱" ]]; then
  export XIAOYI_ENERGY_ROOT="$XIAOYI_DESKTOP_ROOT/能碳驾驶舱"
fi
if [[ -z "${XIAOYI_MALACCA_ROOT:-}" && -d "$XIAOYI_DESKTOP_ROOT/马六甲沙盘港口推演" ]]; then
  export XIAOYI_MALACCA_ROOT="$XIAOYI_DESKTOP_ROOT/马六甲沙盘港口推演"
fi
if [[ -z "${XIAOYI_SAILING_SIMULATOR_ROOT:-}" && -d "$XIAOYI_DESKTOP_ROOT/航行模拟器" ]]; then
  export XIAOYI_SAILING_SIMULATOR_ROOT="$XIAOYI_DESKTOP_ROOT/航行模拟器"
fi
export XIAOYI_SAILING_BRIDGE_DIR="${XIAOYI_SAILING_BRIDGE_DIR:-$XIAOYI_PROJECT_ROOT/.runtime/sailing-bridge}"
LOCAL_GODOT_BINARY="$XIAOYI_PROJECT_ROOT/.runtime/tools/godot-4.7.1/Godot.app/Contents/MacOS/Godot"
if [[ -z "${XIAOYI_GODOT_BINARY:-}" && -x "$LOCAL_GODOT_BINARY" ]]; then
  export XIAOYI_GODOT_BINARY="$LOCAL_GODOT_BINARY"
fi

PYTHON_BIN="${XIAOYI_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ ! -x .venv/bin/python ]]; then
    BOOTSTRAP_PYTHON="${XIAOYI_BOOTSTRAP_PYTHON:-}"
    if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
      BOOTSTRAP_PYTHON="$(command -v python3.12 || command -v python3 || true)"
    fi
    if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
      echo "未找到 Python 3.12；请先安装 Python 3.12。" >&2
      exit 2
    fi
    if ! "$BOOTSTRAP_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)'; then
      echo "检测到的 Python 低于 3.12；请设置 XIAOYI_BOOTSTRAP_PYTHON=/path/to/python3.12。" >&2
      exit 2
    fi
    "$BOOTSTRAP_PYTHON" -m venv .venv
  fi
  PYTHON_BIN=".venv/bin/python"
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)'; then
  echo "当前虚拟环境低于 Python 3.12，无法安装已修复安全漏洞的锁定依赖。" >&2
  echo "请移动旧 .venv 后，使用 python3.12 -m venv .venv 重建。" >&2
  exit 2
fi

LOCK_DIGEST="$("$PYTHON_BIN" -c 'import hashlib; print(hashlib.sha256(open("requirements.lock", "rb").read()).hexdigest())')"
LOCK_MARKER="$(dirname "$PYTHON_BIN")/.xiaoyi-requirements-lock.sha256"
INSTALLED_LOCK_DIGEST=""
if [[ -f "$LOCK_MARKER" ]]; then
  INSTALLED_LOCK_DIGEST="$(<"$LOCK_MARKER")"
fi
if [[ "$LOCK_DIGEST" != "$INSTALLED_LOCK_DIGEST" ]] \
  || ! "$PYTHON_BIN" -c 'import fastapi, pydantic, uvicorn' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install --require-hashes -r requirements.lock
  printf '%s\n' "$LOCK_DIGEST" >"$LOCK_MARKER"
fi

if [[ ! -f data/public/uci_appliances_energy.csv ]]; then
  "$PYTHON_BIN" scripts/fetch_public_rl_dataset.py
fi

"$PYTHON_BIN" scripts/build_index.py

MODEL_PID=""
EMBEDDING_PID=""
APP_PID=""
discover_weight_by_size() {
  find "$PWD/.runtime/models" -maxdepth 1 -type f -size "$1" -print -quit 2>/dev/null
}
DISCOVERED_GENERATION_MODEL="$(discover_weight_by_size 2497280256c)"
MODEL_FILE="${XIAOYI_LOCAL_MODEL_PATH:-${DISCOVERED_GENERATION_MODEL:-$PWD/.runtime/models/maritime-generation-4b-q4-k-m.gguf}}"
export XIAOYI_LOCAL_MODEL_PATH="$MODEL_FILE"
MODEL_PORT="${XIAOYI_LOCAL_MODEL_PORT:-11435}"
MODEL_ENABLED="${XIAOYI_GENERATIVE_MODEL_ENABLED:-auto}"
BUNDLED_LLAMA_SERVER="$PWD/.runtime/llama.cpp/llama-server"
LLAMA_SERVER_BIN="${XIAOYI_LLAMA_SERVER_BIN:-$(command -v llama-server || true)}"
if [[ -z "$LLAMA_SERVER_BIN" && -x "$BUNDLED_LLAMA_SERVER" ]]; then
  LLAMA_SERVER_BIN="$BUNDLED_LLAMA_SERVER"
fi
MODEL_ID=xiaoyi-local-4b-q4-k-m
MODEL_ALIAS=xiaoyi-local-4b
MODEL_CONTEXT=4096
USE_LORA=false
DISCOVERED_TRAINING_MODEL="$(discover_weight_by_size 1834426016c)"
LORA_MODEL_FILE="${XIAOYI_LORA_MODEL_PATH:-${DISCOVERED_TRAINING_MODEL:-$PWD/.runtime/models/maritime-training-1.7b-q8-0.gguf}}"
export XIAOYI_LORA_MODEL_PATH="$LORA_MODEL_FILE"
LORA_ADAPTER_FILE="$PWD/artifacts/lora/xiaoyi-maritime-1.7b-r96-v3/xiaoyi-maritime-1.7b-r96-v3-f16.gguf"
if [[ "${XIAOYI_LOCAL_MODEL_PROFILE:-base}" == "lora" && -f "$LORA_ADAPTER_FILE" ]]; then
  MODEL_FILE="$LORA_MODEL_FILE"
  MODEL_ID=xiaoyi-local-1.7b-q8-0
  MODEL_ALIAS=xiaoyi-maritime-1.7b-lora
  MODEL_CONTEXT=4096
  USE_LORA=true
fi
MODEL_STARTED_HERE=false
EMBEDDING_STARTED_HERE=false

cleanup() {
  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID" 2>/dev/null || true
  fi
  if [[ "$MODEL_STARTED_HERE" == true && -n "$MODEL_PID" ]] && kill -0 "$MODEL_PID" 2>/dev/null; then
    kill "$MODEL_PID" 2>/dev/null || true
  fi
  if [[ "$EMBEDDING_STARTED_HERE" == true && -n "$EMBEDDING_PID" ]] && kill -0 "$EMBEDDING_PID" 2>/dev/null; then
    kill "$EMBEDDING_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

model_ready() {
  curl --fail --silent --max-time 2 \
    "http://127.0.0.1:${MODEL_PORT}/health" >/dev/null 2>&1
}

DISCOVERED_EMBEDDING_MODEL="$(discover_weight_by_size 639150592c)"
EMBEDDING_FILE="${XIAOYI_EMBEDDING_MODEL_PATH:-${DISCOVERED_EMBEDDING_MODEL:-$PWD/.runtime/models/maritime-embedding-0.6b-q8-0.gguf}}"
export XIAOYI_EMBEDDING_MODEL_PATH="$EMBEDDING_FILE"
EMBEDDING_PORT="${XIAOYI_EMBEDDING_PORT:-11436}"
embedding_ready() {
  curl --fail --silent --max-time 2 \
    "http://127.0.0.1:${EMBEDDING_PORT}/health" >/dev/null 2>&1
}

if [[ "$MODEL_ENABLED" != "false" && -f "$MODEL_FILE" && -n "$LLAMA_SERVER_BIN" ]]; then
  if ! "$PYTHON_BIN" scripts/local_model.py verify --quiet --model-id "$MODEL_ID"; then
    echo "本地生成模型校验失败；已保留严格证据RAG回退。" >&2
  else
    if ! model_ready; then
      mkdir -p .runtime/logs
      MODEL_SERVER_ARGS=(
        --model "$MODEL_FILE"
        --alias "$MODEL_ALIAS"
        --host 127.0.0.1
        --port "$MODEL_PORT"
        --ctx-size "${XIAOYI_LOCAL_MODEL_CONTEXT:-$MODEL_CONTEXT}"
        --threads "${XIAOYI_LOCAL_MODEL_THREADS:-8}"
        --batch-size "${XIAOYI_LOCAL_MODEL_BATCH_SIZE:-512}"
        --ubatch-size "${XIAOYI_LOCAL_MODEL_UBATCH_SIZE:-256}"
        --parallel 1
        --cache-reuse 128
        --n-gpu-layers 0
        --jinja
      )
      if [[ "$USE_LORA" == true ]]; then
        MODEL_SERVER_ARGS+=(--lora "$LORA_ADAPTER_FILE")
      fi
      "$LLAMA_SERVER_BIN" "${MODEL_SERVER_ARGS[@]}" \
        >.runtime/logs/llama-server.log 2>&1 &
      MODEL_PID=$!
      MODEL_STARTED_HERE=true
      for _ in $(seq 1 180); do
        model_ready && break
        if ! kill -0 "$MODEL_PID" 2>/dev/null; then
          echo "llama-server 启动失败，日志：.runtime/logs/llama-server.log" >&2
          MODEL_STARTED_HERE=false
          MODEL_PID=""
          break
        fi
        sleep 1
      done
    fi
    if model_ready; then
      export XIAOYI_MODEL_PROVIDER=openai_compatible
      export XIAOYI_MODEL_BASE_URL="http://127.0.0.1:${MODEL_PORT}/v1"
      export XIAOYI_MODEL_NAME="$MODEL_ALIAS"
      export XIAOYI_MODEL_TIMEOUT_SECONDS="${XIAOYI_MODEL_TIMEOUT_SECONDS:-60}"
      export XIAOYI_MODEL_MAX_RETRIES="${XIAOYI_MODEL_MAX_RETRIES:-0}"
      export XIAOYI_MODEL_MAX_TOKENS="${XIAOYI_MODEL_MAX_TOKENS:-200}"
      export XIAOYI_MINIMUM_ANSWER_REVIEW_SECONDS="${XIAOYI_MINIMUM_ANSWER_REVIEW_SECONDS:-0}"
      export XIAOYI_MODEL_EXTERNAL_DATA_ALLOWED=false
      if [[ "$USE_LORA" == true ]]; then
        export XIAOYI_MODEL_ADAPTER_ID=xiaoyi-maritime-lora-r96-v3
        echo "小懿生成层：1.7B Q8_0 + Rank 96 本机LoRA v3；证据不足时回答并在底部提醒。"
      else
        echo "小懿生成层：4B Q4_K_M（本机）；证据不足时回答并在底部提醒。"
      fi
    fi
  fi
elif [[ "$MODEL_ENABLED" == "true" ]]; then
  echo "已要求生成模型，但模型文件或 llama-server 不存在。" >&2
  echo "先运行：$PYTHON_BIN scripts/local_model.py install-runtime" >&2
  echo "再运行：$PYTHON_BIN scripts/local_model.py download" >&2
  exit 1
fi

if [[ "$MODEL_ENABLED" != "false" && -f "$EMBEDDING_FILE" && -n "$LLAMA_SERVER_BIN" ]]; then
  if "$PYTHON_BIN" scripts/local_model.py verify --quiet \
    --model-id xiaoyi-embedding-0.6b-q8-0; then
    if ! embedding_ready; then
      "$LLAMA_SERVER_BIN" \
        --model "$EMBEDDING_FILE" \
        --alias xiaoyi-embedding-0.6b \
        --host 127.0.0.1 \
        --port "$EMBEDDING_PORT" \
        --embedding \
        --pooling last \
        --ctx-size 4096 \
        --threads "${XIAOYI_LOCAL_MODEL_THREADS:-8}" \
        --batch-size 256 \
        --ubatch-size 256 \
        --n-gpu-layers 0 \
        >.runtime/logs/embedding-server.log 2>&1 &
      EMBEDDING_PID=$!
      EMBEDDING_STARTED_HERE=true
      for _ in $(seq 1 120); do
        embedding_ready && break
        if ! kill -0 "$EMBEDDING_PID" 2>/dev/null; then
          EMBEDDING_STARTED_HERE=false
          EMBEDDING_PID=""
          break
        fi
        sleep 1
      done
    fi
    if embedding_ready; then
      export XIAOYI_EMBEDDING_BASE_URL="http://127.0.0.1:${EMBEDDING_PORT}/v1"
      export XIAOYI_EMBEDDING_MODEL=xiaoyi-embedding-0.6b
      if "$PYTHON_BIN" scripts/build_vector_index.py --ensure \
        --batch-size "${XIAOYI_EMBEDDING_BATCH_SIZE:-32}"; then
        echo "小懿检索层：0.6B-Embedding 稠密向量 + Sparse/BM25 对照。"
      else
        unset XIAOYI_EMBEDDING_BASE_URL
        echo "稠密向量索引构建失败；已回退到Sparse/BM25。" >&2
      fi
    fi
  fi
fi

"$PYTHON_BIN" -m uvicorn app.main:app \
  --host "${XIAOYI_HOST:-127.0.0.1}" \
  --port "$XIAOYI_PORT" &
APP_PID=$!
wait "$APP_PID"
