#!/usr/bin/env bash
set -euo pipefail

# This file is installed root-owned outside the runtime-writable source tree.
# Only stock governors are allowed; no frequency/voltage overrides.
if [[ "$#" -ne 1 ]] || [[ "$1" != performance && "$1" != powersave && "$1" != ondemand ]]; then
  echo "Usage: instantlink-bridge-cpu-mode performance|powersave|ondemand" >&2
  exit 2
fi

shopt -s nullglob
policies=(/sys/devices/system/cpu/cpufreq/policy*)
if [[ "${#policies[@]}" -eq 0 ]]; then
  echo "CPU frequency policy unavailable" >&2
  exit 1
fi
for policy in "${policies[@]}"; do
  read -r available < "${policy}/scaling_available_governors"
  if [[ " ${available} " != *" $1 "* ]]; then
    echo "Requested CPU governor unavailable" >&2
    exit 1
  fi
done
for policy in "${policies[@]}"; do
  printf '%s\n' "$1" > "${policy}/scaling_governor"
done
