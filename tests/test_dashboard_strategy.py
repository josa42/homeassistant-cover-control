"""The dashboard strategy asset must ship and be registered with the frontend."""

from __future__ import annotations

import pathlib

import pytest
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
    assert '"ll-strategy-dashboard-cover-control"' in source
    assert '"ll-strategy-view-cover-control"' in source


# Runs the shipped module against fake registries and replays what the frontend
# does on a cached page load: this module registers first, then the app bundle's
# scoped custom element polyfill swaps in a new, empty registry.
_SWAP_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
class Registry {
  constructor() { this.defs = new Map(); }
  get(tag) { return this.defs.get(tag); }
  define(tag, cls) {
    if (this.defs.has(tag)) throw new Error("already defined: " + tag);
    this.defs.set(tag, cls);
  }
}
const timers = [];
const window = { customElements: new Registry() };
const context = vm.createContext({
  window, customElements: window.customElements, HTMLElement: class {},
  setTimeout: (fn) => timers.push(fn), Date, Object,
});
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
const original = window.customElements;
const tick = (n) => { for (let i = 0; i < n && timers.length; i++) timers.shift()(); };
tick(3);
// The polyfill replaces the registry, then the app defines its root element.
window.customElements = new Registry();
tick(3);
window.customElements.define("home-assistant", class {});
tick(3);
const final = window.customElements;
console.log(JSON.stringify({
  inOriginal: !!original.get("ll-strategy-dashboard-cover-control"),
  inFinal: !!final.get("ll-strategy-dashboard-cover-control"),
  viewInFinal: !!final.get("ll-strategy-view-cover-control"),
  stoppedAfterSettling: timers.length === 0,
}));
"""


def test_registration_survives_the_frontend_swapping_the_registry(tmp_path) -> None:
    """Regression: the dashboard timed out on most cached page loads.

    The frontend replaces window.customElements during startup. A cached copy of
    this module runs before that, so its elements were lost with the old
    registry and the frontend waited five seconds for an element it could not
    find.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_SWAP_HARNESS)
    result = subprocess.run(
        [node, str(harness), str(ASSET.resolve())],
        capture_output=True, text=True, check=True, timeout=30,
    )
    outcome = json.loads(result.stdout)
    assert outcome["inFinal"], "strategy must be registered in the registry the frontend uses"
    assert outcome["viewInFinal"]
    assert outcome["stoppedAfterSettling"], "registration must stop once the registry settled"


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


_GENERATE_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const defs = new Map();
const registry = { get: (t) => defs.get(t), define: (t, c) => defs.set(t, c) };
defs.set("home-assistant", class {});  // registry already settled
const window = { customElements: registry };
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), vm.createContext({
  window, customElements: registry, HTMLElement: class {}, setTimeout: () => {}, Date, Object,
}));
const hass = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
defs.get("ll-strategy-dashboard-cover-control").generate({}, hass)
  .then((dashboard) => console.log(JSON.stringify(dashboard)));
"""


def test_overview_shows_every_status_attribute(tmp_path) -> None:
    """The status count alone does not say what it counts.

    The expected keys come from the sensor itself, so an attribute added there
    later fails this test until the dashboard shows it too.
    """
    import json
    import shutil
    import subprocess
    from types import SimpleNamespace

    from custom_components.cover_control.sensor import HubStatusSensor

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    coordinator = SimpleNamespace(
        runtimes={},
        master_enabled=True,
        entry=SimpleNamespace(entry_id="e", title="Cover Control"),
    )
    expected = set(HubStatusSensor(coordinator).extra_state_attributes)

    status = "sensor.cover_control_status"
    hass = {
        "locale": {"language": "en"},
        "devices": {"hub": {"id": "hub", "name": "Cover Control", "via_device_id": None}},
        "entities": {status: {"entity_id": status, "platform": "cover_control", "device_id": "hub"}},
        "states": {status: {"entity_id": status, "state": "0", "attributes": {}}},
    }
    (tmp_path / "hass.json").write_text(json.dumps(hass))
    (tmp_path / "harness.js").write_text(_GENERATE_HARNESS)
    result = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(ASSET.resolve()), str(tmp_path / "hass.json")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    dashboard = json.loads(result.stdout)

    rows = [
        row
        for view in dashboard["views"]
        for section in view.get("sections", [])
        for card in section["cards"]
        for row in card.get("entities", [])
        if isinstance(row, dict) and row.get("entity") == status and row.get("type") == "attribute"
    ]
    assert {row["attribute"] for row in rows} == expected
    assert all(row.get("name") for row in rows), "every row needs a readable name"

