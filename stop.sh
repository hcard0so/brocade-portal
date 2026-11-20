#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -f logs/portal.pid ] && kill "$(cat logs/portal.pid)" 2>/dev/null && echo "portal parado"
rm -f logs/portal.pid
