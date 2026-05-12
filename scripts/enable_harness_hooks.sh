#!/usr/bin/env bash
set -euo pipefail

git config core.hooksPath .githooks
echo "HARNESS hooks enabled: .githooks"
