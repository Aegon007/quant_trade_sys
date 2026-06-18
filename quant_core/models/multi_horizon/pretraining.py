from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def pretrain_temporal_encoder(
    bundle: MultiAssetTensorBundle,
    *,
    config: MultiAssetTransformerConfig,
    epochs: int = 5,
    batch_size: int = 8,
    learning_rate: float = 3e-4,
    mask_ratio: float = 0.30,
    device: str = "auto",
    checkpoint_path: str = "trained_models/finance_multi_asset_transformer_pretrain.pt",
    seed: int = 17,
) -> dict:
    resolved_device = _resolve_device(device)
    sequences = np.asarray(bundle.sequences, dtype=np.float32)
    valid_sequences = sequences[np.asarray(bundle.asset_mask, dtype=bool)]
    mean = valid_sequences.reshape(-1, sequences.shape[-1]).mean(axis=0)
    std = valid_sequences.reshape(-1, sequences.shape[-1]).std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    scaled = (sequences - mean.reshape(1, 1, 1, -1)) / std.reshape(1, 1, 1, -1)
    dataset = TensorDataset(
        torch.tensor(scaled, dtype=torch.float32),
        torch.tensor(bundle.asset_mask, dtype=torch.bool),
    )
    generator = torch.Generator().manual_seed(int(seed))
    loader = DataLoader(
        dataset,
        batch_size=max(int(batch_size), 1),
        shuffle=True,
        generator=generator,
    )
    model = MaskedPatchPretrainer(config).to(resolved_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=1e-4)
    torch.manual_seed(int(seed))
    total_masked = 0
    final_loss = 0.0
    model.train()
    for _ in range(max(int(epochs), 1)):
        loss_total = 0.0
        batch_count = 0
        for sequence, asset_mask in loader:
            sequence = sequence.to(resolved_device)
            asset_mask = asset_mask.to(resolved_device)
            target = _patch_targets(
                sequence,
                patch_size=config.patch_size,
                patch_stride=config.patch_stride,
            )
            patch_mask = (
                torch.rand(target.shape[:-1], device=resolved_device) < float(mask_ratio)
            ) & asset_mask.unsqueeze(-1)
            if not patch_mask.any():
                valid_positions = asset_mask.nonzero(as_tuple=False)
                if len(valid_positions):
                    first_batch, first_asset = valid_positions[0]
                    patch_mask[first_batch, first_asset, 0] = True
            masked_sequence = _mask_patch_spans(
                sequence,
                patch_mask,
                patch_size=config.patch_size,
                patch_stride=config.patch_stride,
            )
            optimizer.zero_grad()
            reconstructed = model(masked_sequence)
            error = (reconstructed - target) ** 2
            loss = error[patch_mask].mean()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            masked_count = int(patch_mask.sum().detach().cpu())
            total_masked += masked_count
            loss_total += float(loss.detach().cpu())
            batch_count += 1
        final_loss = loss_total / max(batch_count, 1)

    target_path = Path(checkpoint_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_id": "finance_multi_asset_transformer_pretrain",
        "trained_at": datetime.now().isoformat(),
        "task": "masked_patch_reconstruction",
        "config": config.__dict__,
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "loss": final_loss,
        "masked_patch_count": total_masked,
    }
    torch.save(
        {
            "temporal_state_dict": model.temporal.state_dict(),
            "metadata": metadata,
        },
        target_path,
    )
    return {
        "checkpoint_path": str(target_path),
        "device": str(resolved_device),
        "loss": final_loss,
        "masked_patch_count": total_masked,
    }
