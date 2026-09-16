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
