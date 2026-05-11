"""Azure Workbook JSON template generators (PR5).

Three Workbooks ship out of the box:

* ``hidden-waste``      — leaderboard + per-category bars + top-25 offenders.
* ``peak-rightsizing``  — VM inventory + advisor-unsafe filter + metrics.
* ``ri-coverage``       — coverage gap by family×region + buffer-exposure tracker.

Workbooks read from a Log Analytics custom table (``HiddenWaste_CL``,
``PeakRightsizing_CL``, ``RICoverage_CL``) populated by the operator's
ingestion pipeline. The web app emits the JSON; how the data lands in the
workspace is the operator's call (Diagnostic Settings export from the API,
Logic App, etc.).

Each generator returns a dict shaped per the Application-Insights-Workbooks
schema. The /api/workbooks endpoints in app.py serialise to JSON for the
SPA's download links.
"""
from __future__ import annotations


def _md_item(name: str, markdown: str) -> dict:
    return {"type": 1, "name": name, "content": {"json": markdown}}


def _kql_table(name: str, query: str, workspace_resource: bool = True) -> dict:
    item: dict = {
        "type": 3,
        "name": name,
        "content": {
            "version": "KqlItem/1.0",
            "query": query,
            "size": 0,
            "queryType": 0,
            "visualization": "table",
        },
    }
    if workspace_resource:
        item["content"]["resourceType"] = "microsoft.operationalinsights/workspaces"
    return item


def _bar_chart(name: str, query: str) -> dict:
    return {
        "type": 3,
        "name": name,
        "content": {
            "version": "KqlItem/1.0",
            "query": query,
            "size": 0,
            "queryType": 0,
            "resourceType": "microsoft.operationalinsights/workspaces",
            "visualization": "barchart",
        },
    }


def _workspace_param() -> dict:
    return {
        "type": 9,
        "name": "params",
        "content": {
            "version": "KqlParameterItem/1.0",
            "parameters": [{
                "id": "p_workspace",
                "version": "KqlParameterItem/1.0",
                "name": "Workspace",
                "type": 5,
                "isRequired": True,
                "typeSettings": {
                    "resourceTypeFilter": {"microsoft.operationalinsights/workspaces": True},
                },
            }],
        },
    }


def hidden_waste_workbook() -> dict:
    return {
        "version": "Notebook/1.0",
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
        "items": [
            _md_item("title",
                "# Azure Shadow Cost — Hidden Waste\n\nSeven recurring waste classes that Advisor "
                "under-reports or misses, priced from Cost Management actuals. Source: Azure Shadow Cost "
                "(CSV uploaded as Log Analytics custom table `HiddenWaste_CL`)."),
            _workspace_param(),
            _md_item("section_headline", "## Headline\n\nMonthly recoverable across all categories."),
            _kql_table("headline",
                "HiddenWaste_CL\n"
                "| where TimeGenerated > ago(7d)\n"
                "| summarize Findings=count(), MonthlyGBP=sum(monthly_gbp_d)\n"
                "| extend AnnualisedGBP = MonthlyGBP * 12"),
            _md_item("section_category", "## By category"),
            _bar_chart("category_chart",
                "HiddenWaste_CL\n"
                "| where TimeGenerated > ago(7d)\n"
                "| summarize MonthlyGBP=sum(monthly_gbp_d) by Category=category_s\n"
                "| order by MonthlyGBP desc"),
            _md_item("section_offenders", "## Top 25 individual offenders"),
            _kql_table("offenders_table",
                "HiddenWaste_CL\n"
                "| where TimeGenerated > ago(7d)\n"
                "| top 25 by monthly_gbp_d desc\n"
                "| project Sub=sub_name_s, ResourceGroup=resource_group_s, Resource=name_s, "
                "Category=category_s, MonthlyGBP=monthly_gbp_d, Source=cost_source_s"),
            _md_item("footer",
                "---\n\n_Source: Azure Shadow Cost — `webapp/backend/`. The web app exports this "
                "workbook on demand via /api/workbooks/hidden-waste.json._"),
        ],
        "fallbackResourceIds": [],
        "fromTemplateId": "azshc-hidden-waste",
    }


def peak_rightsizing_workbook() -> dict:
    return {
        "version": "Notebook/1.0",
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
        "items": [
            _md_item("title",
                "# Azure Shadow Cost — Peak-Aware Rightsizing\n\nWorkload-aware (P95 / P99) rightsizing "
                "dashboard for the FinOps team. Replaces Advisor's average-based logic for spiky / batch "
                "workloads."),
            _workspace_param(),
            _md_item("section_inventory", "## VM inventory + decision class"),
            {
                "type": 3, "name": "vm_inventory",
                "content": {
                    "version": "KqlItem/1.0",
                    "query": (
                        "Resources\n"
                        "| where type =~ 'microsoft.compute/virtualmachines'\n"
                        "| where resourceGroup !startswith 'databricks-rg-' and resourceGroup !startswith 'mc_'\n"
                        "| where name !startswith 'aks-'\n"
                        "| extend size = tostring(properties.hardwareProfile.vmSize)\n"
                        "| project subscriptionId, resourceGroup, name, location, size\n"
                        "| order by name asc"
                    ),
                    "size": 1,
                    "queryType": 1,
                    "resourceType": "microsoft.resourcegraph/resources",
                },
            },
            _md_item("section_advisor",
                "## Advisor-unsafe diff\n\nRows where Advisor recommended a downsize but the engine "
                "flagged the workload as KEEP or UPSIZE_WARNING at P95. This is the headline metric."),
            _kql_table("advisor_unsafe",
                "PeakRightsizing_CL\n"
                "| where TimeGenerated > ago(7d)\n"
                "| where advisor_unsafe_b == true\n"
                "| project Sub=sub_name_s, VM=name_s, Size=size_s, "
                "CpuP95=cpu_p95_d, CpuP99=cpu_p99_d, MemP95=mem_p95_used_d, Verdict=verdict_s"),
            _md_item("footer",
                "---\n\n_Source: Azure Shadow Cost — `webapp/backend/peak_rightsizing.py`._"),
        ],
        "fallbackResourceIds": [],
        "fromTemplateId": "azshc-peak-rightsizing",
    }


def ri_coverage_workbook() -> dict:
    return {
        "version": "Notebook/1.0",
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
        "items": [
            _md_item("title",
                "# Azure Shadow Cost — RI / Savings-Plan Coverage\n\nWorkload-aware coverage map for "
                "Reservations and Compute Savings Plans across your Azure tenant. Source: `RICoverage_CL`."),
            _workspace_param(),
            _md_item("section_gap", "## Coverage gap by family × region\n\nBars are annual PAYG — biggest opportunities absent the buffer constraint."),
            _bar_chart("coverage_chart",
                "RICoverage_CL\n"
                "| where TimeGenerated > ago(7d)\n"
                "| summarize annual_payg=sum(annual_payg_gbp_d) by family_s, location_s\n"
                "| top 25 by annual_payg desc"),
            _md_item("section_buffer", "## Refund-buffer exposure tracker\n\nCumulative cancellation exposure of accepted picks against the configured buffer."),
            _kql_table("buffer_tracker",
                "RICoverage_CL\n"
                "| where TimeGenerated > ago(7d)\n"
                "| where shortlisted_b == true\n"
                "| order by annual_savings_gbp_d desc\n"
                "| extend cumulative_exposure = row_cumsum(cancellation_exposure_gbp_d)\n"
                "| project Family=family_s, Region=location_s, Product=recommended_product_s, "
                "AnnualCommit=annual_commit_gbp_d, AnnualSavings=annual_savings_gbp_d, "
                "CancelExposure=cancellation_exposure_gbp_d, CumExposure=cumulative_exposure"),
            _md_item("footer",
                "---\n\n_Source: Azure Shadow Cost — `webapp/backend/ri_coverage.py`. Refund buffer "
                "is the operator-set procurement cap (no default). Cross-check against Peak Rightsizing "
                "before any commitment._"),
        ],
        "fallbackResourceIds": [],
        "fromTemplateId": "azshc-ri-coverage",
    }


def all_workbooks() -> dict[str, dict]:
    return {
        "hidden-waste":      hidden_waste_workbook(),
        "peak-rightsizing":  peak_rightsizing_workbook(),
        "ri-coverage":       ri_coverage_workbook(),
    }
