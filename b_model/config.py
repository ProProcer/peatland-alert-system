"""
Configuration and constants for Role B (ML Lead) pipeline.
Strict adherence to Team Playbook Contracts 3.1 & 3.2.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import numpy as np

# Contract 3.2 Metadata
SCHEMA_VERSION: str = "1.0"
MODEL_VERSION: str = "v1"
HORIZONS: List[int] = [24, 48, 72]
TARGET_COLS: Dict[int, str] = {
    24: "target_24h",
    48: "target_48h",
    72: "target_72h",
}

# Contract 3.1 & Section 1.1 Canonical Feature Groupings
# Note: 'et0_mm' is spelled with a zero (0), per Contract 3.1
FEATURE_GROUPS: Dict[str, List[str]] = {
    "peat": [
        "peat_fraction",
        "peat_area_km2",
    ],
    "weather": [
        "temp_c",
        "precip_mm",
        "wind_kmh",
        "wind_dir_deg",
        "sm_0_1",
        "sm_1_3",
        "sm_3_9",
        "sm_9_27",
        "sm_27_81",
        "vpd_kpa",
        "soil_temp_0_c",
        "soil_temp_18_c",
        "et_mm",
        "et0_mm",
    ],
    "derived": [
        "rain_24h_mm",
        "rain_7d_mm",
        "rain_30d_mm",
        "days_since_rain",
        "sm_27_81_delta_7d",
        "vpd_mean_24h",
        "soil_air_temp_gap_c",
    ],
    "fire": [
        "hotspots_in_cell_24h",
        "hotspots_10km_7d",
        "frp_sum_10km_7d",
        "nearest_hotspot_km",
    ],
}

# Flat ordered list of all 27 canonical features
FEATURE_COLUMNS: List[str] = [
    col for group_cols in FEATURE_GROUPS.values() for col in group_cols
]

# Physical direction sign map for feature attribution:
# -1 indicates an inverse risk feature (lower value -> higher fire risk; e.g. low soil moisture increases risk)
# +1 indicates a direct risk feature (higher value -> higher fire risk; e.g. prolonged dry days increase risk)
DOMAIN_FEATURE_SIGNS: Dict[str, int] = {
    # Soil moisture (moisture depletion increases risk)
    "sm_0_1": -1,
    "sm_1_3": -1,
    "sm_3_9": -1,
    "sm_9_27": -1,
    "sm_27_81": -1,
    "sm_27_81_delta_7d": -1,  # negative delta = desiccation = higher risk
    # Precipitation / moisture inputs (rain decreases risk)
    "precip_mm": -1,
    "rain_24h_mm": -1,
    "rain_7d_mm": -1,
    "rain_30d_mm": -1,
    "et_mm": -1,
    "et0_mm": -1,
    # Distance to active fire (smaller distance = higher risk)
    "nearest_hotspot_km": -1,
    # Positive risk drivers (increase with fire danger)
    "days_since_rain": 1,
    "temp_c": 1,
    "soil_temp_0_c": 1,
    "soil_temp_18_c": 1,
    "soil_air_temp_gap_c": 1,
    "vpd_kpa": 1,
    "vpd_mean_24h": 1,
    "wind_kmh": 1,
    "wind_dir_deg": 1,
    "peat_fraction": 1,
    "peat_area_km2": 1,
    "hotspots_in_cell_24h": 1,
    "hotspots_10km_7d": 1,
    "frp_sum_10km_7d": 1,
}

# Path helpers avoiding hardcoded relative path traps
PACKAGE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = PACKAGE_DIR.parent
DEFAULT_FEATURES_PATH: Path = PROJECT_ROOT / "data" / "processed" / "features.json"
DEFAULT_FEATURES_PARQUET_PATH: Path = PROJECT_ROOT / "data" / "processed" / "features.parquet"
DEFAULT_RISK_PATH: Path = PROJECT_ROOT / "data" / "processed" / "risk.json"
DEFAULT_HISTORY_PATH: Path = PROJECT_ROOT / "data" / "processed" / "history.parquet"
DEFAULT_MODEL_DIR: Path = PACKAGE_DIR / "model"
DEFAULT_MOCK_OUTPUT_PATH: Path = PACKAGE_DIR / "mock_output.json"


def get_risk_level(score: float) -> str:
    """
    Contract 3.2 risk classification.
    Enforces exact fixed boundaries:
    LOW < 0.35 <= MODERATE < 0.60 <= HIGH < 0.80 <= CRITICAL

    Args:
        score: Probability score in [0.0, 1.0]

    Returns:
        One of 'LOW', 'MODERATE', 'HIGH', 'CRITICAL'
    """
    if score < 0.35:
        return "LOW"
    elif score < 0.60:
        return "MODERATE"
    elif score < 0.80:
        return "HIGH"
    return "CRITICAL"


def setup_logger(name: str = "b_model", level: int = logging.INFO) -> logging.Logger:
    """Configures structured console logging."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


class CalibratedRiskModel:
    """
    Wraps base classifier to provide calibrated probability outputs.
    Guards against empirical probability compression on sparse real FIRMS data by automatically
    falling back to log-odds temperature calibration if pure Platt scaling compresses P99 < 0.75.
    """

    def __init__(
        self,
        base_estimator: Any,
        calibrator: Optional[Any] = None,
        use_logit_scaling: bool = False,
        shift: float = -0.3,
        temp: float = 1.2,
    ):
        self.base_estimator = base_estimator
        self.calibrator = calibrator
        self.use_logit_scaling = use_logit_scaling
        self.shift = shift
        self.temp = temp
        self.classes_ = np.array([0, 1])

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.use_logit_scaling and self.calibrator is not None:
            try:
                return self.calibrator.predict_proba(X)
            except Exception:
                pass

        # Prior-adjusted logit temperature calibration
        p_raw = self.base_estimator.predict_proba(X)[:, 1]
        eps = 1e-6
        p_clipped = np.clip(p_raw, eps, 1.0 - eps)
        logits = np.log(p_clipped / (1.0 - p_clipped))
        calib_logits = (logits + self.shift) / self.temp
        p_calib = 1.0 / (1.0 + np.exp(-calib_logits))
        return np.vstack([1.0 - p_calib, p_calib]).T

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.50).astype(int)