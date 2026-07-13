"""Fail-closed runtime adapter selection for fixture and live modes."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from mandate_worker.fixtures import (
    DEMO_BACKENDS,
    AdapterCapability,
    FixtureCatalog,
)


class RuntimeConfigurationError(ValueError):
    """Runtime provider selection is invalid or unsafe."""


SELECTOR_ENV: Final[Mapping[AdapterCapability, str]] = MappingProxyType(
    {
        AdapterCapability.SEARCH: "PROVIDER_SEARCH",
        AdapterCapability.PAGE_FETCHER: "PROVIDER_PAGE_FETCHER",
        AdapterCapability.COMPANY_DATA: "PROVIDER_COMPANY_DATA",
        AdapterCapability.REGULATORY: "PROVIDER_REGULATORY",
        AdapterCapability.LITIGATION: "PROVIDER_LITIGATION",
        AdapterCapability.MODEL: "PROVIDER_MODEL",
        AdapterCapability.QUEUE: "QUEUE_BACKEND",
        AdapterCapability.STORAGE: "STORAGE_BACKEND",
        AdapterCapability.EMAIL: "EMAIL_PROVIDER",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeAdapterPlan:
    demo_mode: bool
    bindings: Mapping[AdapterCapability, str]
    catalog: FixtureCatalog | None = field(default=None, repr=False)
    overridden_selectors: tuple[str, ...] = ()

    @property
    def fixture_revision(self) -> str | None:
        return self.catalog.manifest.revision if self.catalog is not None else None

    @property
    def zero_spend(self) -> bool:
        return self.demo_mode and self.catalog is not None and self.bindings == DEMO_BACKENDS


def build_runtime_adapter_plan(
    environ: Mapping[str, str] | None = None,
    fixture_root: Path | None = None,
) -> RuntimeAdapterPlan:
    environment = os.environ if environ is None else environ
    raw_demo_mode = environment.get("DEMO_MODE", "0")
    if raw_demo_mode not in {"0", "1"}:
        raise RuntimeConfigurationError("DEMO_MODE must be exactly '0' or '1'")

    if raw_demo_mode == "1":
        catalog = FixtureCatalog.load(fixture_root)
        overridden = tuple(
            sorted(
                selector
                for capability, selector in SELECTOR_ENV.items()
                if selector in environment and environment[selector] != DEMO_BACKENDS[capability]
            )
        )
        plan = RuntimeAdapterPlan(
            demo_mode=True,
            bindings=MappingProxyType(dict(DEMO_BACKENDS)),
            catalog=catalog,
            overridden_selectors=overridden,
        )
        if not plan.zero_spend:
            raise RuntimeConfigurationError("demo mode did not resolve to zero-spend adapters")
        return plan

    return RuntimeAdapterPlan(
        demo_mode=False,
        bindings=MappingProxyType(
            {
                capability: environment.get(selector, "unconfigured")
                for capability, selector in SELECTOR_ENV.items()
            }
        ),
    )
