#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Shadow Cost — generated remediation script
# Detector: __DETECTOR__
# Generated for subscription: __SUBSCRIPTION__
#
# DRY-RUN BY DEFAULT. Pass --apply to mutate state.
# Always review the affected resources below before applying.
# ----------------------------------------------------------------------------
set -euo pipefail

APPLY=false
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=true ;;
    -h|--help) echo "Usage: $0 [--apply]"; exit 0 ;;
  esac
done

if ! command -v az >/dev/null; then
  echo "az CLI is required. Install from https://aka.ms/azcli" >&2
  exit 2
fi

echo ">> Setting subscription context: __SUBSCRIPTION__"
az account set --subscription "__SUBSCRIPTION__"

echo ">> Mode: $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"
echo ">> Resources to operate on: ${#RESOURCE_IDS[@]}"
