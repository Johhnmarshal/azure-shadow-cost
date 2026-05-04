# Release unattached Standard public IPs. Re-checks ipConfiguration before
# deleting to avoid releasing one that was claimed in the meantime.

for ID in "${RESOURCE_IDS[@]}"; do
  IPCFG=$(az network public-ip show --ids "$ID" --query "ipConfiguration.id" -o tsv 2>/dev/null || echo "")
  if [ -n "$IPCFG" ]; then
    echo "  SKIP: $ID (now attached: $IPCFG)"
    continue
  fi
  if [ "$APPLY" = true ]; then
    az network public-ip delete --ids "$ID" -o none && echo "  DELETED: $ID"
  else
    echo "  WOULD DELETE: $ID"
  fi
done
