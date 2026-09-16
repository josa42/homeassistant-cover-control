"""The dashboard strategy asset must ship and be registered with the frontend."""

from __future__ import annotations

import pathlib

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control import STRATEGY_URL_PATH

ASSET = (
    pathlib.Path("custom_components/cover_control/www/cover-control-dashboard.js")
)


def test_asset_ships_with_the_integration() -> None:
    """A missing www/ directory is the classic custom-integration packaging bug."""
    assert ASSET.is_file(), "the dashboard strategy asset is not in the package"


def test_asset_registers_both_strategy_kinds() -> None:
    """The element names are the contract the frontend looks the strategy up by."""
    source = ASSET.read_text(encoding="utf-8")
    assert 'customElements.define(\n  "ll-strategy-dashboard-cover-control"' in source
    assert 'customElements.define(\n  "ll-strategy-view-cover-control"' in source


def test_asset_surfaces_dry_run() -> None:
    """A dashboard that cannot tell dry run from real is actively misleading."""
    source = ASSET.read_text(encoding="utf-8")
    assert "dry_run" in source
    assert "would_move" in source


def test_asset_reads_the_cover_from_the_decision_sensor() -> None:
    """The controlled cover is not one of our entities; it comes from the record."""
    source = ASSET.read_text(encoding="utf-8")
    assert "cover_entity" in source


async def test_strategy_is_served_over_http(
    hass: HomeAssistant, hass_client, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    # hass_client needs a real http component; the integration only declares it
    # as an after-dependency, so nothing else sets it up here.
    assert await async_setup_component(hass, "http", {})
    set_scene()
    await setup_entry(entry)

    client = await hass_client()
    response = await client.get(STRATEGY_URL_PATH)
    assert response.status == 200
    body = await response.text()
    assert "ll-strategy-dashboard-cover-control" in body


async def test_setup_survives_an_unavailable_frontend(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """Covers must keep working even if the dashboard cannot be registered.

    Regression: add_extra_js_url raises KeyError when the frontend component is
    not loaded, and that propagated out of async_setup and aborted the whole
    integration. The test environment has no frontend, so this is the real case.
    """
    set_scene()
    await setup_entry(entry)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"
