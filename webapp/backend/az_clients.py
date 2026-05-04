"""Azure SDK client factory.

Uses :class:`DefaultAzureCredential`, which resolves in this order at runtime:

  1. EnvironmentCredential       — local dev with AZURE_CLIENT_ID / SECRET / TENANT
  2. ManagedIdentityCredential   — App Service's system-assigned MI (production)
  3. AzureCliCredential          — `az login` on the developer's laptop

That means the same code works locally (via `az login`) and in App Service
(via Managed Identity) with no code changes.
"""
from __future__ import annotations

from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.mgmt.consumption import ConsumptionManagementClient
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.resource import SubscriptionClient
from azure.mgmt.resourcegraph import ResourceGraphClient

from .config import settings


@lru_cache(maxsize=1)
def credential() -> DefaultAzureCredential:
    # exclude_interactive_browser_credential keeps the App Service flow snappy;
    # local devs should use `az login` rather than browser popups.
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


@lru_cache(maxsize=1)
def resource_graph() -> ResourceGraphClient:
    return ResourceGraphClient(credential())


@lru_cache(maxsize=1)
def subscriptions() -> SubscriptionClient:
    return SubscriptionClient(credential())


@lru_cache(maxsize=1)
def cost_management() -> CostManagementClient:
    return CostManagementClient(credential())


@lru_cache(maxsize=1)
def consumption() -> ConsumptionManagementClient:
    return ConsumptionManagementClient(credential(), settings().target_subscription_id)


@lru_cache(maxsize=1)
def monitor() -> MonitorManagementClient:
    return MonitorManagementClient(credential(), settings().target_subscription_id)
