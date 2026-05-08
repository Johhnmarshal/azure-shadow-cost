"""VM SKU → memory lookup table + downsize ladder.

Hardcoded from public Azure VM-size tables. Covers the most common families
(B / Dsv3-v5 / Dasv4-v5 / Esv3-v5 / Easv5 / Fsv2). Unmapped SKUs cause the
detector to fall back to ``INSUFFICIENT_DATA`` rather than guess — extend
this table when your tenant uses a family we don't list.

The ``DOWNSIZE_LADDER`` is the *only* place an explicit target SKU is
proposed. If the current size has no entry, the detector still emits
``DOWNSIZE_CANDIDATE`` but leaves ``proposed_size`` blank for human review.
"""
from __future__ import annotations


# Memory in GB per SKU. Keep the file alphabetised within each family.
SKU_MEMORY_GB: dict[str, float] = {
    # B-series (burstable)
    "Standard_B1s": 1.0,    "Standard_B1ms": 2.0,
    "Standard_B2s": 4.0,    "Standard_B2ms": 8.0,
    "Standard_B4ms": 16.0,  "Standard_B8ms": 32.0,
    "Standard_B12ms": 48.0, "Standard_B16ms": 64.0,  "Standard_B20ms": 80.0,

    # Dsv3 / Dsv4 — general purpose
    "Standard_D2s_v3": 8.0,  "Standard_D4s_v3": 16.0,
    "Standard_D8s_v3": 32.0, "Standard_D16s_v3": 64.0, "Standard_D32s_v3": 128.0,

    # Dasv4 — AMD general purpose
    "Standard_D2as_v4": 8.0,  "Standard_D4as_v4": 16.0,
    "Standard_D8as_v4": 32.0, "Standard_D16as_v4": 64.0, "Standard_D32as_v4": 128.0,

    # Dsv5 / Dasv5 / Ddsv5
    "Standard_D2s_v5": 8.0,   "Standard_D4s_v5": 16.0,
    "Standard_D8s_v5": 32.0,  "Standard_D16s_v5": 64.0, "Standard_D32s_v5": 128.0,
    "Standard_D2as_v5": 8.0,  "Standard_D4as_v5": 16.0,
    "Standard_D8as_v5": 32.0, "Standard_D16as_v5": 64.0, "Standard_D32as_v5": 128.0,
    "Standard_D2ds_v5": 8.0,  "Standard_D4ds_v5": 16.0,
    "Standard_D8ds_v5": 32.0, "Standard_D16ds_v5": 64.0, "Standard_D32ds_v5": 128.0,

    # Esv3 / Esv5 / Edsv5 / Easv5 — memory optimised
    "Standard_E2s_v3": 16.0,  "Standard_E4s_v3": 32.0,
    "Standard_E8s_v3": 64.0,  "Standard_E16s_v3": 128.0, "Standard_E32s_v3": 256.0,
    "Standard_E2s_v5": 16.0,  "Standard_E4s_v5": 32.0,
    "Standard_E8s_v5": 64.0,  "Standard_E16s_v5": 128.0, "Standard_E32s_v5": 256.0,
    "Standard_E2ds_v5": 16.0, "Standard_E4ds_v5": 32.0,
    "Standard_E8ds_v5": 64.0, "Standard_E16ds_v5": 128.0, "Standard_E32ds_v5": 256.0,
    "Standard_E2as_v5": 16.0, "Standard_E4as_v5": 32.0,
    "Standard_E8as_v5": 64.0, "Standard_E16as_v5": 128.0, "Standard_E32as_v5": 256.0,

    # Fsv2 — compute optimised
    "Standard_F2s_v2": 4.0,   "Standard_F4s_v2": 8.0,
    "Standard_F8s_v2": 16.0,  "Standard_F16s_v2": 32.0, "Standard_F32s_v2": 64.0,
}


# Each entry: current → one-step-smaller within the same family. The detector
# walks one step only; chaining downsizes is a multi-cycle decision so we
# refuse to skip steps automatically.
DOWNSIZE_LADDER: dict[str, str] = {
    # B-series
    "Standard_B20ms": "Standard_B16ms", "Standard_B16ms": "Standard_B12ms",
    "Standard_B12ms": "Standard_B8ms",  "Standard_B8ms":  "Standard_B4ms",
    "Standard_B4ms":  "Standard_B2ms",  "Standard_B2ms":  "Standard_B1ms",

    # Dsv3 / Dsv5
    "Standard_D32s_v3": "Standard_D16s_v3", "Standard_D16s_v3": "Standard_D8s_v3",
    "Standard_D8s_v3":  "Standard_D4s_v3",  "Standard_D4s_v3":  "Standard_D2s_v3",
    "Standard_D32s_v5": "Standard_D16s_v5", "Standard_D16s_v5": "Standard_D8s_v5",
    "Standard_D8s_v5":  "Standard_D4s_v5",  "Standard_D4s_v5":  "Standard_D2s_v5",

    # Dasv5
    "Standard_D32as_v5": "Standard_D16as_v5", "Standard_D16as_v5": "Standard_D8as_v5",
    "Standard_D8as_v5":  "Standard_D4as_v5",  "Standard_D4as_v5":  "Standard_D2as_v5",

    # Esv5 / Edsv5
    "Standard_E32s_v5": "Standard_E16s_v5", "Standard_E16s_v5": "Standard_E8s_v5",
    "Standard_E8s_v5":  "Standard_E4s_v5",  "Standard_E4s_v5":  "Standard_E2s_v5",
    "Standard_E32ds_v5":"Standard_E16ds_v5","Standard_E16ds_v5":"Standard_E8ds_v5",
    "Standard_E8ds_v5": "Standard_E4ds_v5", "Standard_E4ds_v5": "Standard_E2ds_v5",

    # Fsv2
    "Standard_F32s_v2": "Standard_F16s_v2", "Standard_F16s_v2": "Standard_F8s_v2",
    "Standard_F8s_v2":  "Standard_F4s_v2",  "Standard_F4s_v2":  "Standard_F2s_v2",
}


def memory_gb(sku: str) -> float | None:
    """Memory in GB for a known SKU. Returns None if not in the table."""
    return SKU_MEMORY_GB.get(sku)


def proposed_downsize(sku: str) -> str | None:
    """One-step-smaller SKU within the same family, or None."""
    return DOWNSIZE_LADDER.get(sku)
