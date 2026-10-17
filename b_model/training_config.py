"""PIC 2's typed training settings, separate from PIC 1's inference config."""

from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
from typing import Dict, List, Optional

from hydra.core.config_store import ConfigStore
import numpy as np
from omegaconf import OmegaConf
import pandas as pd

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT


@dataclass
class TrainingPaths:
    history: str = "data/processed/history.parquet"
    model_dir: str = "b_model/runs/latest"


@dataclass
class SplitSettings:
    train_ratio: float = 0.55
    calibration_ratio: float = 0.20
    embargo_hours: int = 72
    strict_embargo: bool = True


@dataclass
class BaselineSettings:
    features: List[str] = field(default_factory=lambda: ["peat_fraction", "peat_area_km2", "temp_c", "precip_mm"])
    max_iter: int = 500
    c: float = 1.0
    z_score_clip: float = 3.0


@dataclass
class ModelSettings:
    backend: str = "auto"
    class_weight: Optional[str] = "balanced"
    max_iter: int = 150
    learning_rate: float = 0.05
    max_depth: int = 4
    min_samples_leaf: int = 25
    l2_regularization: float = 2.0
    logistic_max_iter: int = 500
    logistic_c: float = 1.0


@dataclass
class DrynessSettings:
    rain_weight: float = 0.40
    soil_weight: float = 0.40
    air_weight: float = 0.20
    rainless_days_cap: float = 30.0
    soil_moisture_reference: float = 0.50
    vpd_reference_kpa: float = 3.5
    missing_days_since_rain: float = 0.0
    missing_soil_moisture: float = 0.30
    missing_vpd_kpa: float = 1.5


def default_priorities() -> Dict[str, float]:
    return {"days_since_rain": 3.0, "sm_27_81": 3.0, "vpd_mean_24h": 2.5,
            "sm_27_81_delta_7d": 2.5, "vpd_kpa": 2.0, "rain_24h_mm": 2.5,
            "sm_0_1": 2.0, "hotspots_10km_7d": 2.0, "peat_fraction": 2.0,
            "et_mm": 0.05, "et0_mm": 0.05, "wind_dir_deg": 0.05,
            "soil_air_temp_gap_c": 0.05}


@dataclass
class ExplanationSettings:
    method: str = "signed_standardized"
    importance_split: str = "calibration"
    permutation_repeats: int = 5
    priority_multipliers: Dict[str, float] = field(default_factory=default_priorities)
    # PIC 1's current inference hard-codes these. Reject incompatible overrides.
    top_k: int = 3
    z_score_clip: Optional[float] = None
    contribution_clip: Optional[float] = None


@dataclass
class CalibrationSettings:
    method: str = "sigmoid"


@dataclass
class TrainingConfig:
    paths: TrainingPaths = field(default_factory=TrainingPaths)
    horizons: List[int] = field(default_factory=lambda: list(HORIZONS))
    seed: int = 42
    split: SplitSettings = field(default_factory=SplitSettings)
    baseline: BaselineSettings = field(default_factory=BaselineSettings)
    model: ModelSettings = field(default_factory=ModelSettings)
    dryness: DrynessSettings = field(default_factory=DrynessSettings)
    explanation: ExplanationSettings = field(default_factory=ExplanationSettings)
    calibration: CalibrationSettings = field(default_factory=CalibrationSettings)


def register_training_config() -> None:
    ConfigStore.instance().store(name="training_schema", node=TrainingConfig)


def validate_training_config(config) -> TrainingConfig:
    if isinstance(config, TrainingConfig):
        config = OmegaConf.structured(config)
    # Strip source-node metadata before merging: Hydra's +key syntax can add
    # fields to a structured node, and to_object would otherwise discard them.
    source = config if OmegaConf.is_config(config) else OmegaConf.create(config)
    plain = OmegaConf.to_container(source, resolve=True)
    merged = OmegaConf.merge(OmegaConf.structured(TrainingConfig), plain)
    OmegaConf.resolve(merged)
    result = OmegaConf.to_object(merged)

    def finite_tree(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Training settings must be finite numbers")
        if isinstance(value, dict):
            for child in value.values():
                finite_tree(child)
        elif isinstance(value, list):
            for child in value:
                finite_tree(child)

    finite_tree(asdict(result))
    if result.horizons != HORIZONS:
        raise ValueError("Training must retain horizons [24, 48, 72]")
    split = result.split
    if not (0 < split.train_ratio < 1 and 0 < split.calibration_ratio < 1
            and split.train_ratio + split.calibration_ratio < 1):
        raise ValueError("Training and calibration ratios must leave a nonempty validation fraction")
    if split.embargo_hours < max(HORIZONS):
        raise ValueError("embargo_hours must be at least 72 to cover all label horizons")
    if not split.strict_embargo:
        raise ValueError("Configured training requires strict_embargo=true; provide enough history for the full gap")
    if not 0 <= result.seed < 2 ** 32:
        raise ValueError("seed must be an unsigned 32-bit integer")
    if result.model.backend not in {"auto", "hist_gradient_boosting", "snapml", "logistic_regression"}:
        raise ValueError("Unsupported model backend")
    if result.model.class_weight not in ("balanced", None):
        raise ValueError("class_weight must be balanced or null")
    for name in ("max_iter", "max_depth", "min_samples_leaf", "logistic_max_iter"):
        if getattr(result.model, name) <= 0:
            raise ValueError(f"model.{name} must be positive")
    if not 0 < result.model.learning_rate <= 1 or result.model.l2_regularization < 0 or result.model.logistic_c <= 0:
        raise ValueError("Invalid model learning rate or regularization")
    baseline = result.baseline
    if (not baseline.features or len(set(baseline.features)) != len(baseline.features)
            or set(baseline.features) - set(FEATURE_COLUMNS)):
        raise ValueError("baseline.features must contain unique canonical feature names")
    if baseline.max_iter <= 0 or baseline.c <= 0 or baseline.z_score_clip <= 0:
        raise ValueError("Baseline max_iter, c and z_score_clip must be positive")
    dry = result.dryness
    weights = (dry.rain_weight, dry.soil_weight, dry.air_weight)
    if any(weight < 0 for weight in weights) or not math.isclose(sum(weights), 1.0, abs_tol=1e-8):
        raise ValueError("Dryness weights must be nonnegative and sum to 1")
    if min(dry.rainless_days_cap, dry.soil_moisture_reference, dry.vpd_reference_kpa) <= 0:
        raise ValueError("Dryness normalizing references must be positive")
    if (dry.missing_days_since_rain < 0 or dry.missing_vpd_kpa < 0
            or not 0 <= dry.missing_soil_moisture <= 1):
        raise ValueError("Invalid dryness missing-value defaults")
    explain = result.explanation
    if explain.method != "signed_standardized" or explain.importance_split not in {"train", "calibration"}:
        raise ValueError("Use signed_standardized explanations with train/calibration importance data")
    if explain.permutation_repeats < 1:
        raise ValueError("permutation_repeats must be positive")
    if (set(explain.priority_multipliers) - set(FEATURE_COLUMNS)
            or any(value <= 0 for value in explain.priority_multipliers.values())):
        raise ValueError("Explanation multipliers need canonical features and positive weights")
    if explain.top_k != 3 or explain.z_score_clip is not None or explain.contribution_clip is not None:
        raise ValueError("PIC 1 inference requires top_k=3 and unclipped standardized contributions (both explanation clips null)")
    if result.calibration.method not in {"sigmoid", "isotonic", "legacy_guarded"}:
        raise ValueError("Calibration method must be sigmoid, isotonic or legacy_guarded")
    if not result.paths.history.strip() or not result.paths.model_dir.strip():
        raise ValueError("History and model directory paths must be nonempty")
    return result


def resolve_training_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def compute_training_dryness(df: pd.DataFrame, settings: DrynessSettings) -> pd.Series:
    """PIC 2 baseline feature; defaults match PIC 1's existing complete-data formula."""
    def series(name, fallback):
        return pd.to_numeric(df.get(name, pd.Series(fallback, index=df.index)), errors="raise")

    days = series("days_since_rain", settings.missing_days_since_rain).fillna(settings.missing_days_since_rain)
    soil = series("sm_27_81", settings.missing_soil_moisture).fillna(settings.missing_soil_moisture)
    vpd = series("vpd_mean_24h", np.nan).fillna(series("vpd_kpa", settings.missing_vpd_kpa)).fillna(settings.missing_vpd_kpa)
    rain_dry = days.clip(0, settings.rainless_days_cap) / settings.rainless_days_cap
    soil_dry = (1 - soil / settings.soil_moisture_reference).clip(0, 1)
    air_dry = (vpd / settings.vpd_reference_kpa).clip(0, 1)
    return (settings.rain_weight * rain_dry + settings.soil_weight * soil_dry + settings.air_weight * air_dry).clip(0, 1)
