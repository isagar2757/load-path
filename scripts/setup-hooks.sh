#!/usr/bin/env bash
# Run once per clone.
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/*
echo "hooks active: $(git config core.hooksPath)"
