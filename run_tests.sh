#!/bin/sh
# Offline unit tests, then the gateway integration test (needs gg, see README).
set -eu
cd "$(dirname "$0")"
python3 agent/test_unit.py
python3 agent/test_agent.py
