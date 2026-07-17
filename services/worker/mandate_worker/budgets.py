"""Hard per-job and per-stage research budgets.

The ledger is deliberately independent of queue persistence.  Callers can use
it in fixtures today and persist its counters with job checkpoints later.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BudgetDecision(StrEnum):
    CONTINUE = "continue"
    STOP_TO_QUESTIONS = "stop_to_questions"
    RETRY_WAIT = "retry_wait"
    FAILED_RESTORED = "failed_restored"


class BudgetExceeded(RuntimeError):
    """Stable hard-cap failure without source, prompt or secret text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StageBudgetSlice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    searches: int = Field(ge=1, le=45)
    pages: int = Field(ge=1, le=100)
    model_calls: int = Field(ge=1, le=16)
    input_tokens: int = Field(ge=1, le=350_000)
    output_tokens: int = Field(ge=1, le=60_000)
    cost_inr: Decimal = Field(gt=0)
    wall_clock_seconds: int = Field(ge=1, le=1_200)


class BudgetProfile(BaseModel):
    """The documented ``mvp-standard`` profile from QUEUE-AND-JOB-SPEC §8."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,40}$")
    searches: int = Field(gt=0)
    pages: int = Field(gt=0)
    browser_seconds: int = Field(gt=0)
    frontier_model_calls: int = Field(gt=0)
    model_input_tokens: int = Field(gt=0)
    model_output_tokens: int = Field(gt=0)
    model_cost_inr: Decimal = Field(gt=0)
    wall_clock_seconds: int = Field(gt=0)
    stage_retries: int = Field(ge=0)
    redeliveries: int = Field(ge=0)
    concurrent_heavy_jobs: int = Field(gt=0)
    stage_slices: tuple[StageBudgetSlice, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def slices_fit_within_job(self) -> BudgetProfile:
        if len({item.stage for item in self.stage_slices}) != len(self.stage_slices):
            raise ValueError("budget stage keys must be unique")
        if sum(item.searches for item in self.stage_slices) > self.searches:
            raise ValueError("stage search budgets exceed job cap")
        if sum(item.pages for item in self.stage_slices) > self.pages:
            raise ValueError("stage page budgets exceed job cap")
        if sum(item.input_tokens for item in self.stage_slices) > self.model_input_tokens:
            raise ValueError("stage input-token budgets exceed job cap")
        if sum(item.output_tokens for item in self.stage_slices) > self.model_output_tokens:
            raise ValueError("stage output-token budgets exceed job cap")
        if sum(item.cost_inr for item in self.stage_slices) > self.model_cost_inr:
            raise ValueError("stage cost budgets exceed job cap")
        if sum(item.wall_clock_seconds for item in self.stage_slices) > self.wall_clock_seconds:
            raise ValueError("stage wall-clock budgets exceed job cap")
        return self

    @classmethod
    def mvp_standard(cls) -> BudgetProfile:
        slices = (
            StageBudgetSlice(
                stage="research_business",
                searches=8,
                pages=16,
                model_calls=1,
                input_tokens=50_000,
                output_tokens=8_000,
                cost_inr=Decimal("20"),
                wall_clock_seconds=200,
            ),
            StageBudgetSlice(
                stage="research_industry",
                searches=7,
                pages=15,
                model_calls=1,
                input_tokens=50_000,
                output_tokens=8_000,
                cost_inr=Decimal("20"),
                wall_clock_seconds=200,
            ),
            StageBudgetSlice(
                stage="research_competitors",
                searches=8,
                pages=16,
                model_calls=1,
                input_tokens=50_000,
                output_tokens=8_000,
                cost_inr=Decimal("20"),
                wall_clock_seconds=200,
            ),
            StageBudgetSlice(
                stage="research_corporate",
                searches=10,
                pages=20,
                model_calls=1,
                input_tokens=50_000,
                output_tokens=8_000,
                cost_inr=Decimal("20"),
                wall_clock_seconds=200,
            ),
            StageBudgetSlice(
                stage="research_regulatory",
                searches=7,
                pages=13,
                model_calls=1,
                input_tokens=50_000,
                output_tokens=8_000,
                cost_inr=Decimal("20"),
                wall_clock_seconds=200,
            ),
            StageBudgetSlice(
                stage="research_public_risk",
                searches=5,
                pages=12,
                model_calls=1,
                input_tokens=50_000,
                output_tokens=8_000,
                cost_inr=Decimal("20"),
                wall_clock_seconds=200,
            ),
        )
        return cls(
            name="mvp-standard",
            searches=45,
            pages=100,
            browser_seconds=180,
            frontier_model_calls=4,
            model_input_tokens=350_000,
            model_output_tokens=60_000,
            model_cost_inr=Decimal("120"),
            wall_clock_seconds=1_200,
            stage_retries=2,
            redeliveries=3,
            concurrent_heavy_jobs=2,
            stage_slices=slices,
        )

    def slice_for(self, stage: str) -> StageBudgetSlice:
        for item in self.stage_slices:
            if item.stage == stage:
                return item
        raise BudgetExceeded("budget_stage_unconfigured")


@dataclass(slots=True)
class BudgetUsage:
    searches: int = 0
    pages: int = 0
    model_calls: int = 0
    frontier_model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_inr: Decimal = Decimal(0)
    wall_clock_seconds: int = 0


class BudgetLedger:
    """Mutable request-local ledger; every increment is checked before commit."""

    def __init__(self, profile: BudgetProfile) -> None:
        self.profile = profile
        self.usage = BudgetUsage()
        self.stage_usage: dict[str, BudgetUsage] = {}
        self.current_stage: str | None = None

    def start_stage(self, stage: str) -> StageBudgetSlice:
        selected = self.profile.slice_for(stage)
        self.current_stage = stage
        self.stage_usage.setdefault(stage, BudgetUsage())
        return selected

    def consume_search(self, amount: int = 1) -> None:
        self._consume("searches", amount, self.profile.searches, "budget_searches_exhausted")

    def consume_page(self, amount: int = 1) -> None:
        self._consume("pages", amount, self.profile.pages, "budget_pages_exhausted")

    def consume_model_call(self, *, frontier: bool = False, amount: int = 1) -> None:
        if amount < 0 or (
            frontier
            and self.usage.frontier_model_calls + amount > self.profile.frontier_model_calls
        ):
            raise BudgetExceeded(
                "budget_frontier_model_calls_exhausted" if frontier else "budget_increment_invalid"
            )
        self._consume(
            "model_calls",
            amount,
            sum(item.model_calls for item in self.profile.stage_slices),
            "budget_model_calls_exhausted",
        )
        if frontier:
            self.usage.frontier_model_calls += amount

    def consume_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self._check(
            "input_tokens",
            input_tokens,
            self.profile.model_input_tokens,
            "budget_input_tokens_exhausted",
        )
        self._check(
            "output_tokens",
            output_tokens,
            self.profile.model_output_tokens,
            "budget_output_tokens_exhausted",
        )
        self._consume(
            "input_tokens",
            input_tokens,
            self.profile.model_input_tokens,
            "budget_input_tokens_exhausted",
        )
        self._consume(
            "output_tokens",
            output_tokens,
            self.profile.model_output_tokens,
            "budget_output_tokens_exhausted",
        )

    def consume_cost(self, cost_inr: Decimal) -> None:
        if cost_inr < 0 or self.usage.cost_inr + cost_inr > self.profile.model_cost_inr:
            raise BudgetExceeded("budget_model_cost_exhausted")
        stage = self._stage()
        stage_limit = self._stage_cap("cost_inr")
        if stage.cost_inr + cost_inr > stage_limit:
            raise BudgetExceeded("budget_stage_cost_exhausted")
        self.usage.cost_inr += cost_inr
        stage.cost_inr += cost_inr

    def consume_wall_clock(self, seconds: int) -> None:
        self._consume(
            "wall_clock_seconds",
            seconds,
            self.profile.wall_clock_seconds,
            "budget_wall_clock_exhausted",
        )

    def stopping_decision(
        self, *, mandatory_fields_supported: bool, transient: bool
    ) -> BudgetDecision:
        if self.is_exhausted:
            if mandatory_fields_supported:
                return BudgetDecision.STOP_TO_QUESTIONS
            if transient:
                return BudgetDecision.RETRY_WAIT
            return BudgetDecision.FAILED_RESTORED
        return BudgetDecision.CONTINUE

    @property
    def is_exhausted(self) -> bool:
        return (
            self.usage.searches >= self.profile.searches
            or self.usage.pages >= self.profile.pages
            or self.usage.model_calls >= sum(item.model_calls for item in self.profile.stage_slices)
            or self.usage.input_tokens >= self.profile.model_input_tokens
            or self.usage.output_tokens >= self.profile.model_output_tokens
            or self.usage.cost_inr >= self.profile.model_cost_inr
            or self.usage.wall_clock_seconds >= self.profile.wall_clock_seconds
        )

    def _consume(self, field: str, amount: int, job_limit: int, code: str) -> None:
        self._check(field, amount, job_limit, code)
        stage = self._stage()
        setattr(self.usage, field, getattr(self.usage, field) + amount)
        setattr(stage, field, getattr(stage, field) + amount)

    def _check(self, field: str, amount: int, job_limit: int, code: str) -> None:
        if amount < 0:
            raise BudgetExceeded("budget_increment_invalid")
        stage = self._stage()
        stage_limit = self._stage_cap(field)
        if getattr(self.usage, field) + amount > job_limit:
            raise BudgetExceeded(code)
        if getattr(stage, field) + amount > stage_limit:
            raise BudgetExceeded(f"budget_stage_{field}_exhausted")

    def _stage(self) -> BudgetUsage:
        if self.current_stage is None:
            raise BudgetExceeded("budget_stage_not_started")
        return self.stage_usage[self.current_stage]

    def _stage_cap(self, field: str) -> int | Decimal:
        selected = self.profile.slice_for(self.current_stage or "")
        return cast(int | Decimal, getattr(selected, field))


__all__ = [
    "BudgetDecision",
    "BudgetExceeded",
    "BudgetLedger",
    "BudgetProfile",
    "BudgetUsage",
    "StageBudgetSlice",
]
