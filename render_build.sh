#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Create data directory for persistent SQLite
mkdir -p /opt/render/project/src/data