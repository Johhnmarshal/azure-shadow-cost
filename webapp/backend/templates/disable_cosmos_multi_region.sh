# Disable multi-region writes on non-prod Cosmos DB accounts. Single-region
# write is sufficient for ephemeral environments and removes the multi-write
# RU surcharge.

for ID in "${RESOURCE_IDS[@]}"; do
  ENV=$(az resource show --ids "$ID" --query "tags.Environment" -o tsv 2>/dev/null | tr '[:upper:]' '[:lower:]')
  case "$ENV" in
    dev|development|test|qa|staging|sandbox|nonprod|non-prod) ;;
    *) echo "  SKIP: $ID (Environment=$ENV)"; continue ;;
  esac
  if [ "$APPLY" = true ]; then
    az cosmosdb update --ids "$ID" --enable-multiple-write-locations false -o none \
      && echo "  MULTI-WRITE DISABLED: $ID"
  else
    echo "  WOULD DISABLE multi-write on: $ID"
  fi
done
