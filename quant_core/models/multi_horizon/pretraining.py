from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .network import MultiAssetTransformerConfig, PatchTemporalEncoder
from .training import MultiAssetTensorBundle, _resolve_device


class MaskedPatchPretrainer(nn.Module):
    """Reconstruct masked patch-level feature means before supervised training."""

    def __init__(self, config: MultiAssetTransformerConfig):
        super().__init__()
        self.config = config
        self.temporal = PatchTemporalEncoder(config)
        self.decoder = nn.Linear(config.d_model, config.feature_count)

    def forward(self, sequences):
        tokens, batch_size, asset_count = self.temporal.encode_tokens(sequences)
        reconstructed = self.decoder(tokens)
        return reconstructed.reshape(batch_size, asset_count, reconstructed.shape[1], -1)


def _patch_targets(sequences, *, patch_size: int, patch_stride: int):
    batch_size, asset_count, time_steps, feature_count = sequences.shape
    flattened = sequences.reshape(batch_size * asset_count, time_steps, feature_count).transpose(1, 2)
    patches = flattened.unfold(2, int(patch_size), int(patch_stride)).mean(dim=-1)
    return patches.transpose(1, 2).reshape(batch_size, asset_count, patches.shape[-1], feature_count)


def _mask_patch_spans(sequences, patch_mask, *, patch_size: int, patch_stride: int):
    masked = sequences.clone()
    for patch_index in range(patch_mask.shape[-1]):
        active = patch_mask[..., patch_index]
        if not active.any():
            continue
        start = patch_index * int(patch_stride)
        end = min(start + int(patch_size), sequences.shape[-2])
        masked[..., start:end, :] = torch.where(
            active.unsqueeze(-1).unsqueeze(-1),
            torch.zeros_like(masked[..., start:end, :]),
            masked[..., start:end, :],
        )
    return masked


def _time_ordered_split_indices(sample_count: int, *, validation_fraction: float = 0.15):
    sample_count = max(int(sample_count), 0)
    if sample_count < 2:
        indices = np.arange(sample_count, dtype=np.int64)
        return indices, indices
    validation_count = min(
        max(int(round(sample_count * float(validation_fraction))), 1),
        sample_count - 1,
    )
    split_at = sample_count - validation_count
    return (
        np.arange(0, split_at, dtype=np.int64),
        np.arange(split_at, sample_count, dtype=np.int64),
    )


def _build_patch_mask(target, asset_mask, *, mask_ratio: float, generator):
    random_values = torch.rand(
        target.shape[:-1],
        generator=generator,
        device="cpu",
    ).to(target.device)
    patch_mask = (random_values < float(mask_ratio)) & asset_mask.unsqueeze(-1)
    if not patch_mask.any():
        valid_positions = asset_mask.nonzero(as_tuple=False)
        if len(valid_positions):
            first_batch, first_asset = valid_positions[0]
            patch_mask[first_batch, first_asset, 0] = True
    return patch_mask


def _reconstruction_loss(model, sequence, asset_mask, *, config, mask_ratio, generator):
    target = _patch_targets(
        sequence,
        patch_size=config.patch_size,
        patch_stride=config.patch_stride,
    )
    patch_mask = _build_patch_mask(
        target,
        asset_mask,
        mask_ratio=mask_ratio,
        generator=generator,
    )
    masked_sequence = _mask_patch_spans(
        sequence,
        patch_mask,
        patch_size=config.patch_size,
        patch_stride=config.patch_stride,
    )
    reconstructed = model(masked_sequence)
    error = (reconstructed - target) ** 2
    return error[patch_mask].mean(), int(patch_mask.sum().detach().cpu())


def pretrain_temporal_encoder(
    bundle: MultiAssetTensorBundle,
    *,
    config: MultiAssetTransformerConfig,
    epochs: int = 20,
    batch_size: int = 8,
    learning_rate: float = 3e-4,
    mask_ratio: float = 0.30,
    validation_fraction: float = 0.15,
    minimum_epochs: int = 5,
    early_stopping_patience: int = 4,
    early_stopping_min_delta: float = 1e-4,
    device: str = "auto",
    checkpoint_path: str = "trained_models/finance_multi_asset_transformer_pretrain.pt",
    seed: int = 17,
    progress_callback: Callable[[Mapping], None] | None = None,
) -> dict:
    resolved_device = _resolve_device(device)
    sequences = np.asarray(bundle.sequences, dtype=np.float32)
    asset_masks = np.asarray(bundle.asset_mask, dtype=bool)
    train_indices, validation_indices = _time_ordered_split_indices(
        len(sequences),
        validation_fraction=validation_fraction,
    )
    train_sequences = sequences[train_indices]
    train_masks = asset_masks[train_indices]
    valid_sequences = train_sequences[train_masks]
    mean = valid_sequences.reshape(-1, sequences.shape[-1]).mean(axis=0)
    std = valid_sequences.reshape(-1, sequences.shape[-1]).std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    scaled = (sequences - mean.reshape(1, 1, 1, -1)) / std.reshape(1, 1, 1, -1)
    train_dataset = TensorDataset(
        torch.tensor(scaled[train_indices], dtype=torch.float32),
        torch.tensor(asset_masks[train_indices], dtype=torch.bool),
    )
    validation_dataset = TensorDataset(
        torch.tensor(scaled[validation_indices], dtype=torch.float32),
        torch.tensor(asset_masks[validation_indices], dtype=torch.bool),
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=max(int(batch_size), 1),
        shuffle=True,
        generator=torch.Generator().manual_seed(int(seed)),
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=max(int(batch_size), 1),
        shuffle=False,
    )
    model = MaskedPatchPretrainer(config).to(resolved_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=1e-4)
    torch.manual_seed(int(seed))
    total_masked = 0
    epoch_count = max(int(epochs), 1)
    minimum_epochs = min(max(int(minimum_epochs), 1), epoch_count)
    patience = max(int(early_stopping_patience), 1)
    min_delta = max(float(early_stopping_min_delta), 0.0)
    best_validation_loss = float("inf")
    best_training_loss = float("inf")
    best_epoch = 0
    best_temporal_state = None
    epochs_without_improvement = 0
    stopped_early = False
    epoch_history = []
    epochs_completed = 0
    for epoch_index in range(epoch_count):
        model.train()
        training_loss_total = 0.0
        training_batch_count = 0
        training_mask_generator = torch.Generator().manual_seed(int(seed) + epoch_index + 1)
        for sequence, asset_mask in train_loader:
            sequence = sequence.to(resolved_device)
            asset_mask = asset_mask.to(resolved_device)
            optimizer.zero_grad()
            loss, masked_count = _reconstruction_loss(
                model,
                sequence,
                asset_mask,
                config=config,
                mask_ratio=mask_ratio,
                generator=training_mask_generator,
            )
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_masked += masked_count
            training_loss_total += float(loss.detach().cpu())
            training_batch_count += 1
        training_loss = training_loss_total / max(training_batch_count, 1)

        model.eval()
        validation_loss_total = 0.0
        validation_batch_count = 0
        validation_mask_generator = torch.Generator().manual_seed(int(seed) + 100_000)
        with torch.no_grad():
            for sequence, asset_mask in validation_loader:
                validation_loss, _ = _reconstruction_loss(
                    model,
                    sequence.to(resolved_device),
                    asset_mask.to(resolved_device),
                    config=config,
                    mask_ratio=mask_ratio,
                    generator=validation_mask_generator,
                )
                validation_loss_total += float(validation_loss.detach().cpu())
                validation_batch_count += 1
        validation_loss = validation_loss_total / max(validation_batch_count, 1)
        epochs_completed = epoch_index + 1
        improved = validation_loss < best_validation_loss - min_delta
        if improved or best_temporal_state is None:
            best_validation_loss = validation_loss
            best_training_loss = training_loss
            best_epoch = epochs_completed
            best_temporal_state = deepcopy(model.temporal.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
        epoch_history.append(
            {
                "epoch": epochs_completed,
                "training_loss": round(float(training_loss), 8),
                "validation_loss": round(float(validation_loss), 8),
                "best_validation_loss": round(float(best_validation_loss), 8),
            }
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "pretraining",
                    "detail": (
                        f"Pretraining epoch {epochs_completed}/{epoch_count}; "
                        f"train {training_loss:.4f}, validation {validation_loss:.4f}"
                    ),
                    "progress_pct": round(epochs_completed / epoch_count * 100.0, 1),
                    "epoch": epochs_completed,
                    "epochs": epoch_count,
                    "loss": round(float(training_loss), 6),
                    "training_loss": round(float(training_loss), 6),
                    "validation_loss": round(float(validation_loss), 6),
                    "best_validation_loss": round(float(best_validation_loss), 6),
                    "best_epoch": best_epoch,
                    "device": str(resolved_device),
                }
            )
        if epochs_completed >= minimum_epochs and epochs_without_improvement >= patience:
            stopped_early = True
            break

    if stopped_early and progress_callback is not None:
        progress_callback(
            {
                "stage": "pretraining",
                "detail": (
                    f"Pretraining stopped early after epoch {epochs_completed}; "
                    f"best epoch {best_epoch}, validation {best_validation_loss:.4f}"
                ),
                "progress_pct": 100.0,
                "epoch": epochs_completed,
                "epochs": epoch_count,
                "loss": round(float(best_training_loss), 6),
                "training_loss": round(float(best_training_loss), 6),
                "validation_loss": round(float(best_validation_loss), 6),
                "best_validation_loss": round(float(best_validation_loss), 6),
                "best_epoch": best_epoch,
                "epochs_completed": epochs_completed,
                "stopped_early": True,
                "device": str(resolved_device),
            }
        )

    target_path = Path(checkpoint_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_id": "finance_multi_asset_transformer_pretrain",
        "trained_at": datetime.now().isoformat(),
        "task": "masked_patch_reconstruction",
        "config": config.__dict__,
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "loss": best_training_loss,
        "training_loss": best_training_loss,
        "validation_loss": best_validation_loss,
        "best_epoch": best_epoch,
        "epochs_completed": epochs_completed,
        "stopped_early": stopped_early,
        "epoch_history": epoch_history,
        "training_sample_count": len(train_indices),
        "validation_sample_count": len(validation_indices),
        "masked_patch_count": total_masked,
    }
    torch.save(
        {
            "temporal_state_dict": best_temporal_state,
            "metadata": metadata,
        },
        target_path,
    )
    return {
        "checkpoint_path": str(target_path),
        "device": str(resolved_device),
        "loss": best_training_loss,
        "training_loss": best_training_loss,
        "validation_loss": best_validation_loss,
        "best_epoch": best_epoch,
        "epochs_completed": epochs_completed,
        "stopped_early": stopped_early,
        "epoch_history": epoch_history,
        "training_sample_count": len(train_indices),
        "validation_sample_count": len(validation_indices),
        "masked_patch_count": total_masked,
    }
