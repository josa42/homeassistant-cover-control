"""Buttons that hand control back after a manual override."""

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
    """Set up the resume-all button and one resume button per cover."""
    coordinator = entry.runtime_data
    async_add_entities([ResumeAllButton(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [ResumeButton(coordinator, runtime)], config_subentry_id=subentry_id
        )


class ResumeAllButton(HubEntity, ButtonEntity):
    """Clear every manual override at once."""

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "resume_all")

    async def async_press(self) -> None:
        await self.coordinator.async_resume_all()


class ResumeButton(ControlledCoverEntity, ButtonEntity):
    """Clear this cover's manual override without waiting for the episode to end."""

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "resume")

    async def async_press(self) -> None:
        await self.coordinator.async_resume(self._subentry_id)
