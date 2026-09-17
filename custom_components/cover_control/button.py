"""Buttons that suspend automatic control and hand it back again."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoverControlConfigEntry
from .const import SUBENTRY_TYPE_COVER
from .coordinator import CoverControlCoordinator, CoverRuntime
from .entity import ControlledCoverEntity, HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoverControlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub's pause and resume buttons, and one pair per cover."""
    coordinator = entry.runtime_data
    async_add_entities([PauseAllButton(coordinator), ResumeAllButton(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [
                PauseButton(coordinator, runtime),
                ResumeButton(coordinator, runtime),
            ],
            config_subentry_id=subentry_id,
        )


class PauseAllButton(HubEntity, ButtonEntity):
    """Leave every cover alone until the next sunrise."""

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "pause_all")

    @property
    def available(self) -> bool:
        return super().available and any(
            not runtime.is_paused for runtime in self.coordinator.runtimes.values()
        )

    async def async_press(self) -> None:
        await self.coordinator.async_pause_all()


class ResumeAllButton(HubEntity, ButtonEntity):
    """Hand control back for every suspended cover at once."""

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "resume_all")

    @property
    def available(self) -> bool:
        return super().available and any(
            runtime.is_suspended for runtime in self.coordinator.runtimes.values()
        )

    async def async_press(self) -> None:
        await self.coordinator.async_resume_all()


class PauseButton(ControlledCoverEntity, ButtonEntity):
    """Leave this cover alone until the next sunrise."""

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "pause")

    @property
    def available(self) -> bool:
        runtime = self.runtime
        return super().available and runtime is not None and not runtime.is_paused

    async def async_press(self) -> None:
        await self.coordinator.async_pause(self._subentry_id)


class ResumeButton(ControlledCoverEntity, ButtonEntity):
    """Hand control back without waiting for sunrise or for the episode to end."""

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "resume")

    @property
    def available(self) -> bool:
        runtime = self.runtime
        return super().available and runtime is not None and runtime.is_suspended

    async def async_press(self) -> None:
        await self.coordinator.async_resume(self._subentry_id)
