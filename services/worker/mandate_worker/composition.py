from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from mandate_worker.entity_resolution.task import (
    EntityResolutionTaskHandler,
    build_entity_resolution_task_loop,
)
from mandate_worker.fixtures import AdapterCapability
from mandate_worker.light_tasks import LightTaskLoop, LightTaskLoopConfig
from mandate_worker.preliminary_research import (
    PreliminaryResearchTaskHandler,
    build_preliminary_research_task_loop,
)
from mandate_worker.queue import QueueAdapter
from mandate_worker.runtime import SELECTOR_ENV, RuntimeConfigurationError

LIGHT_TASK_SHUTDOWN_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class LightTaskRuntimeConfiguration:
    enabled: bool
    queue_backend: str
    requested_queue_backend: str


@dataclass(frozen=True, slots=True)
class LightTaskRuntimeDependencies:
    queue: QueueAdapter
    preliminary_research_handler: PreliminaryResearchTaskHandler
    entity_resolution_handler: EntityResolutionTaskHandler
    preliminary_research_config: LightTaskLoopConfig | None = None
    entity_resolution_config: LightTaskLoopConfig | None = None


LightTaskDependenciesFactory = Callable[[], LightTaskRuntimeDependencies]


@dataclass(frozen=True, slots=True)
class LightTaskLoopBundle:
    preliminary_research: LightTaskLoop
    entity_resolution: LightTaskLoop


@dataclass(slots=True)
class LightTaskLoopSupervisor:
    loops: LightTaskLoopBundle
    stop_event: asyncio.Event
    tasks: tuple[asyncio.Task[None], asyncio.Task[None]]

    @classmethod
    def start(cls, loops: LightTaskLoopBundle) -> LightTaskLoopSupervisor:
        stop_event = asyncio.Event()
        return cls(
            loops=loops,
            stop_event=stop_event,
            tasks=(
                asyncio.create_task(
                    loops.preliminary_research.run_forever(stop_event),
                    name="mandate-light-task-preliminary-research",
                ),
                asyncio.create_task(
                    loops.entity_resolution.run_forever(stop_event),
                    name="mandate-light-task-entity-resolution",
                ),
            ),
        )

    async def stop(self) -> None:
        self.stop_event.set()
        pending = {task for task in self.tasks if not task.done()}
        if pending:
            _, pending = await asyncio.wait(
                pending,
                timeout=LIGHT_TASK_SHUTDOWN_TIMEOUT_SECONDS,
            )
        for task in pending:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


@dataclass(frozen=True, slots=True)
class LightTaskRuntime:
    configuration: LightTaskRuntimeConfiguration
    supervisor: LightTaskLoopSupervisor | None = None

    @property
    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return () if self.supervisor is None else self.supervisor.tasks

    async def stop(self) -> None:
        if self.supervisor is not None:
            await self.supervisor.stop()


def resolve_light_task_runtime_configuration(
    *,
    environ: Mapping[str, str] | None = None,
    dependencies_factory: LightTaskDependenciesFactory | None = None,
) -> LightTaskRuntimeConfiguration:
    environment = os.environ if environ is None else environ
    requested_queue_backend = environment.get(
        SELECTOR_ENV[AdapterCapability.QUEUE],
        "unconfigured",
    )
    if dependencies_factory is None:
        return LightTaskRuntimeConfiguration(
            enabled=False,
            queue_backend="unconfigured",
            requested_queue_backend=requested_queue_backend,
        )
    return LightTaskRuntimeConfiguration(
        enabled=True,
        queue_backend=requested_queue_backend
        if requested_queue_backend != "unconfigured"
        else "injected",
        requested_queue_backend=requested_queue_backend,
    )


def build_light_task_loop_bundle(
    dependencies: LightTaskRuntimeDependencies,
) -> LightTaskLoopBundle:
    return LightTaskLoopBundle(
        preliminary_research=build_preliminary_research_task_loop(
            dependencies.queue,
            dependencies.preliminary_research_handler,
            config=dependencies.preliminary_research_config,
        ),
        entity_resolution=build_entity_resolution_task_loop(
            dependencies.queue,
            dependencies.entity_resolution_handler,
            config=dependencies.entity_resolution_config,
        ),
    )


def start_light_task_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    dependencies_factory: LightTaskDependenciesFactory | None = None,
) -> LightTaskRuntime:
    configuration = resolve_light_task_runtime_configuration(
        environ=environ,
        dependencies_factory=dependencies_factory,
    )
    if not configuration.enabled:
        return LightTaskRuntime(configuration=configuration)
    if dependencies_factory is None:
        raise RuntimeConfigurationError("light task runtime is enabled without dependencies")
    try:
        dependencies = dependencies_factory()
    except RuntimeConfigurationError:
        raise
    except Exception as error:
        raise RuntimeConfigurationError("light task dependency factory failed") from error
    if not isinstance(dependencies, LightTaskRuntimeDependencies):
        raise RuntimeConfigurationError(
            "light task dependency factory returned invalid dependencies"
        )
    return LightTaskRuntime(
        configuration=configuration,
        supervisor=LightTaskLoopSupervisor.start(build_light_task_loop_bundle(dependencies)),
    )


__all__ = [
    "LightTaskDependenciesFactory",
    "LightTaskLoopBundle",
    "LightTaskLoopSupervisor",
    "LightTaskRuntime",
    "LightTaskRuntimeConfiguration",
    "LightTaskRuntimeDependencies",
    "build_light_task_loop_bundle",
    "resolve_light_task_runtime_configuration",
    "start_light_task_runtime",
]
