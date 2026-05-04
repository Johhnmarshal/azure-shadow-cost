// ----------------------------------------------------------------------------
// Shadow Cost — v1 infrastructure
// Deploys: Linux App Service Plan + App Service (Python 3.11) with a
// system-assigned managed identity. Role assignments at subscription scope
// are applied in role-assignments.bicep (separate scope).
// ----------------------------------------------------------------------------
targetScope = 'resourceGroup'

@description('Base name used for App Service + Plan. Lowercase, 3-24 chars.')
@minLength(3)
@maxLength(24)
param appName string = 'shadowcost'

@description('Azure region for the App Service Plan + App.')
param location string = resourceGroup().location

@description('App Service Plan SKU. B1 is the cheapest always-on tier; F1 free tier sleeps and breaks long-running detectors.')
@allowed(['B1','B2','P0v3','P1v3'])
param skuName string = 'B1'

@description('Subscription ID the app should target for shadow-cost detection.')
param targetSubscriptionId string = subscription().subscriptionId

@description('Comma-separated mandatory tag keys. Drives the Visibility Gap calc.')
param requiredTags string = 'Owner,CostCenter,Environment,Application'

var planName = '${appName}-plan'
var siteName = '${appName}-${uniqueString(resourceGroup().id)}'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  sku: { name: skuName, tier: skuName == 'B1' || skuName == 'B2' ? 'Basic' : 'PremiumV3' }
  kind: 'linux'
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: siteName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      alwaysOn: skuName != 'F1'
      appCommandLine: 'gunicorn -w 2 -k uvicorn.workers.UvicornWorker backend.app:app --chdir /home/site/wwwroot --bind 0.0.0.0:8000 --timeout 120'
      appSettings: [
        { name: 'TARGET_SUBSCRIPTION_ID',       value: targetSubscriptionId }
        { name: 'REQUIRED_TAGS',                value: requiredTags }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITES_PORT',                value: '8000' }
        { name: 'PYTHON_ENABLE_GUNICORN_MULTIWORKERS', value: 'true' }
      ]
    }
  }
}

output siteName string = site.name
output siteHostname string = site.properties.defaultHostName
output principalId string = site.identity.principalId
