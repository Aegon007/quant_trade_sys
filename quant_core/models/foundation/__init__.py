"""Foundation-model-first quant engine.

The production direction is a pluggable time-series foundation model layer
with explicit risk overlays. The deterministic proxy backend exists only to
keep the personal system usable when TimesFM/Chronos/MOMENT dependencies or
checkpoints are not installed.
"""

from quant_core.models.foundation.config import load_foundation_model_config, save_foundation_model_config
from quant_core.models.foundation.pipeline import run_foundation_job

__all__ = [
    "load_foundation_model_config",
    "run_foundation_job",
    "save_foundation_model_config",
]
