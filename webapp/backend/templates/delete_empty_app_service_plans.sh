# Delete App Service Plans that still have zero hosted apps at apply time.

for ID in "${RESOURCE_IDS[@]}"; do
  SITES=$(az appservice plan show --ids "$ID" --query "numberOfSites" -o tsv 2>/dev/null || echo "?")
  if [ "$SITES" != "0" ]; then
    echo "  SKIP: $ID (sites=$SITES)"
    continue
  fi
  if [ "$APPLY" = true ]; then
    az appservice plan delete --ids "$ID" --yes -o none && echo "  DELETED: $ID"
  else
    echo "  WOULD DELETE: $ID"
  fi
done
