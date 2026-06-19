from __future__ import annotations

from dataclasses import dataclass

try:
    import torch
    from torch import nn
    from torch.nn import functional as F
except ImportError:  # pragma: no cover - requirements include torch
    torch = None
    nn = None
    F = None


@dataclass(frozen=True)
class MultiAssetTransformerConfig:
    feature_count: int
    horizon_count: int = 3
    d_model: int = 64
    temporal_layers: int = 2
    cross_asset_layers: int = 2
    attention_heads: int = 4
    feedforward_multiplier: int = 4
    dropout: float = 0.1
    patch_size: int = 10
    patch_stride: int = 5
    market_context_size: int = 5
    expert_count: int = 4
    top_k_experts: int = 2
    timing_state_count: int = 5


class PatchTemporalEncoder(nn.Module):
    def __init__(self, config: MultiAssetTransformerConfig):
        super().__init__()
        self.patch = nn.Conv1d(
            config.feature_count,
            config.d_model,
            kernel_size=config.patch_size,
            stride=config.patch_stride,
        )
        layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.attention_heads,
            dim_feedforward=config.d_model * config.feedforward_multiplier,
            dropout=config.dropout,
            batch_first=True,
            norm_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=config.temporal_layers)
        self.norm = nn.LayerNorm(config.d_model)

    def encode_tokens(self, sequences):
        batch_size, asset_count, time_steps, feature_count = sequences.shape
        flattened = sequences.reshape(batch_size * asset_count, time_steps, feature_count).transpose(1, 2)
        tokens = self.patch(flattened).transpose(1, 2)
        return self.encoder(tokens), batch_size, asset_count

    def forward(self, sequences):
        encoded, batch_size, asset_count = self.encode_tokens(sequences)
        pooled = self.norm(encoded.mean(dim=1))
        return pooled.reshape(batch_size, asset_count, -1)


class SparseRegimeMoE(nn.Module):
    def __init__(self, config: MultiAssetTransformerConfig):
        super().__init__()
        self.top_k = max(1, min(config.top_k_experts, config.expert_count))
        self.router = nn.Linear(config.d_model, config.expert_count)
        self.experts = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Linear(config.d_model, config.d_model * 2),
                    nn.GELU(),
                    nn.Dropout(config.dropout),
                    nn.Linear(config.d_model * 2, config.d_model),
                )
                for _ in range(config.expert_count)
            ]
        )
        self.norm = nn.LayerNorm(config.d_model)

    def forward(self, representation):
        logits = self.router(representation)
        top_values, top_indices = torch.topk(logits, self.top_k, dim=-1)
        sparse_logits = torch.full_like(logits, float("-inf"))
        sparse_logits.scatter_(-1, top_indices, top_values)
        weights = torch.softmax(sparse_logits, dim=-1)
        expert_outputs = torch.stack([expert(representation) for expert in self.experts], dim=-2)
        mixed = torch.sum(expert_outputs * weights.unsqueeze(-1), dim=-2)
        return self.norm(representation + mixed), weights


class FinanceMultiAssetTransformer(nn.Module):
    """Patch temporal encoder + cross-asset attention + sparse regime MoE."""

    def __init__(self, config: MultiAssetTransformerConfig):
        if nn is None:
            raise RuntimeError("PyTorch is required for FinanceMultiAssetTransformer")
        super().__init__()
        self.config = config
        self.temporal = PatchTemporalEncoder(config)
        self.market_projection = nn.Sequential(
            nn.Linear(config.market_context_size, config.d_model),
            nn.GELU(),
            nn.LayerNorm(config.d_model),
        )
        self.variable_gate = nn.Sequential(
            nn.Linear(config.d_model * 2, config.d_model),
            nn.GELU(),
            nn.Linear(config.d_model, config.d_model),
            nn.Sigmoid(),
        )
        layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.attention_heads,
            dim_feedforward=config.d_model * config.feedforward_multiplier,
            dropout=config.dropout,
            batch_first=True,
            norm_first=True,
            activation="gelu",
        )
        self.cross_asset = nn.TransformerEncoder(layer, num_layers=config.cross_asset_layers)
        self.moe = SparseRegimeMoE(config)
        self.rank_head = nn.Linear(config.d_model, config.horizon_count)
        self.positive_return_head = nn.Linear(config.d_model, config.horizon_count)
        self.risk_free_outperformance_head = nn.Linear(config.d_model, config.horizon_count)
        self.market_outperformance_head = nn.Linear(config.d_model, config.horizon_count)
        self.quantile_head = nn.Linear(config.d_model, config.horizon_count * 3)
        self.adverse_head = nn.Linear(config.d_model, config.horizon_count)
        self.favorable_head = nn.Linear(config.d_model, config.horizon_count)
        self.timing_head = nn.Linear(config.d_model, config.timing_state_count)

    def forward(self, sequences, *, market_context=None, asset_mask=None):
        representation = self.temporal(sequences)
        batch_size, asset_count, _ = representation.shape
        if market_context is None:
            market_context = representation.new_zeros(batch_size, self.config.market_context_size)
        market_token = self.market_projection(market_context).unsqueeze(1).expand(-1, asset_count, -1)
        gate = self.variable_gate(torch.cat([representation, market_token], dim=-1))
        representation = representation * gate + market_token * (1.0 - gate)
        padding_mask = None if asset_mask is None else ~asset_mask.bool()
        representation = self.cross_asset(representation, src_key_padding_mask=padding_mask)
        representation, expert_weights = self.moe(representation)

        quantile_raw = self.quantile_head(representation).reshape(
            batch_size,
            asset_count,
            self.config.horizon_count,
            3,
        )
        p10 = quantile_raw[..., 0]
        p50 = p10 + F.softplus(quantile_raw[..., 1])
        p90 = p50 + F.softplus(quantile_raw[..., 2])
        return {
            "rank_scores": self.rank_head(representation),
            "positive_return_logits": self.positive_return_head(representation),
            "risk_free_outperformance_logits": self.risk_free_outperformance_head(representation),
            "market_outperformance_logits": self.market_outperformance_head(representation),
            "return_quantiles": torch.stack([p10, p50, p90], dim=-1),
            "adverse_excursion": -F.softplus(self.adverse_head(representation)),
            "favorable_excursion": F.softplus(self.favorable_head(representation)),
            "timing_logits": self.timing_head(representation),
            "expert_weights": expert_weights,
            "representation": representation,
        }
