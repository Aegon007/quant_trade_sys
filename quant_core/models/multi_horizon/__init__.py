"""Finance-native multi-asset, multi-horizon model components."""

from .dataset import (
    FEATURE_COLUMNS,
    build_forward_labels,
    build_panel_frame,
)
from .config import load_multi_horizon_config, save_multi_horizon_config
from .fusion import FusedDecision, fuse_multi_horizon_decision
from .governance import (
    append_prediction_journal,
    build_model_governance_snapshot,
    refresh_model_governance,
    score_shadow_outcomes,
)
from .network import FinanceMultiAssetTransformer, MultiAssetTransformerConfig
from .prediction import build_prediction_snapshot
from .pipeline import (
    build_model_universe,
    build_satellite_snapshot_from_model,
    model_training_due,
    run_multi_horizon_job,
)
from .pretraining import pretrain_temporal_encoder
from .runtime import run_multi_horizon_inference
from .snapshot import load_multi_horizon_snapshot, save_multi_horizon_snapshot
from .validation import (
    evaluate_prediction_arrays,
    purged_walk_forward_splits,
    walk_forward_validate_bundle,
)

__all__ = [
    "FEATURE_COLUMNS",
    "FinanceMultiAssetTransformer",
    "FusedDecision",
    "MultiAssetTransformerConfig",
    "build_forward_labels",
    "build_model_governance_snapshot",
    "build_panel_frame",
    "build_prediction_snapshot",
    "build_model_universe",
    "build_satellite_snapshot_from_model",
    "append_prediction_journal",
    "evaluate_prediction_arrays",
    "load_multi_horizon_config",
    "fuse_multi_horizon_decision",
    "load_multi_horizon_snapshot",
    "model_training_due",
    "purged_walk_forward_splits",
    "refresh_model_governance",
    "pretrain_temporal_encoder",
    "run_multi_horizon_inference",
    "run_multi_horizon_job",
    "save_multi_horizon_config",
    "save_multi_horizon_snapshot",
    "score_shadow_outcomes",
    "walk_forward_validate_bundle",
]
