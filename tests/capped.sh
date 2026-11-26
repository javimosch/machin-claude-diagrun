#!/bin/sh
# Run a command in its own cgroup: hard memory cap, no swap, time limit.
exec systemd-run --user --scope -q -p MemoryMax="${CAP:-1G}" -p MemorySwapMax=0 timeout "${LIMIT:-60}" "$@"
