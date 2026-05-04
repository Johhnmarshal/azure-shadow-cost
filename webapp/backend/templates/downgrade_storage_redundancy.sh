# Downgrade non-prod storage accounts from GRS/GZRS to LRS.
# This is a metadata change — no data movement — but it is irreversible
# without recreating the account, so we double-check the Environment tag.

for ID in "${RESOURCE_IDS[@]}"; do
  ENV=$(az resource show --ids "$ID" --query "tags.Environment" -o tsv 2>/dev/null | tr '[:upper:]' '[:lower:]')
  case "$ENV" in
    dev|development|test|qa|staging|sandbox|nonprod|non-prod) ;;
    *) echo "  SKIP: $ID (Environment=$ENV — refusing to downgrade non-nonprod)"; continue ;;
  esac
  if [ "$APPLY" = true ]; then
    az storage account update --ids "$ID" --sku Standard_LRS -o none \
      && echo "  DOWNGRADED to Standard_LRS: $ID"
  else
    echo "  WOULD DOWNGRADE to Standard_LRS: $ID"
  fi
done
