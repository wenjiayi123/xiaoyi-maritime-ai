#!/bin/bash
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -u scripts/start_agent_rl_v1.py "$@"
