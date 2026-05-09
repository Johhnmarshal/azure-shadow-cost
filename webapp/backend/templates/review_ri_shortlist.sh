# RI / Savings-Plan shortlist review.
#
# Reservation purchases are billing-account-scoped and have human gates that
# don't belong in an ad-hoc bash script. This template prints the analysis
# so you can paste it into the procurement review meeting, then walks you
# to the Azure Portal Reservations blade where the actual commitment is made.

echo ">> Shortlist (priced from Cost Management actuals):"
echo ""
printf '   %-32s  %-12s\n' "FAMILY × REGION" "STATUS"
printf '   %-32s  %-12s\n' "--------------------------------" "------------"
for entry in "${RESOURCE_IDS[@]}"; do
  FAMILY="${entry%|*}"
  REGION="${entry##*|}"
  printf '   %-32s  (review in portal)\n' "$FAMILY / $REGION"
done

echo ""
echo "Next step: open the Azure Portal Reservations blade and confirm per-SKU"
echo "savings before committing."
echo "  https://portal.azure.com/#blade/Microsoft_Azure_Reservations/ReservationsBrowseBlade"
echo ""
echo "Cross-check each pick against the Peak Rightsizing tab — never reserve"
echo "a family×region that should be downsized first (locks in current"
echo "inefficiency for 1-3 years)."
