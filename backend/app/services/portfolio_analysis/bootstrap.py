from __future__ import annotations

import numpy as np


def joint_block_bootstrap(history: np.ndarray, days: int, simulations: int, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """Draw contiguous row blocks jointly across every asset."""
    if history.ndim != 2 or len(history) < block_length:
        raise ValueError("联合历史样本不足以执行区块自助法")
    blocks = (days + block_length - 1) // block_length
    starts = rng.integers(0, len(history) - block_length + 1, size=(simulations, blocks))
    offsets = np.arange(block_length)
    indices = (starts[..., None] + offsets).reshape(simulations, -1)[:, :days]
    return history[indices]
