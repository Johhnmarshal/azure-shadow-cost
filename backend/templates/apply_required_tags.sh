# Apply default values for required tags to resources missing them.
# Intentionally non-destructive: we never overwrite existing tag values, only
# fill gaps. Defaults are a "needs-attribution" sentinel so untagged spend
# remains visible in chargeback reports but doesn't fail policy on creation.

DEFAULTS=(
  "Owner=needs-attribution@your-org.example"
  "CostCenter=NEEDS-ATTRIBUTION"
  "Environment=unknown"
  "Application=unknown"
)

for ID in "${RESOURCE_IDS[@]}"; do
  CURRENT=$(az resource show --ids "$ID" --query "tags" -o json 2>/dev/null || echo "{}")
  ARGS=()
  for KV in "${DEFAULTS[@]}"; do
    KEY="${KV%%=*}"
    if ! echo "$CURRENT" | grep -q "\"$KEY\""; then
      ARGS+=("$KV")
    fi
  done
  if [ ${#ARGS[@]} -eq 0 ]; then
    echo "  SKIP: $ID (already has all required tags)"
    continue
  fi
  if [ "$APPLY" = true ]; then
    az tag update --resource-id "$ID" --operation merge --tags "${ARGS[@]}" -o none \
      && echo "  TAGGED: $ID (${ARGS[*]})"
  else
    echo "  WOULD TAG: $ID with ${ARGS[*]}"
  fi
done
