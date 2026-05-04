// ----------------------------------------------------------------------------
// Grants the App Service's system-assigned managed identity the minimum roles
// it needs at SUBSCRIPTION scope:
//   - Reader                   — Resource Graph inventory queries
//   - Cost Management Reader   — Cost Management / Consumption API
// Optional (uncomment if you want commitment-drift to work end-to-end):
//   - Reservations Reader at the *billing* scope (separate deployment, not here)
// ----------------------------------------------------------------------------
targetScope = 'subscription'

@description('Object (principal) ID of the App Service managed identity. Output of main.bicep.')
param principalId string

// Built-in role definition IDs
var readerRoleId             = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var costManagementReaderId   = '72fafb9e-0641-4937-9268-a91bfd8191a3'

resource readerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, principalId, readerRoleId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
  }
}

resource costAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, principalId, costManagementReaderId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', costManagementReaderId)
  }
}
