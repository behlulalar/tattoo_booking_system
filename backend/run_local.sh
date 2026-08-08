#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

export FLASK_ENV=development
export FLASK_DEBUG=1

python3 app.py

