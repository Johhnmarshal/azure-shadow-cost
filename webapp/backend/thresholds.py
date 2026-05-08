"""Peak-rightsizing thresholds: env-var defaults + in-memory override.

Thread-safe. ``current()`` is the hot read path — every detector call reads
from it. ``update()`` is invoked by the SPA settings panel via the
``POST /api/settings`` endpoint, validates, and atomically replaces the
in-memory state.

State is **process-local**. Restarting the App Service resets to env-var
defaults. PR-after-5 will add Cosmos persistence so settings survive
restarts; for now it's deliberately ephemeral so an operator can experiment
freely without polluting prod.
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Thresholds:
    """The seven knobs that drive the peak-rightsizing decision tree.

    All percentages are 0–100. ``min_data_coverage`` is 0–1.

    Defaults are the *Conservative* profile from the FinOps Engine README —
    safe for spiky / batch workloads. Operators typically loosen them only
    after several nightly cycles validate the output.
    """
    downsize_cpu_p95_max:     float = 40.0
    downsize_mem_p95_max:     float = 50.0
    downsize_cpu_p99_high_conf: float = 50.0
    downsize_mem_p99_high_conf: float = 60.0
    upsize_cpu_p95_min:       float = 80.0
    upsize_mem_p95_min:       float = 85.0
    min_data_coverage:        float = 0.80


_DEFAULTS: dict[str, tuple[str, float]] = {
    "downsize_cpu_p95_max":       ("AZSHC_T_DS_CPU_P95", 40.0),
    "downsize_mem_p95_max":       ("AZSHC_T_DS_MEM_P95", 50.0),
    "downsize_cpu_p99_high_conf": ("AZSHC_T_DS_CPU_P99", 50.0),
    "downsize_mem_p99_high_conf": ("AZSHC_T_DS_MEM_P99", 60.0),
    "upsize_cpu_p95_min":         ("AZSHC_T_US_CPU_P95", 80.0),
    "upsize_mem_p95_min":         ("AZSHC_T_US_MEM_P95", 85.0),
    "min_data_coverage":          ("AZSHC_T_MIN_COV",     0.80),
}


def _from_env() -> Thresholds:
    out: dict[str, float] = {}
    for field_name, (env_key, default) in _DEFAULTS.items():
        try:
            out[field_name] = float(os.environ.get(env_key, default))
        except ValueError:
            out[field_name] = default
    return Thresholds(**out)


_lock = threading.Lock()
_state: Thresholds = _from_env()


def current() -> Thresholds:
    with _lock:
        return _state


def validate(t: Thresholds) -> str | None:
    """Return None if valid; otherwise a human-readable error message."""
    if not (0 < t.min_data_coverage <= 1):
        return "min_data_coverage must be in (0, 1]"
    for fname, value in asdict(t).items():
        if fname == "min_data_coverage":
            continue
        if not (0 <= float(value) <= 100):
            return f"{fname} must be in [0, 100]"
    if t.downsize_cpu_p95_max >= t.upsize_cpu_p95_min:
        return "downsize_cpu_p95_max must be strictly less than upsize_cpu_p95_min"
    if t.downsize_mem_p95_max >= t.upsize_mem_p95_min:
        return "downsize_mem_p95_max must be strictly less than upsize_mem_p95_min"
    return None


def update(**fields: float) -> Thresholds:
    """Atomically replace specified fields. Raises ValueError on invalid input."""
    global _state
    with _lock:
        candidate = replace(_state, **fields)
        err = validate(candidate)
        if err:
            raise ValueError(err)
        _state = candidate
        return _state


def reset_to_env() -> Thresholds:
    """Re-read env vars and reset state. Used by tests."""
    global _state
    with _lock:
        _state = _from_env()
        return _state


def to_dict(t: Thresholds | None = None) -> dict[str, float]:
    return asdict(t or current())
