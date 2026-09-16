"""Translations must cover every field the flows actually show."""

from __future__ import annotations

import json
import pathlib

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import CONF_COVER_ENTITY, DOMAIN

COMPONENT = pathlib.Path("custom_components/cover_control")
LANGUAGES = ["en", "de"]


def load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def flatten(data: dict, prefix: str = "") -> set[str]:
    keys = set()
    for key, value in data.items():
        keys.add(prefix + key)
        if isinstance(value, dict):
            keys |= flatten(value, prefix + key + ".")
    return keys


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_matches_strings(language: str) -> None:
    """Every language file must have exactly the keys strings.json has."""
    expected = flatten(load("strings.json"))
    actual = flatten(load(f"translations/{language}.json"))
    assert expected - actual == set(), f"{language} is missing keys"
    assert actual - expected == set(), f"{language} has stale keys"


async def test_hub_schema_fields_are_all_translated(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    fields = {str(key) for key in result["data_schema"].schema}
    labelled = set(load("strings.json")["config"]["step"]["user"]["data"])
    assert fields - labelled == set(), "config flow fields without a label"


async def test_cover_schema_fields_are_all_translated(hass: HomeAssistant) -> None:
    """Includes the tilt field, which only appears for tilt-capable covers."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    hass.states.async_set("cover.raffstore", "open", {"supported_features": 255})

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    pick_fields = {str(key) for key in result["data_schema"].schema}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_COVER_ENTITY: "cover.raffstore"}
    )
    configure_fields = {str(key) for key in result["data_schema"].schema}

    steps = load("strings.json")["config_subentries"]["cover"]["step"]
    assert pick_fields - set(steps["user"]["data"]) == set()
    assert configure_fields - set(steps["configure"]["data"]) == set()


def test_decision_states_are_all_translated() -> None:
    """A decision sensor state with no translation shows as a raw enum value."""
    from custom_components.cover_control.const import Intent

    states = set(load("strings.json")["entity"]["sensor"]["decision"]["state"])
    assert {intent.value for intent in Intent} - states == set()


def test_selector_options_are_all_translated() -> None:
    from custom_components.cover_control.const import CoverType, StormAction

    selectors = load("strings.json")["selector"]
    assert {t.value for t in CoverType} == set(selectors["cover_type"]["options"])
    assert {a.value for a in StormAction} == set(selectors["storm_action"]["options"])


def _decision_attribute_states(language_file: str, attribute: str) -> set[str]:
    data = load(language_file)
    return set(
        data["entity"]["sensor"]["decision"]["state_attributes"][attribute]["state"]
    )


@pytest.mark.parametrize("language", ["strings.json", *(f"translations/{x}.json" for x in LANGUAGES)])
def test_every_reason_code_is_translated(language: str) -> None:
    """Untranslated codes show up raw in the dashboard, e.g. sun_not_on_window."""
    from custom_components.cover_control.const import Reason

    missing = {r.value for r in Reason} - _decision_attribute_states(language, "reason_code")
    assert missing == set(), f"{language} is missing reason codes"


@pytest.mark.parametrize("language", ["strings.json", *(f"translations/{x}.json" for x in LANGUAGES)])
def test_every_blocked_by_value_is_translated(language: str) -> None:
    """blocked_by has no enum, so scan the source for every value it is set to."""
    import re

    used = set()
    for source in COMPONENT.glob("*.py"):
        used |= set(re.findall(r'blocked_by="([a-z_]+)"', source.read_text()))
    assert used, "found no blocked_by values; the scan is broken"
    missing = used - _decision_attribute_states(language, "blocked_by")
    assert missing == set(), f"{language} is missing blocked_by values"


ALL_FILES = ["strings.json", *(f"translations/{x}.json" for x in LANGUAGES)]


@pytest.mark.parametrize("language", ALL_FILES)
def test_every_decision_attribute_has_a_name(language: str) -> None:
    """Raw keys like would_move otherwise show up in the more-info dialog."""
    from datetime import datetime

    from custom_components.cover_control.const import Intent, Reason
    from custom_components.cover_control.models import Decision

    keys = set(
        Decision(
            timestamp=datetime(2026, 1, 1),
            cover_entity="cover.x",
            intent=Intent.NEUTRAL,
            reason=Reason.TEMP_NEUTRAL,
            message="",
        ).as_attributes()
    )
    attrs = load(language)["entity"]["sensor"]["decision"]["state_attributes"]
    unnamed = {key for key in keys if "name" not in attrs.get(key, {})}
    assert unnamed == set(), f"{language}: attributes without a name"


@pytest.mark.parametrize("language", ALL_FILES)
def test_weather_conditions_are_translated_everywhere(language: str) -> None:
    """Both the decision attribute and the setup selector show conditions."""
    from custom_components.cover_control.config_flow import WEATHER_CONDITIONS

    data = load(language)
    attr = set(data["entity"]["sensor"]["decision"]["state_attributes"]["weather"]["state"])
    selector = set(data["selector"]["weather_condition"]["options"])
    assert set(WEATHER_CONDITIONS) - attr == set()
    assert set(WEATHER_CONDITIONS) - selector == set()


@pytest.mark.parametrize("language", ALL_FILES)
def test_status_sensor_attributes_and_unit_are_translated(language: str) -> None:
    from types import SimpleNamespace

    from custom_components.cover_control.sensor import HubStatusSensor

    coordinator = SimpleNamespace(
        runtimes={},
        master_enabled=True,
        entry=SimpleNamespace(entry_id="e", title="Cover Control"),
        async_add_listener=lambda *a, **k: None,
    )
    keys = set(HubStatusSensor(coordinator).extra_state_attributes)
    status = load(language)["entity"]["sensor"]["status"]
    assert "unit_of_measurement" in status
    unnamed = {k for k in keys if "name" not in status.get("state_attributes", {}).get(k, {})}
    assert unnamed == set(), f"{language}: status attributes without a name"


def test_dashboard_templates_use_translated_states() -> None:
    """states() in a card template renders the raw state, e.g. window_open."""
    source = (COMPONENT / "www" / "cover-control-dashboard.js").read_text()
    assert "{{ states(" not in source


async def test_every_flow_outcome_is_translated(hass: HomeAssistant) -> None:
    """Regression: reconfiguring a cover ended on a raw reconfigure_successful.

    Runs the real flows to their abort, so a reason produced implicitly by a
    Home Assistant helper is caught as well as one written out in the source.
    """
    from homeassistant.config_entries import ConfigSubentryData

    strings = load("strings.json")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_COVER_ENTITY: "cover.raffstore"},
                subentry_type="cover",
                title="Raffstore",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    hass.states.async_set("cover.raffstore", "open", {"supported_features": 15})

    # A second hub.
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["reason"] in strings["config"]["abort"]

    # Reconfiguring a cover.
    subentry_id = next(iter(entry.subentries))
    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Raffstore",
            "cover_type": "rolladen",
            "azimuth": 180.0,
            "window_height": 1.5,
            "sill_height": 0.0,
            "max_penetration_depth": 0.0,
            "fov_left": 90.0,
            "fov_right": 90.0,
            "storm_action": "ignore",
            "shade_with_window_open": False,
            "dry_run": False,
        },
    )
    assert result["type"] == "abort"
    abort = strings["config_subentries"]["cover"].get("abort", {})
    assert result["reason"] in abort, f"untranslated outcome: {result['reason']}"
