"""
Training pipeline for Role B (ML Lead).
Predicts peat fire hotspot emergence for 24h, 48h, and 72h horizons.
Supports IBM Snap ML on IBM Z / LinuxONE (s390x) with Scikit-Learn fallback.
Configured runs require producer-supplied future labels, strict chronological
train/calibration/validation splits and held-out probability calibration.
Strict adherence to Team Playbook Contracts 3.1 & 3.2.
"""

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import Any, Dict, List, Optional, Tuple
import joblib
import hydra
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from b_model.config import (
    CalibratedRiskModel,
    DEFAULT_FEATURES_PARQUET_PATH,
    DEFAULT_HISTORY_PATH,
    DEFAULT_MODEL_DIR,
    DOMAIN_FEATURE_SIGNS,
    FEATURE_COLUMNS,
    HORIZONS,
    MODEL_VERSION,
    SCHEMA_VERSION,
    TARGET_COLS,
    setup_logger,
)
from b_model.features import generate_mock_data_if_missing
from b_model.training_config import (
    TrainingConfig, compute_training_dryness, register_training_config,
    resolve_training_path, validate_training_config,
)
from omegaconf import OmegaConf

# Silence multiprocessing loky worker warnings on Windows / containers
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

logger = setup_logger("b_model.train")

# IBM Snap ML hardware-accelerated library check for LinuxONE (s390x)
try:
    from snapml import BoostingMachineClassifier as SnapBoostingMachineClassifier
    from snapml import LogisticRegression as SnapLogisticRegression

    SNAPML_AVAILABLE = True
    logger.info("IBM Snap ML is installed and available; verify hardware performance on the deployment target.")
except ImportError:
    SNAPML_AVAILABLE = False
    logger.info("IBM Snap ML is NOT installed. Falling back to Scikit-Learn gradient boosting.")

# Check for Scikit-Learn >= 1.6 FrozenEstimator (with fallback for sklearn < 1.6 on s390x)
try:
    from sklearn.frozen import FrozenEstimator

    FROZEN_ESTIMATOR_AVAILABLE = True
except ImportError:
    FROZEN_ESTIMATOR_AVAILABLE = False
    logger.debug("FrozenEstimator not present (sklearn < 1.6); using cv='prefit' fallback.")


def compute_directional_feature_signs(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feature_names: List[str] = FEATURE_COLUMNS,
) -> np.ndarray:
    """
    Computes a directional sign vector for physical feature attribution.
    Enforces domain overrides:
    - sm_*, rain_*, precip_mm, et_mm, nearest_hotspot_km have sign -1 (inverse risk)
    - days_since_rain, temp_c, vpd_*, peat_*, hotspots_*, frp_* have sign +1 (direct risk)
    Falls back to Spearman rank correlation sign if not in domain override map.
    """
    signs = np.ones(len(feature_names), dtype=float)
    y_s = pd.Series(y_train)

    for idx, feat in enumerate(feature_names):
        if feat in DOMAIN_FEATURE_SIGNS:
            signs[idx] = float(DOMAIN_FEATURE_SIGNS[feat])
        else:
            x_s = pd.Series(X_train[:, idx])
            corr = x_s.corr(y_s, method="spearman")
            if not np.isnan(corr) and abs(corr) > 1e-4:
                signs[idx] = 1.0 if corr > 0 else -1.0
            else:
                signs[idx] = 1.0

    return signs


def ensure_target_labels(df: pd.DataFrame, horizons: List[int] = HORIZONS) -> pd.DataFrame:
    """
    Ensures binary target columns exist for all horizons.
    Target = 1 if at least one FIRMS hotspot emerges in cell within [t + 1h, t + horizon_h], else 0.
    Uses .shift(-1) before forward rolling to strictly eliminate current-hour target leakage.
    """
    df = df.sort_values(["cell_id", "ts"]).copy()
    hotspot_src = "hotspots_in_cell_24h" if "hotspots_in_cell_24h" in df.columns else None

    for h in horizons:
        col = TARGET_COLS[h]
        if col not in df.columns:
            logger.warning("Target column '%s' missing. Computing non-leaking forward-looking labels.", col)
            if hotspot_src is None:
                logger.warning("No hotspot count found; defaulting synthetic targets.")
                df[col] = 0
            else:
                indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=h)
                df[col] = (
                    df.groupby("cell_id")[hotspot_src]
                    .transform(
                        lambda s: (
                            s.shift(-1)
                            .fillna(0)
                            .rolling(indexer, min_periods=1)
                            .max() > 0
                        ).astype(int)
                    )
                )
    return df


def temporal_train_val_split(
    df: pd.DataFrame,
    train_ratio: float = 0.80,
    embargo_hours: int = 72,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    2-way temporal split with an embargo/purge gap.
    """
    df = df.sort_values("ts").reset_index(drop=True)
    df["_ts_dt"] = pd.to_datetime(df["ts"])
    unique_timestamps = np.sort(df["_ts_dt"].unique())

    split_index = int(len(unique_timestamps) * train_ratio)
    val_start = unique_timestamps[split_index]

    total_hours = (val_start - unique_timestamps[0]).total_seconds() / 3600.0
    if total_hours > embargo_hours * 1.5:
        train_cutoff = val_start - pd.Timedelta(hours=embargo_hours)
    else:
        short_gap = max(1, int(total_hours * 0.10))
        train_cutoff = val_start - pd.Timedelta(hours=short_gap)

    df_train = df[df["_ts_dt"] < train_cutoff].copy().drop(columns=["_ts_dt"])
    df_val = df[df["_ts_dt"] >= val_start].copy().drop(columns=["_ts_dt"])
    return df_train, df_val


def temporal_train_calib_val_split(
    df: pd.DataFrame,
    train_ratio: float = 0.55,
    calib_ratio: float = 0.20,
    embargo_hours: int = 72,
    strict_embargo: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Performs a 3-way chronological split:
    Train (~55%) -> 72h Embargo -> Calibration (~20%) -> 72h Embargo -> Validation (~25%).
    Ensures calibration is fit on its own chronological slice and never on the final evaluation set.
    """
    df = df.sort_values("ts").reset_index(drop=True)
    df["_ts_dt"] = pd.to_datetime(df["ts"])
    unique_ts = np.sort(df["_ts_dt"].unique())

    total_unique = len(unique_ts)
    idx_train_end = max(1, int(total_unique * train_ratio))
    idx_calib_end = max(idx_train_end + 1, int(total_unique * (train_ratio + calib_ratio)))

    calib_start = unique_ts[idx_train_end]
    val_start = unique_ts[idx_calib_end]

    total_hours = (unique_ts[-1] - unique_ts[0]).total_seconds() / 3600.0
    if strict_embargo or total_hours > embargo_hours * 3.5:
        gap = pd.Timedelta(hours=embargo_hours)
    else:
        gap = pd.Timedelta(hours=max(1, int(total_hours * 0.03)))

    train_cutoff = calib_start - gap
    calib_cutoff = val_start - gap

    df_train = df[df["_ts_dt"] < train_cutoff].copy().drop(columns=["_ts_dt"])
    df_calib = df[(df["_ts_dt"] >= calib_start) & (df["_ts_dt"] < calib_cutoff)].copy().drop(columns=["_ts_dt"])
    df_val = df[df["_ts_dt"] >= val_start].copy().drop(columns=["_ts_dt"])

    if df_train.empty or df_calib.empty or df_val.empty:
        raise ValueError("History is too short for nonempty train/calibration/validation sets with the requested embargo; provide more history or adjust split ratios")

    logger.info(
        "3-way temporal split: Train=%d rows (< %s), Calib=%d rows (%s - %s), Val=%d rows (>= %s)",
        len(df_train),
        train_cutoff,
        len(df_calib),
        calib_start,
        calib_cutoff,
        len(df_val),
        val_start,
    )
    return df_train, df_calib, df_val


def compute_lead_time_hours(
    df_val: pd.DataFrame,
    y_val: np.ndarray,
    probs_val: np.ndarray,
    horizon_h: int,
    alert_threshold: float = 0.60,
) -> Optional[float]:
    """
    Estimates lead time: average hours before hotspot emergence that a cell crossed risk_score >= 0.60.
    For each cell's hotspot onset timestamp t_fire (where hotspots_in_cell_24h > 0 following at least
    12 hours of hotspots_in_cell_24h == 0), look back up to horizon_h hours ([t_fire - horizon_h, t_fire])
    and find the earliest timestamp t_warn where predicted risk_score >= 0.60.
    Lead time is t_fire - t_warn in hours.
    """
    df_eval = df_val[["cell_id", "ts"]].copy()
    df_eval["ts_dt"] = pd.to_datetime(df_eval["ts"])
    if "hotspots_in_cell_24h" in df_val.columns:
        df_eval["hotspots"] = df_val["hotspots_in_cell_24h"].values
    else:
        df_eval["hotspots"] = y_val
    df_eval["prob"] = probs_val
    df_eval = df_eval.sort_values(["cell_id", "ts_dt"]).reset_index(drop=True)

    lead_times: List[float] = []

    for cell_id, group in df_eval.groupby("cell_id"):
        group = group.reset_index(drop=True)
        hotspot_series = group["hotspots"].values
        n_rows = len(group)

        for i in range(n_rows):
            if hotspot_series[i] > 0:
                lookback_len = min(i, 12)
                if lookback_len >= 4:
                    preceding = hotspot_series[max(0, i - 12):i]
                    if np.all(preceding == 0):
                        t_fire = group.loc[i, "ts_dt"]
                        window_start = t_fire - pd.Timedelta(hours=horizon_h)
                        window = group[(group["ts_dt"] >= window_start) & (group["ts_dt"] <= t_fire)]
                        alerts = window[window["prob"] >= alert_threshold]
                        if not alerts.empty:
                            t_warn = alerts["ts_dt"].iloc[0]
                            lead_h = (t_fire - t_warn).total_seconds() / 3600.0
                            if lead_h > 0:
                                lead_times.append(lead_h)

    if lead_times:
        return float(np.round(np.mean(lead_times), 1))

    # No observed qualifying event means lead time is unmeasured, not invented.
    return None


def build_calibrated_model(
    base_primary: Any,
    X_calib_imp: np.ndarray,
    y_calib: np.ndarray,
    horizon_h: int,
    method: str = "legacy_guarded",
) -> CalibratedRiskModel:
    """
    Fits probability calibration on held-out calibration slice.
    Checks P99 to guard against probability compression on sparse satellite data.
    If Platt scaling compresses P99 < 0.75, dynamically computes log-odds prior shift
    and temperature scaling so that extreme drought reaches >= 0.80 (CRITICAL) while
    median/wet conditions stay < 0.35 (LOW).
    """
    if method in {"sigmoid", "isotonic"}:
        if len(X_calib_imp) == 0 or len(np.unique(y_calib)) < 2:
            raise ValueError(f"Horizon {horizon_h}h needs both classes in its chronological calibration slice")
        if FROZEN_ESTIMATOR_AVAILABLE:
            fitted = CalibratedClassifierCV(FrozenEstimator(base_primary), method=method)
        else:
            fitted = CalibratedClassifierCV(estimator=base_primary, method=method, cv="prefit")
        fitted.fit(X_calib_imp, y_calib)
        return CalibratedRiskModel(base_estimator=base_primary, calibrator=fitted, use_logit_scaling=False)
    if method != "legacy_guarded":
        raise ValueError(f"Unsupported calibration method: {method}")
    calibrator: Optional[Any] = None
    use_logit_scaling: bool = False
    shift: float = -0.3
    temp: float = 1.2

    if len(X_calib_imp) > 0 and len(np.unique(y_calib)) > 1:
        try:
            if FROZEN_ESTIMATOR_AVAILABLE:
                calibrator = CalibratedClassifierCV(FrozenEstimator(base_primary), method="sigmoid")
            else:
                calibrator = CalibratedClassifierCV(estimator=base_primary, method="sigmoid", cv="prefit")
            calibrator.fit(X_calib_imp, y_calib)

            p_calib_check = calibrator.predict_proba(X_calib_imp)[:, 1]
            p99 = float(np.percentile(p_calib_check, 99))
            logger.info("Horizon %dh: Calibrated P99 on calibration slice = %.3f", horizon_h, p99)

            if p99 < 0.85:
                logger.warning(
                    "Horizon %dh: Pure Platt scaling compressed P99 to %.3f (< 0.85). "
                    "Enabling log-odds prior-adjusted calibration to protect CRITICAL risk threshold.",
                    horizon_h,
                    p99,
                )
                use_logit_scaling = True
            else:
                use_logit_scaling = False
        except Exception as e:
            logger.warning("Horizon %dh: CalibratedClassifierCV failed (%s); using logit scaling.", horizon_h, e)
            use_logit_scaling = True
    else:
        logger.info("Horizon %dh: Calibration slice single-class; defaulting to logit scaling.", horizon_h)
        use_logit_scaling = True

    # If logit scaling is needed (due to sparse label compression):
    if use_logit_scaling and len(X_calib_imp) > 0:
        raw_calib_probs = base_primary.predict_proba(X_calib_imp)[:, 1]
        eps = 1e-6
        p_clipped = np.clip(raw_calib_probs, eps, 1.0 - eps)
        p50 = float(np.percentile(p_clipped, 50))
        p90 = float(np.percentile(p_clipped, 90))

        z50 = np.log(p50 / (1.0 - p50))
        z90 = np.log(p90 / (1.0 - p90))

        # Cap z90 at 2.2 (prob ~ 0.90) so confident dry spells don't get over-compressed
        z_high = min(z90, 2.2)
        z_low = min(z50, -1.5)

        target_low = -2.0   # sigma(-2.0) ~ 0.12 (LOW)
        target_high = 1.75  # sigma(1.75) ~ 0.85 (CRITICAL)

        if z_high > z_low + 1e-3:
            A = (target_high - target_low) / (z_high - z_low)
            B = target_high - A * z_high
            temp = float(1.0 / A)
            shift = float(B / A)
        else:
            temp = 1.0
            shift = 0.25
        logger.info("Horizon %dh fitted log-odds prior shift: shift=%.3f, temp=%.3f", horizon_h, shift, temp)

    return CalibratedRiskModel(
        base_estimator=base_primary,
        calibrator=calibrator,
        use_logit_scaling=use_logit_scaling,
        shift=shift,
        temp=temp,
    )



def train_pipeline(
    history_path: Path = DEFAULT_HISTORY_PATH,
    model_dir: Path = DEFAULT_MODEL_DIR,
    force_mock: bool = False,
    training_config: Optional[TrainingConfig] = None,
) -> Dict[str, Any]:
    """
    Train all horizons and save fitted state plus resolved experiment settings.
    Configured calls require labeled history and a strict chronological protocol.
    Calls without settings retain the older synthetic-data compatibility path.
    """
    settings = validate_training_config(training_config or TrainingConfig())
    if training_config is None:
        # Preserve the direct API used by existing short synthetic tests. The
        # configured CLI uses strict embargo and genuine held-out calibration.
        settings.split.strict_embargo = False
        settings.calibration.method = "legacy_guarded"
    settings.paths.history = str(history_path.resolve())
    settings.paths.model_dir = str(model_dir.resolve())
    backend = settings.model.backend
    if backend == "auto":
        backend = "snapml" if SNAPML_AVAILABLE else "hist_gradient_boosting"
    if backend == "snapml" and not SNAPML_AVAILABLE:
        raise ImportError("model=snapml requires the optional snapml package; select model=hist_gradient_boosting locally")

    # 1. Configured runs never silently substitute synthetic history.
    resolved_path = history_path
    if training_config is not None and not force_mock and not resolved_path.is_file():
        raise FileNotFoundError(f"Training history does not exist: {resolved_path}")
    if training_config is not None and not force_mock and resolved_path.stat().st_size == 0:
        raise ValueError(f"Training history is empty: {resolved_path}")
    if not resolved_path.exists() or resolved_path.stat().st_size == 0:
        if DEFAULT_FEATURES_PARQUET_PATH.exists() and DEFAULT_FEATURES_PARQUET_PATH.stat().st_size > 0:
            logger.info("Using features.parquet fallback at %s", DEFAULT_FEATURES_PARQUET_PATH)
            resolved_path = DEFAULT_FEATURES_PARQUET_PATH
        else:
            logger.info("Generating realistic mock history table -> %s", resolved_path)
            generate_mock_data_if_missing(history_path=resolved_path, features_path=model_dir / "generated_features.json", force=True)

    if force_mock:
        logger.info("Force flag set; regenerating mock data -> %s", resolved_path)
        generate_mock_data_if_missing(history_path=resolved_path, features_path=model_dir / "generated_features.json", force=True)

    df_raw = pd.read_parquet(resolved_path)
    logger.info("Loaded training data: %d rows from %s", len(df_raw), resolved_path)

    if training_config is not None:
        required = {"cell_id", "ts", *FEATURE_COLUMNS, *(TARGET_COLS[h] for h in HORIZONS)}
        missing = required - set(df_raw.columns)
        if missing:
            raise ValueError(f"Training history requires canonical features and producer-supplied future labels; missing: {sorted(missing)}")
        if df_raw.duplicated(["cell_id", "ts"]).any():
            raise ValueError("Duplicate (cell_id, ts) in training history")
        if not df_raw["ts"].map(lambda value: isinstance(value, str) and value.endswith("Z")).all():
            raise ValueError("Training timestamps must be UTC strings ending in Z")
        pd.to_datetime(df_raw["ts"], utc=True, errors="raise")
        targets = [TARGET_COLS[h] for h in HORIZONS]
        original_count = len(df_raw)
        df_raw = df_raw.dropna(subset=targets).copy()
        logger.info("Dropped %d rows with incomplete future labels", original_count - len(df_raw))
        if df_raw.empty or not df_raw[targets].isin([0, 1]).all().all():
            raise ValueError("Training history needs observed binary target labels (0/1)")

    # 2. Guarantee targets and column alignment
    df = ensure_target_labels(df_raw, HORIZONS)
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = pd.to_numeric(df[col], errors="raise" if training_config is not None else "coerce")

    # 3. 3-way chronological split: Train (~55%) -> Embargo -> Calib (~20%) -> Embargo -> Val (~25%)
    df_train, df_calib, df_val = temporal_train_calib_val_split(
        df, train_ratio=settings.split.train_ratio, calib_ratio=settings.split.calibration_ratio,
        embargo_hours=settings.split.embargo_hours, strict_embargo=settings.split.strict_embargo,
    )

    # 4. Fit Imputer and Scaler on train split only
    X_train_raw = df_train[FEATURE_COLUMNS].copy()
    X_calib_raw = df_calib[FEATURE_COLUMNS].copy()
    X_val_raw = df_val[FEATURE_COLUMNS].copy()

    if X_train_raw.isna().all().any():
        raise ValueError("Every canonical feature needs at least one training value for median imputation")
    if training_config is not None:
        values = df[FEATURE_COLUMNS].to_numpy(dtype=float)
        if np.isinf(values).any() or (values == -999).any():
            raise ValueError("Training measurements must not contain infinity or -999 sentinels")

    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()

    X_train_imp = imputer.fit_transform(X_train_raw)
    clip = settings.baseline.z_score_clip
    X_train_scaled = np.clip(scaler.fit_transform(X_train_imp), -clip, clip)

    X_calib_imp = imputer.transform(X_calib_raw)
    X_val_imp = imputer.transform(X_val_raw)
    X_val_scaled = np.clip(scaler.transform(X_val_imp), -clip, clip)

    # Rule-based dryness index for baseline feature
    dryness_train = compute_training_dryness(df_train, settings.dryness).values.reshape(-1, 1)
    dryness_val = compute_training_dryness(df_val, settings.dryness).values.reshape(-1, 1)

    # Compute physical directional signs
    feature_signs = compute_directional_feature_signs(
        X_train_imp,
        df_train[TARGET_COLS[24]].values if TARGET_COLS[24] in df_train.columns else np.zeros(len(df_train)),
        FEATURE_COLUMNS,
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    all_metrics: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "snapml_accelerated": backend == "snapml",
        "model_backend": backend,
        "training_config": asdict(settings),
        "training_data": {"path": str(resolved_path.resolve()),
                          "sha256": hashlib.sha256(resolved_path.read_bytes()).hexdigest(),
                          "rows_used": len(df), "provenance": "Not verified by training; confirm with Role A"},
        "split_rows": {"train": len(df_train), "calibration": len(df_calib), "validation": len(df_val)},
        "split_ranges": {name: {"start": part["ts"].min(), "end": part["ts"].max()}
                         for name, part in (("train", df_train), ("calibration", df_calib), ("validation", df_val))},
        "library_versions": {name: version(name) for name in
                             ("numpy", "pandas", "scikit-learn", "joblib", "hydra-core", "omegaconf")},
        "horizons": {},
    }

    for horizon in HORIZONS:
        target_col = TARGET_COLS[horizon]
        y_train = df_train[target_col].values.astype(int)
        y_calib = df_calib[target_col].values.astype(int)
        y_val = df_val[target_col].values.astype(int)

        pos_rate_train = float(np.mean(y_train))
        pos_rate_calib = float(np.mean(y_calib)) if len(y_calib) > 0 else 0.0
        pos_rate_val = float(np.mean(y_val)) if len(y_val) > 0 else 0.0
        logger.info(
            "Horizon %dh: Train pos=%.3f, Calib pos=%.3f, Val pos=%.3f",
            horizon, pos_rate_train, pos_rate_calib, pos_rate_val,
        )

        # Baseline Model: Logistic Regression on dryness index + top surface features
        baseline_indices = [FEATURE_COLUMNS.index(name) for name in settings.baseline.features]
        baseline_X_train = np.hstack([dryness_train, X_train_scaled[:, baseline_indices]])
        baseline_X_val = np.hstack([dryness_val, X_val_scaled[:, baseline_indices]])

        if len(np.unique(y_train)) < 2:
            raise ValueError(f"Horizon {horizon}h needs both target classes in training")
        baseline_model = LogisticRegression(class_weight=settings.model.class_weight, random_state=settings.seed,
                                            max_iter=settings.baseline.max_iter, C=settings.baseline.c)
        baseline_model.fit(baseline_X_train, y_train)
        baseline_probs_val = baseline_model.predict_proba(baseline_X_val)[:, 1]

        # Primary Model: IBM Snap ML Boosting or HistGradientBoosting
        if backend == "snapml":
            logger.info("Training IBM Snap ML BoostingMachineClassifier for horizon %dh", horizon)
            base_primary = SnapBoostingMachineClassifier(
                random_state=settings.seed,
                class_weight=settings.model.class_weight,
                num_round=settings.model.max_iter,
                learning_rate=settings.model.learning_rate,
                max_depth=settings.model.max_depth,
                lambda_l2=settings.model.l2_regularization,
            )
            base_primary.fit(X_train_imp, y_train)
            if hasattr(base_primary, "feature_importances_"):
                raw_weights = np.array(base_primary.feature_importances_, dtype=float)
            else:
                raw_weights = np.ones(len(FEATURE_COLUMNS)) / len(FEATURE_COLUMNS)
        elif backend == "logistic_regression":
            # PIC 1 still supplies raw imputed predictors; scale inside the model.
            base_primary = make_pipeline(StandardScaler(), LogisticRegression(
                class_weight=settings.model.class_weight, random_state=settings.seed,
                max_iter=settings.model.logistic_max_iter, C=settings.model.logistic_c))
            base_primary.fit(X_train_imp, y_train)
            raw_weights = np.abs(base_primary.named_steps["logisticregression"].coef_[0])
        else:
            logger.info("Training Scikit-Learn HistGradientBoostingClassifier for horizon %dh", horizon)
            base_primary = HistGradientBoostingClassifier(
                class_weight=settings.model.class_weight,
                random_state=settings.seed,
                max_iter=settings.model.max_iter,
                learning_rate=settings.model.learning_rate,
                max_depth=settings.model.max_depth,
                min_samples_leaf=settings.model.min_samples_leaf,
                l2_regularization=settings.model.l2_regularization,
                early_stopping=False,
            )
            base_primary.fit(X_train_imp, y_train)

            importance_X, importance_y = ((X_calib_imp, y_calib) if settings.explanation.importance_split == "calibration"
                                          else (X_train_imp, y_train))
            if len(importance_X) > 0 and len(np.unique(importance_y)) > 1:
                perm_result = permutation_importance(
                    base_primary, importance_X, importance_y,
                    n_repeats=settings.explanation.permutation_repeats, random_state=settings.seed, scoring="roc_auc"
                )
                raw_weights = np.maximum(0.0, perm_result.importances_mean)
            else:
                raw_weights = np.ones(len(FEATURE_COLUMNS))

            if raw_weights.sum() == 0:
                raw_weights = np.ones(len(FEATURE_COLUMNS))

        # 5. Build Calibrated Model guarded against probability compression
        primary_model = build_calibrated_model(
            base_primary=base_primary,
            X_calib_imp=X_calib_imp,
            y_calib=y_calib,
            horizon_h=horizon,
            method=settings.calibration.method,
        )

        # Boost core peat hydrology features and down-weight auxiliary meteorological noise
        priority_multipliers = np.ones(len(FEATURE_COLUMNS), dtype=float)
        for i, col in enumerate(FEATURE_COLUMNS):
            priority_multipliers[i] = settings.explanation.priority_multipliers.get(col, 1.0)

        raw_weights = raw_weights * priority_multipliers

        # Compute signed feature weights
        sum_w = float(np.sum(np.abs(raw_weights)))
        norm_weights = (raw_weights / sum_w) if sum_w > 0 else (np.ones(len(FEATURE_COLUMNS)) / len(FEATURE_COLUMNS))
        signed_feature_weights = norm_weights * feature_signs

        # Validation predictions & evaluation on final validation split
        probs_val = primary_model.predict_proba(X_val_imp)[:, 1] if len(X_val_imp) > 0 else np.zeros(0)
        preds_val = (probs_val >= 0.50).astype(int)

        pr_auc = float(average_precision_score(y_val, probs_val)) if len(np.unique(y_val)) > 1 else None
        roc_auc = float(roc_auc_score(y_val, probs_val)) if len(np.unique(y_val)) > 1 else None
        prec = float(precision_score(y_val, preds_val, zero_division=0))
        rec = float(recall_score(y_val, preds_val, zero_division=0))
        f1 = float(f1_score(y_val, preds_val, zero_division=0))

        baseline_pr = float(average_precision_score(y_val, baseline_probs_val)) if len(np.unique(y_val)) > 1 else None
        baseline_roc = float(roc_auc_score(y_val, baseline_probs_val)) if len(np.unique(y_val)) > 1 else None

        lead_time = compute_lead_time_hours(df_val, y_val, probs_val, horizon_h=horizon)

        horizon_metrics = {
            "pr_auc": round(pr_auc, 3) if pr_auc is not None else None,
            "roc_auc": round(roc_auc, 3) if roc_auc is not None else None,
            "precision": round(prec, 3),
            "recall": round(rec, 3),
            "f1": round(f1, 3),
            "lead_time_hours": lead_time,
            "baseline_pr_auc": round(baseline_pr, 3) if baseline_pr is not None else None,
            "baseline_roc_auc": round(baseline_roc, 3) if baseline_roc is not None else None,
        }
        all_metrics["horizons"][str(horizon)] = horizon_metrics

        logger.info(
            "Horizon %dh Metrics: PR-AUC=%s, ROC-AUC=%s, Prec=%.3f, Rec=%.3f, F1=%.3f, LeadTime=%s h",
            horizon, pr_auc, roc_auc, prec, rec, f1, lead_time,
        )

        # 6. Save joblib bundle
        artifact = {
            "horizon_h": horizon,
            "model_version": MODEL_VERSION,
            "schema_version": SCHEMA_VERSION,
            "feature_columns": FEATURE_COLUMNS,
            "imputer": imputer,
            "scaler": scaler,
            "baseline_model": baseline_model,
            "primary_model": primary_model,
            "base_primary": base_primary,
            "model": primary_model,
            "feature_weights": signed_feature_weights,
            "signed_feature_weights": signed_feature_weights,
            "feature_signs": feature_signs,
            "snapml_used": backend == "snapml",
            "training_config": asdict(settings),
            "dryness_config": asdict(settings.dryness),
            "baseline_feature_columns": ["dryness_index", *settings.baseline.features],
            "baseline_config": asdict(settings.baseline),
            "explanation_config": asdict(settings.explanation),
            "training_data": all_metrics["training_data"],
        }

        artifact_path = model_dir / f"model_{horizon}h.joblib"
        joblib.dump(artifact, artifact_path)
        logger.info("Saved artifact to %s", artifact_path)

    # Measured lead times are never replaced to force a minimum or ordering.
    OmegaConf.save(OmegaConf.structured(settings), model_dir / "training_config.yaml", resolve=True)

    # Save metrics JSON
    metrics_path = model_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2, allow_nan=False)
    logger.info("Saved validation metrics to %s", metrics_path)

    # Publish the PIC 1 handoff only after all three bundles are available.
    manifest = {"schema_version": SCHEMA_VERSION, "models": {
        str(horizon): {"filename": f"model_{horizon}h.joblib", "format": "joblib",
                       "model_version": MODEL_VERSION, "feature_order": list(FEATURE_COLUMNS),
                       "positive_class": 1}
        for horizon in HORIZONS}}
    manifest_path = model_dir / "artifact_manifest.json"
    temporary = manifest_path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)

    return all_metrics


def main():
    parser = argparse.ArgumentParser(description="Role B Peat Fire ML Training Pipeline")
    parser.add_argument(
        "--input",
        "--data-path",
        dest="data_path",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Path to training history parquet (falls back to features.parquet if missing)",
    )
    parser.add_argument(
        "--output",
        "--model-dir",
        dest="model_dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Directory to save model artifacts and metrics",
    )
    parser.add_argument(
        "--force-mock",
        action="store_true",
        help="Regenerate synthetic history data even if file exists",
    )
    args = parser.parse_args()

    train_pipeline(
        history_path=args.data_path,
        model_dir=args.model_dir,
        force_mock=args.force_mock,
        training_config=TrainingConfig(),
    )


def run_configured_training(config) -> Dict[str, Any]:
    settings = validate_training_config(config)
    return train_pipeline(history_path=resolve_training_path(settings.paths.history),
                          model_dir=resolve_training_path(settings.paths.model_dir), training_config=settings)


register_training_config()


@hydra.main(version_base="1.3", config_path="conf", config_name="training")
def hydra_training_main(config):
    return run_configured_training(config)


if __name__ == "__main__":
    legacy_flags = {"--input", "--data-path", "--output", "--model-dir", "--force-mock"}
    if any(arg.split("=")[0] in legacy_flags for arg in sys.argv[1:]):
        main()
    else:
        hydra_training_main()
