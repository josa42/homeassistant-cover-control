"""Config flow and per-cover subentry flow."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import (
    CONF_AZIMUTH,
    CONF_COOL_ABOVE,
    CONF_COVER_ENTITY,
    CONF_COVER_TYPE,
    CONF_MAX_DEPTH,
    CONF_OUTDOOR_TEMP,
    CONF_SEATING_POINT,
    CONF_SHADED_TILT,
    CONF_SILL_HEIGHT,
    CONF_STORM_ACTION,
    CONF_WEATHER,
    CONF_WINDOW_HEIGHT,
    DOMAIN,
    CoverType,
    StormAction,
)

HUB_INPUT = {
    CONF_OUTDOOR_TEMP: "sensor.outdoor",
    CONF_WEATHER: "weather.home",
    CONF_COOL_ABOVE: 25.0,
    "heat_below": 12.0,
    "indoor_cool_above": 23.0,
    "indoor_heat_below": 21.0,
    "pv_threshold": 800.0,
    "allowed_weather_states": ["sunny"],
    "wind_threshold": 40.0,
    "wind_release": 30.0,
}


def schema_defaults(schema) -> dict:
    """Map field name to its default, skipping fields that have none."""
    defaults = {}
    for key in schema.schema:
        default = getattr(key, "default", vol.UNDEFINED)
        if default is not vol.UNDEFINED and callable(default):
            defaults[str(key)] = default()
    return defaults


def schema_fields(schema) -> set[str]:
    return {str(key) for key in schema.schema}


async def test_creates_the_hub(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], HUB_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cover Control"
    assert result["data"][CONF_OUTDOOR_TEMP] == "sensor.outdoor"


async def test_only_one_hub_is_allowed(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, data=HUB_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_adding_a_cover_prefills_the_type_from_its_features(
    hass: HomeAssistant,
) -> None:
    """A cover that reports tilt is almost certainly a Raffstore."""
    entry = MockConfigEntry(domain=DOMAIN, data=HUB_INPUT)
    entry.add_to_hass(hass)
    hass.states.async_set(
        "cover.raffstore",
        "open",
        {"supported_features": 255, "friendly_name": "Raffstore"},
    )

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER_ENTITY: "cover.raffstore"}
    )
    assert result["step_id"] == "configure"

    schema = result["data_schema"]
    assert schema_defaults(schema)[CONF_COVER_TYPE] == CoverType.RAFFSTORE
    # The slat angle field only appears for covers that can actually tilt.
    assert CONF_SHADED_TILT in schema_fields(schema)


async def test_cover_without_tilt_is_prefilled_as_a_roller_shutter(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=HUB_INPUT)
    entry.add_to_hass(hass)
    hass.states.async_set(
        "cover.rolladen",
        "open",
        {"supported_features": 15, "friendly_name": "Rolladen"},
    )

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER_ENTITY: "cover.rolladen"}
    )
    schema = result["data_schema"]
    assert schema_defaults(schema)[CONF_COVER_TYPE] == CoverType.ROLLADEN
    assert CONF_SHADED_TILT not in schema_fields(schema)


async def test_cover_subentry_is_created(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=HUB_INPUT)
    entry.add_to_hass(hass)
    hass.states.async_set(
        "cover.rolladen",
        "open",
        {"supported_features": 15, "friendly_name": "Rolladen"},
    )

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER_ENTITY: "cover.rolladen"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Bedroom",
            CONF_COVER_TYPE: CoverType.ROLLADEN,
            CONF_AZIMUTH: 60.0,
            CONF_WINDOW_HEIGHT: 2.0,
            CONF_SILL_HEIGHT: 0.0,
            CONF_MAX_DEPTH: 0.0,
            "fov_left": 90.0,
            "fov_right": 90.0,
            CONF_STORM_ACTION: StormAction.IGNORE,
            "shade_with_window_open": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom"
    assert result["data"][CONF_COVER_ENTITY] == "cover.rolladen"
    assert result["data"][CONF_AZIMUTH] == 60.0


async def test_already_controlled_covers_are_hidden(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=HUB_INPUT,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_COVER_ENTITY: "cover.rolladen"},
                subentry_type="cover",
                title="Bedroom",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    selector_config = next(iter(result["data_schema"].schema.values())).config
    assert selector_config["exclude_entities"] == ["cover.rolladen"]


async def test_options_flow_edits_the_hub_defaults(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=HUB_INPUT)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**HUB_INPUT, CONF_COOL_ABOVE: 22.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_COOL_ABOVE] == 22.0


async def test_seating_point_override_is_optional(hass: HomeAssistant) -> None:
    """Left blank it must be absent, so the cover type default applies."""
    entry = MockConfigEntry(domain=DOMAIN, data=HUB_INPUT)
    entry.add_to_hass(hass)
    hass.states.async_set("cover.rolladen", "open", {"supported_features": 15})

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER_ENTITY: "cover.rolladen"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Bedroom",
            CONF_COVER_TYPE: CoverType.ROLLADEN,
            CONF_AZIMUTH: 60.0,
            CONF_WINDOW_HEIGHT: 2.0,
            CONF_SILL_HEIGHT: 0.0,
            CONF_MAX_DEPTH: 0.0,
            "fov_left": 90.0,
            "fov_right": 90.0,
            CONF_STORM_ACTION: StormAction.IGNORE,
            "shade_with_window_open": False,
        },
    )
    assert CONF_SEATING_POINT not in result["data"]
