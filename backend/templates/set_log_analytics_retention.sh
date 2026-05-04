# Cap Log Analytics retention at 90 days (hot tier) and route the surplus to
# the Archive tier. Adjust HOT_DAYS to match your compliance baseline.

HOT_DAYS=90

for ID in "${RESOURCE_IDS[@]}"; do
  CURRENT=$(az monitor log-analytics workspace show --ids "$ID" --query "retentionInDays" -o tsv 2>/dev/null || echo "?")
  if [ "$CURRENT" = "?" ] || [ "$CURRENT" -le "$HOT_DAYS" ]; then
    echo "  SKIP: $ID (retention=$CURRENT)"
    continue
  fi
  if [ "$APPLY" = true ]; then
    az monitor log-analytics workspace update --ids "$ID" --retention-time "$HOT_DAYS" -o none \
      && echo "  RETENTION SET ${HOT_DAYS}d: $ID (was $CURRENT)"
  else
    echo "  WOULD SET ${HOT_DAYS}d retention on: $ID (currently $CURRENT)"
  fi
done
