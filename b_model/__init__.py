"""
b_model package for Role B (ML Lead).
Peat Fire Early-Warning Agent.
"""

from b_model.config import (
    FEATURE_COLUMNS,
    HORIZONS,
    MODEL_VERSION,
    SCHEMA_VERSION,
    TARGET_COLS,
    get_risk_level,
)

__all__ = [
    "SCHEMA_VERSION",
    "MODEL_VERSION",
    "HORIZONS",
    "TARGET_COLS",
    "FEATURE_COLUMNS",
    "get_risk_level",
]

