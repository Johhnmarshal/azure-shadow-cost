# Delete unattached managed disks. Snapshots are NOT taken — confirm none of
# these disks are in your retention scope before applying.

for ID in "${RESOURCE_IDS[@]}"; do
  STATE=$(az disk show --ids "$ID" --query "diskState" -o tsv 2>/dev/null || echo "missing")
  if [ "$STATE" != "Unattached" ]; then
    echo "  SKIP: $ID (state=$STATE)"
    continue
  fi
  if [ "$APPLY" = true ]; then
    az disk delete --ids "$ID" --yes -o none && echo "  DELETED: $ID"
  else
    echo "  WOULD DELETE: $ID"
  fi
done
