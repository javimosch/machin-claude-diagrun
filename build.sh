#!/bin/sh
# Compose the vendored JSON framework with src/ and compile one binary.
set -eu
cd "$(dirname "$0")"
mkdir -p bin
machin encode vendor/json.src src/pricing.src src/load.src src/trigger.src src/cache.src src/analyze.src src/render.src src/main.src > bin/diagrun.mfl
machin build bin/diagrun.mfl -o bin/diagrun
