#!/usr/bin/env bash
set -euo pipefail
python3 -m venv "$HOME/policy-env"
"$HOME/policy-env/bin/python" -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.5.1+cpu'
"$HOME/policy-env/bin/python" -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r /opt/xiaoyi/runtime/requirements.txt /opt/xiaoyi/upstream/routefinder /opt/xiaoyi/upstream/parco
"$HOME/policy-env/bin/python" -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r /opt/xiaoyi/runtime/requirements.lock.txt
"$HOME/policy-env/bin/python" -m pip check
"$HOME/policy-env/bin/python" -m pip freeze > "$HOME/policy-runtime-freeze.txt"
"$HOME/policy-env/bin/python" -c 'import torch,torchrl,tensordict,routefinder,parco; print("OFFICIAL_POLICY_RUNTIME_IMPORTS_OK",torch.__version__,torchrl.__version__,tensordict.__version__)'
