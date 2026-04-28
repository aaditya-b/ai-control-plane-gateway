"""Budget management with per-user and per-team spending limits."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .config import BudgetConfig

logger = logging.getLogger("gateway.budget")

_SECONDS_PER_DAY   = 86_400.0
_SECONDS_PER_MONTH = 86_400.0 * 30   # approximate


@dataclass
class BudgetStatus:
    user_id: str = ""
    team_id: str = ""
    daily_cost: float = 0.0
    monthly_cost: float = 0.0
    daily_tokens: int = 0
    monthly_tokens: int = 0
    daily_limit: float = 0.0
    monthly_limit: float = 0.0
    allowed: bool = True


@dataclass
class _UsageRecord:
    daily_cost: float = 0.0
    monthly_cost: float = 0.0
    daily_tokens: int = 0
    monthly_tokens: int = 0
    last_daily_reset: float = field(default_factory=time.time)
    last_monthly_reset: float = field(default_factory=time.time)


class BudgetManager:
    """Enforce per-user and per-team spending limits."""

    def __init__(self, config: BudgetConfig) -> None:
        self._config = config
        self._user_usage: dict[str, _UsageRecord] = {}
        self._team_usage: dict[str, _UsageRecord] = {}
        self._lock = asyncio.Lock()

    # ── Public API ──────────────────────────────────────────────────────────

    async def check_budget(
        self,
        user_id: str,
        team_id: str,
        estimated_cost: float,
    ) -> tuple[bool, BudgetStatus]:
        async with self._lock:
            user_rec = self._get_user(user_id)
            self._auto_reset(user_rec)

            daily_limit   = self._config.user_budgets.get(user_id, self._config.default_daily_limit)
            monthly_limit = self._config.team_budgets.get(team_id, self._config.default_monthly_limit)

            allowed = True
            if user_rec.daily_cost + estimated_cost > daily_limit:
                allowed = False
            if user_rec.monthly_cost + estimated_cost > monthly_limit:
                allowed = False

            if team_id:
                team_rec   = self._get_team(team_id)
                self._auto_reset(team_rec)
                team_limit = self._config.team_budgets.get(team_id, self._config.default_monthly_limit)
                if team_rec.monthly_cost + estimated_cost > team_limit:
                    allowed = False

            status = BudgetStatus(
                user_id=user_id,
                team_id=team_id,
                daily_cost=user_rec.daily_cost,
                monthly_cost=user_rec.monthly_cost,
                daily_tokens=user_rec.daily_tokens,
                monthly_tokens=user_rec.monthly_tokens,
                daily_limit=daily_limit,
                monthly_limit=monthly_limit,
                allowed=allowed,
            )
            return allowed, status

    async def record_usage(
        self,
        user_id: str,
        team_id: str,
        cost: float,
        tokens: int,
    ) -> None:
        async with self._lock:
            user_rec = self._get_user(user_id)
            self._auto_reset(user_rec)
            user_rec.daily_cost    += cost
            user_rec.monthly_cost  += cost
            user_rec.daily_tokens  += tokens
            user_rec.monthly_tokens += tokens

            if team_id:
                team_rec   = self._get_team(team_id)
                self._auto_reset(team_rec)
                team_rec.daily_cost    += cost
                team_rec.monthly_cost  += cost
                team_rec.daily_tokens  += tokens
                team_rec.monthly_tokens += tokens

    async def get_usage(self, user_id: str) -> BudgetStatus:
        async with self._lock:
            rec           = self._get_user(user_id)
            self._auto_reset(rec)
            daily_limit   = self._config.user_budgets.get(user_id, self._config.default_daily_limit)
            monthly_limit = self._config.default_monthly_limit
            return BudgetStatus(
                user_id=user_id,
                daily_cost=rec.daily_cost,
                monthly_cost=rec.monthly_cost,
                daily_tokens=rec.daily_tokens,
                monthly_tokens=rec.monthly_tokens,
                daily_limit=daily_limit,
                monthly_limit=monthly_limit,
                allowed=True,
            )

    # ── Internals ───────────────────────────────────────────────────────────

    def _get_user(self, user_id: str) -> _UsageRecord:
        if user_id not in self._user_usage:
            self._user_usage[user_id] = _UsageRecord()
        return self._user_usage[user_id]

    def _get_team(self, team_id: str) -> _UsageRecord:
        if team_id not in self._team_usage:
            self._team_usage[team_id] = _UsageRecord()
        return self._team_usage[team_id]

    @staticmethod
    def _auto_reset(record: _UsageRecord) -> None:
        now = time.time()
        if now - record.last_daily_reset >= _SECONDS_PER_DAY:
            record.daily_cost   = 0.0
            record.daily_tokens = 0
            record.last_daily_reset = now
        if now - record.last_monthly_reset >= _SECONDS_PER_MONTH:
            record.monthly_cost   = 0.0
            record.monthly_tokens = 0
            record.last_monthly_reset = now
