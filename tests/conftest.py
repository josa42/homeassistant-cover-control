"""Shared fixtures and the scene helper used by the integration tests."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import (
    CONF_AZIMUTH,
    CONF_COOL_ABOVE,
    CONF_COVER_ENTITY,
    CONF_COVER_TYPE,
    CONF_MAX_DEPTH,
    CONF_OUTDOOR_TEMP,
    CONF_PV_POWER,
    CONF_PV_THRESHOLD,
    CONF_SHADED_TILT,
    CONF_SILL_HEIGHT,
    CONF_STORM_ACTION,
    CONF_WEATHER,
    CONF_WINDOW_HEIGHT,
    DOMAIN,
    CoverType,
    StormAction,
)

pytest_plugins = "pytest_homeassistant_custom_component"

COVER = "cover.raffstore"

HUB_DATA = {
    CONF_OUTDOOR_TEMP: "sensor.outdoor",
    CONF_WEATHER: "weather.home",
    CONF_PV_POWER: "sensor.pv",
    CONF_COOL_ABOVE: 25.0,
    CONF_PV_THRESHOLD: 800.0,
}

COVER_DATA = {
    CONF_COVER_ENTITY: COVER,
    CONF_COVER_TYPE: CoverType.RAFFSTORE,
    CONF_AZIMUTH: 180.0,
    CONF_WINDOW_HEIGHT: 2.0,
    CONF_SILL_HEIGHT: 0.0,
    CONF_MAX_DEPTH: 1.0,
    CONF_SHADED_TILT: 45,
    CONF_STORM_ACTION: StormAction.RETRACT_UP,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom integration loadable in every test."""
    return


@pytest.fixture
def service_calls_factory(hass: HomeAssistant):
    """Record calls to a service, replacing its normal handler."""

    def _factory(domain: str, service: str) -> list:
        calls: list = []

        async def _record(call) -> None:
            calls.append(call)

        hass.services.async_register(domain, service, _record)
        return calls

    return _factory


@pytest.fixture(autouse=True)
def cover_calls(service_calls_factory) -> dict[str, list]:
    """Record cover commands so no test needs the real cover integration."""
    return {
        "position": service_calls_factory("cover", "set_cover_position"),
        "tilt": service_calls_factory("cover", "set_cover_tilt_position"),
    }


@pytest.fixture
def set_scene(hass: HomeAssistant):
    """Set up a hot, sunny noon with the sun straight on a south-facing window."""

    def _set(**overrides) -> None:
        scene = {
            "sun_elevation": 45.0,
            "sun_azimuth": 180.0,
            "outdoor": "28.0",
            "pv": "1500",
            "weather": "sunny",
            "wind": 10.0,
            "position": 100,
            "features": 255,
        }
        scene.update(overrides)
        hass.states.async_set(
            "sun.sun",
            "above_horizon",
            {"elevation": scene["sun_elevation"], "azimuth": scene["sun_azimuth"]},
        )
        hass.states.async_set("sensor.outdoor", scene["outdoor"])
        hass.states.async_set("sensor.pv", scene["pv"])
        hass.states.async_set(
            "weather.home",
            scene["weather"],
            {"wind_speed": scene["wind"], "wind_speed_unit": "km/h"},
        )
        hass.states.async_set(
            COVER,
            "open",
            {
                "current_position": scene["position"],
                "current_tilt_position": 100,
                "supported_features": scene["features"],
            },
        )

    return _set


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A hub entry with one controlled cover."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cover Control",
        data=HUB_DATA,
        subentries_data=[
            ConfigSubentryData(
                data=COVER_DATA,
                subentry_type="cover",
                title="Raffstore",
                unique_id=None,
            )
        ],
    )
    mock_entry.add_to_hass(hass)
    return mock_entry


@pytest.fixture
def setup_entry(hass: HomeAssistant):
    """Set up a config entry and wait for it to settle."""

    async def _setup(mock_entry: MockConfigEntry) -> None:
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()

    return _setup
