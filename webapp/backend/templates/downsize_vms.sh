# Resize VMs to a smaller SKU. RESOURCE_IDS entries are "vmId|targetSku".
# We re-check the current size at apply time so a manual change in the
# meantime doesn't get clobbered.

declare -a IDS=()
declare -a SKUS=()
for entry in "${RESOURCE_IDS[@]}"; do
  IDS+=("${entry%|*}")
  SKUS+=("${entry##*|}")
done

for i in "${!IDS[@]}"; do
  ID="${IDS[$i]}"
  TARGET_SKU="${SKUS[$i]}"
  CURRENT_SKU=$(az vm show --ids "$ID" --query "hardwareProfile.vmSize" -o tsv 2>/dev/null || echo "")
  if [ -z "$CURRENT_SKU" ]; then
    echo "  SKIP: $ID (not found)"
    continue
  fi
  if [ "$CURRENT_SKU" = "$TARGET_SKU" ]; then
    echo "  SKIP: $ID (already $TARGET_SKU)"
    continue
  fi
  if [ "$APPLY" = true ]; then
    az vm resize --ids "$ID" --size "$TARGET_SKU" -o none \
      && echo "  RESIZED: $ID  $CURRENT_SKU -> $TARGET_SKU"
  else
    echo "  WOULD RESIZE: $ID  $CURRENT_SKU -> $TARGET_SKU"
  fi
done

echo ""
echo "Note: resize triggers a reboot. Run during a maintenance window or"
echo "      coordinate with the workload owner first."
