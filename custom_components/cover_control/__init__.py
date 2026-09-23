"""The Cover Control integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, ISSUE_UNCONTROLLED_COVERS
from .coordinator import CoverControlCoordinator

_LOGGER = logging.getLogger(__name__)

# There is nothing to configure in YAML; everything lives in config entries.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

STRATEGY_URL_PATH = "/cover-control/cover-control-dashboard.js"
STRATEGY_VERSION = "1.8.0"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

type CoverControlConfigEntry = ConfigEntry[CoverControlCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the dashboard strategy. Called once per Home Assistant session."""
    http = getattr(hass, "http", None)
    if http is None:
        return True
    strategy = Path(__file__).parent / "www" / "cover-control-dashboard.js"
    if not strategy.is_file():
        _LOGGER.warning("Dashboard strategy asset missing at %s", strategy)
        return True
    try:
        await http.async_register_static_paths(
            [StaticPathConfig(STRATEGY_URL_PATH, str(strategy), cache_headers=False)]
        )
        # Version query string, so a browser does not keep serving the strategy
        # it cached before an upgrade.
        add_extra_js_url(hass, f"{STRATEGY_URL_PATH}?v={STRATEGY_VERSION}")
    except Exception as err:  # noqa: BLE001
        # The dashboard is optional polish. Whatever goes wrong here, shading
        # covers must still work, so this can never abort the setup.
        _LOGGER.warning("Could not register the dashboard strategy: %s", err)
    else:
        _LOGGER.debug("Registered dashboard strategy at %s", STRATEGY_URL_PATH)
    return True


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
    # A reload puts it straight back on the next refresh. Removing the
    # integration for good must not leave the issue behind, though.
    ir.async_delete_issue(hass, DOMAIN, ISSUE_UNCONTROLLED_COVERS)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
