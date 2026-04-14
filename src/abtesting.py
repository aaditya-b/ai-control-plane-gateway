"""A/B testing with consistent hashing for deterministic group assignment."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .types import ExperimentConfig


@dataclass
class GroupStats:
    sample_size: int = 0
    total_latency: float = 0.0
    total_cost: float = 0.0
    total_quality: float = 0.0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.sample_size if self.sample_size else 0.0

    @property
    def avg_cost(self) -> float:
        return self.total_cost / self.sample_size if self.sample_size else 0.0

    @property
    def avg_quality(self) -> float:
        return self.total_quality / self.sample_size if self.sample_size else 0.0


class ABTestManager:
    """Manages A/B test experiments with consistent-hash assignment."""

    def __init__(self, experiments: list[ExperimentConfig] | None = None) -> None:
        self._experiments: dict[str, ExperimentConfig] = {}
        # group key = (experiment_name, group_label)
        self._results: dict[tuple[str, str], GroupStats] = {}

        for exp in experiments or []:
            self._experiments[exp.name] = exp

    # ── Assignment ──────────────────────────────────────────────────

    def assign(self, experiment_name: str, user_id: str) -> tuple[str, str]:
        """Return (model, group_label) using SHA256 consistent hashing.

        The group label is the model name (e.g. "gpt-4o").
        """
        exp = self._experiments.get(experiment_name)
        if exp is None or not exp.enabled or not exp.models:
            return "", ""

        # Deterministic hash -> bucket
        digest = hashlib.sha256(
            f"{experiment_name}:{user_id}".encode()
        ).hexdigest()
        hash_value = int(digest, 16)

        # Build cumulative split
        splits = exp.traffic_split if exp.traffic_split else [1.0 / len(exp.models)] * len(exp.models)
        total = sum(splits)
        normalised = hash_value % 10_000  # 0..9999
        cumulative = 0.0
        for model, split in zip(exp.models, splits):
            cumulative += (split / total) * 10_000
            if normalised < cumulative:
                return model, model
        # Fallback to last model
        return exp.models[-1], exp.models[-1]

    # ── Result recording ────────────────────────────────────────────

    def record_result(
        self,
        experiment_name: str,
        group: str,
        *,
        latency: float = 0.0,
        cost: float = 0.0,
        quality: float = 0.0,
    ) -> None:
        key = (experiment_name, group)
        if key not in self._results:
            self._results[key] = GroupStats()
        stats = self._results[key]
        stats.sample_size += 1
        stats.total_latency += latency
        stats.total_cost += cost
        stats.total_quality += quality

    # ── Reporting ───────────────────────────────────────────────────

    def get_results(self, experiment_name: str) -> dict[str, dict[str, float]]:
        """Return per-group statistics for an experiment."""
        output: dict[str, dict[str, float]] = {}
        for (exp_name, group), stats in self._results.items():
            if exp_name != experiment_name:
                continue
            output[group] = {
                "sample_size": float(stats.sample_size),
                "avg_latency": stats.avg_latency,
                "avg_cost": stats.avg_cost,
                "avg_quality": stats.avg_quality,
                "total_cost": stats.total_cost,
            }
        return output

    # ── Management helpers ──────────────────────────────────────────

    def add_experiment(self, experiment: ExperimentConfig) -> None:
        self._experiments[experiment.name] = experiment

    @property
    def experiments(self) -> dict[str, ExperimentConfig]:
        return dict(self._experiments)
