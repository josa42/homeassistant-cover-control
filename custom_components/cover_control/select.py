"""Mode selectors for the hub and for each cover, which replace the old switches."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.restore_state import async_get as async_get_restore_state

from . import CoverControlConfigEntry
from .const import DOMAIN, MODE_FROM_HUB, SUBENTRY_TYPE_COVER, Mode
from .coordinator import CoverControlCoordinator, CoverRuntime
from .entity import ControlledCoverEntity, HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoverControlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub's mode selector and one per cover."""
    coordinator = entry.runtime_data
    async_add_entities([HubModeSelect(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [CoverModeSelect(coordinator, runtime)], config_subentry_id=subentry_id
        )


def _was_switched_off(hass: HomeAssistant, unique_id: str) -> bool:
    """Whether the enable switch this selector replaces was last left off.

    Read once, on the first start after the upgrade, so a cover that was
    switched off stays off instead of being taken over by surprise.
    """
    entity_id = er.async_get(hass).async_get_entity_id("switch", DOMAIN, unique_id)
    if entity_id is None:
        return False
    stored = async_get_restore_state(hass).last_states.get(entity_id)
    return stored is not None and stored.state.state == STATE_OFF


class HubModeSelect(HubEntity, SelectEntity, RestoreEntity):
    """Which way the sun may be used, for every cover that follows the hub."""

    _attr_options: ClassVar[list[str]] = [mode.value for mode in Mode]

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            await self.coordinator.async_set_mode(Mode(last.state))
        elif last is None and _was_switched_off(
            self.hass, f"{self.coordinator.entry.entry_id}_enabled"
        ):
            await self.coordinator.async_set_mode(Mode.OFF)

    @property
    def current_option(self) -> str:
        return self.coordinator.mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(Mode(option))
        self.async_write_ha_state()


class CoverModeSelect(ControlledCoverEntity, SelectEntity, RestoreEntity):
    """This cover's own mode, or the hub's."""

    _attr_options: ClassVar[list[str]] = [MODE_FROM_HUB, *(mode.value for mode in Mode)]

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            await self.coordinator.async_set_cover_mode(self._subentry_id, last.state)
        elif last is None and _was_switched_off(
            self.hass, f"{self._subentry_id}_enabled"
        ):
            await self.coordinator.async_set_cover_mode(self._subentry_id, Mode.OFF)

    @property
    def current_option(self) -> str | None:
        runtime = self.runtime
        return None if runtime is None else runtime.mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_cover_mode(self._subentry_id, option)
        self.async_write_ha_state()
