# Reservation drift is never auto-remediated: the action is to exchange or
# resize via the Reservations blade, which has billing-account-scoped checks
# that don't belong in an ad-hoc bash script. This template prints a triage
# command so you can pull the data into a spreadsheet for the review meeting.

echo ">> Reservation utilization summary (last 30 days):"
az consumption reservation summary list \
  --grain monthly \
  --reservation-order-id "${RESOURCE_IDS[0]}" \
  --query "[].{Sku:skuName, AvgUtil:avgUtilizationPercentage, MinUtil:minUtilizationPercentage, ReservedHours:reservedHours, UsedHours:usedHours}" \
  -o table || echo "(install: az extension add --name consumption)"

echo ""
echo "Next step: open https://portal.azure.com/#blade/Microsoft_Azure_Reservations/ReservationsBrowseBlade"
echo "and exchange or right-size any reservation below 70% utilization."
