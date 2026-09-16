"""Enable switches for the hub and for each cover."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import CoverControlConfigEntry
from .const import SUBENTRY_TYPE_COVER
from .coordinator import CoverControlCoordinator, CoverRuntime
from .entity import ControlledCoverEntity, HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoverControlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the master switch and one switch per cover."""
    coordinator = entry.runtime_data
    async_add_entities([MasterSwitch(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [CoverEnabledSwitch(coordinator, runtime)], config_subentry_id=subentry_id
        )


class MasterSwitch(HubEntity, SwitchEntity, RestoreEntity):
    """Off means the integration moves nothing at all."""

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "enabled")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            await self.coordinator.async_set_master(last.state == STATE_ON)

    @property
    def is_on(self) -> bool:
        return self.coordinator.master_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_master(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_master(False)
        self.async_write_ha_state()


class CoverEnabledSwitch(ControlledCoverEntity, SwitchEntity, RestoreEntity):
    """Off means this one cover is left alone."""

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "enabled")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            await self.coordinator.async_set_cover_enabled(
                self._subentry_id, last.state == STATE_ON
            )

    @property
    def is_on(self) -> bool:
        runtime = self.runtime
        return bool(runtime and runtime.enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_cover_enabled(self._subentry_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_cover_enabled(self._subentry_id, False)
        self.async_write_ha_state()
