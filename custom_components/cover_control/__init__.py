"""The Cover Control integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import CoverControlCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

type CoverControlConfigEntry = ConfigEntry[CoverControlCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: CoverControlConfigEntry
) -> bool:
    """Set up Cover Control from a config entry."""
    device_registry = dr.async_get(hass)
    hub_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Cover Control",
        model="Controller",
        entry_type=dr.DeviceEntryType.SERVICE,
    )

    coordinator = CoverControlCoordinator(hass, entry)
    coordinator.hub_device_id = hub_device.id
    coordinator.load_subentries()
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_setup_listeners()
    entry.async_on_unload(coordinator.async_stop_listeners)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: CoverControlConfigEntry) -> None:
    """Reload when the hub options or a cover subentry change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: CoverControlConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
