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
        "entities": {
            status: {
                "entity_id": status,
                "platform": "cover_control",
                "device_id": "hub",
                "translation_key": "status",
            }
        },
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


def test_tiles_do_not_repeat_the_device_name(tmp_path) -> None:
    """Tiles truncate, so "Arbeitszimmer Raffstore Fortsetzen" showed as
    "Arbeitszimmer Raff..." under a heading that already names the cover."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    def entity(entity_id, device, friendly, translation_key, attributes=None):
        return (
            {
                "entity_id": entity_id,
                "platform": "cover_control",
                "device_id": device,
                "translation_key": translation_key,
            },
            {"entity_id": entity_id, "state": "on", "attributes": {"friendly_name": friendly, **(attributes or {})}},
        )

    entities = {
        "switch.cc_enabled": entity("switch.cc_enabled", "hub", "Cover Control Aktiviert", "enabled"),
        "button.cc_pause_all": entity(
            "button.cc_pause_all", "hub", "Cover Control Alle pausieren", "pause_all"
        ),
        "button.cc_resume_all": entity(
            "button.cc_resume_all", "hub", "Cover Control Alle fortsetzen", "resume_all"
        ),
        "sensor.az_decision": entity(
            "sensor.az_decision", "az", "Arbeitszimmer Raffstore Entscheidung", "decision",
            {"cover_entity": "cover.az"},
        ),
        "button.az_pause": entity("button.az_pause", "az", "Arbeitszimmer Raffstore Pausieren", "pause"),
        "button.az_resume": entity("button.az_resume", "az", "Arbeitszimmer Raffstore Fortsetzen", "resume"),
        "switch.az_enabled": entity("switch.az_enabled", "az", "Arbeitszimmer Raffstore Aktiviert", "enabled"),
        "binary_sensor.az_override": entity(
            "binary_sensor.az_override", "az", "Arbeitszimmer Raffstore Manueller Eingriff", "override_active"
        ),
        "binary_sensor.az_paused": entity(
            "binary_sensor.az_paused", "az", "Arbeitszimmer Raffstore Pausiert", "paused"
        ),
    }
    hass = {
        "locale": {"language": "de"},
        "devices": {
            "hub": {"id": "hub", "name": "Cover Control", "via_device_id": None},
            "az": {"id": "az", "name": "Arbeitszimmer Raffstore", "via_device_id": "hub"},
        },
        "entities": {k: v[0] for k, v in entities.items()},
        "states": {k: v[1] for k, v in entities.items()},
    }
    (tmp_path / "hass.json").write_text(json.dumps(hass))
    (tmp_path / "harness.js").write_text(_GENERATE_HARNESS)
    result = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(ASSET.resolve()), str(tmp_path / "hass.json")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    names = {
        card["entity"]: card.get("name")
        for view in json.loads(result.stdout)["views"]
        for section in view["sections"]
        for card in section["cards"]
        if card["type"] == "tile" and card["entity"] in entities
    }
    # The decision, the pause and the manual override are not tiles any more:
    # they read as conditions in the cover's own view, and a tile beside them
    # would say the same thing twice.
    assert names == {
        "switch.cc_enabled": "Aktiviert",
        "button.cc_pause_all": "Alle pausieren",
        "button.cc_resume_all": "Alle fortsetzen",
        "button.az_pause": "Pausieren",
        "button.az_resume": "Fortsetzen",
        "switch.az_enabled": "Aktiviert",
    }


def test_debug_view_surfaces_every_decision_attribute(tmp_path) -> None:
    """The debug view is the whole reason the decision record is compact.

    The expected keys come from the decision itself, so an attribute added
    there later fails this test until the debug view shows it too, as a row or
    inside one of the card templates.
    """
    import datetime
    import json
    import shutil
    import subprocess

    from custom_components.cover_control.const import Intent, Reason
    from custom_components.cover_control.models import Decision

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    expected = set(
        Decision(
            timestamp=datetime.datetime.now(datetime.UTC),
            cover_entity="cover.az",
            intent=Intent.COOLING,
            reason=Reason.SHADING,
            message="",
        ).as_attributes()
    )
    # Values the debug view deliberately does not show, and why. Anything not
    # listed here has to appear, so a new attribute fails this test until the
    # view accounts for it.
    for attribute, _reason in (
        ("cover_entity", "plumbing: the strategy reads it to find the cover"),
        ("message", "written in English by the engine; the view is German"),
        ("reason_code", "an enum a template renders raw; the conditions say it"),
        ("blocked_by", "same, and a failing condition already shows which"),
        ("weather_ok", "carried by the brightness condition and its weather word"),
        ("episode_active", "the intent line says it in words"),
    ):
        expected.discard(attribute)

    decision = "sensor.az_decision"
    hass = {
        "locale": {"language": "en"},
        "devices": {
            "hub": {"id": "hub", "name": "Cover Control", "via_device_id": None},
            "az": {"id": "az", "name": "Arbeitszimmer Raffstore", "via_device_id": "hub"},
        },
        # The hub needs an entity of its own: a device is only read as a cover
        # when the device it hangs off carries entities too.
        "entities": {
            "switch.cc_enabled": {
                "entity_id": "switch.cc_enabled",
                "platform": "cover_control",
                "device_id": "hub",
                "translation_key": "enabled",
            },
            "binary_sensor.cc_storm": {
                "entity_id": "binary_sensor.cc_storm",
                "platform": "cover_control",
                "device_id": "hub",
                "translation_key": "storm_active",
            },
            decision: {
                "entity_id": decision,
                "platform": "cover_control",
                "device_id": "az",
                "translation_key": "decision",
            },
        },
        "states": {
            "switch.cc_enabled": {
                "entity_id": "switch.cc_enabled",
                "state": "on",
                "attributes": {},
            },
            "binary_sensor.cc_storm": {
                "entity_id": "binary_sensor.cc_storm",
                "state": "off",
                "attributes": {},
            },
            decision: {
                "entity_id": decision,
                "state": "cooling",
                # A window contact is configured here, because the view only
                # spends a line on that condition for a cover that has one.
                "attributes": {"cover_entity": "cover.az", "window_open": False},
            },
            "sensor.az_today": {
                "entity_id": "sensor.az_today",
                "state": "0",
                "attributes": {"events": []},
            },
        },
    }
    (tmp_path / "hass.json").write_text(json.dumps(hass))
    (tmp_path / "harness.js").write_text(_GENERATE_HARNESS)
    result = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(ASSET.resolve()), str(tmp_path / "hass.json")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    debug = next(
        view for view in json.loads(result.stdout)["views"] if view.get("subview")
    )
    cards = [card for section in debug["sections"] for card in section["cards"]]

    rows = [
        row
        for card in cards
        for row in card.get("entities", [])
        if isinstance(row, dict) and row.get("type") == "attribute"
    ]
    shown = {row["attribute"] for row in rows}
    templates = "\n".join(card.get("content", "") for card in cards)
    shown |= {name for name in expected if f"'{name}'" in templates}

    assert expected - shown == set(), "decision attributes missing from the debug view"
    sun = next(line for line in templates.splitlines() if "profile_angle" in line)
    assert "penetration_depth" in sun, "the angle belongs beside the depth it explains"
    assert "°" in sun and " m" in sun, "both want their unit"

    # The view is a set of sentences now, not a table of values: an attribute
    # row would be an English label and a raw enum among translated prose.
    assert rows == [], "the debug view went back to attribute rows"

    # Every condition reads as a tick or a cross with words after it.
    conditions = [line for line in templates.splitlines() if line.startswith("- {%")]
    assert len(conditions) >= 4, "expected a list of conditions"
    assert all("\u2705" in line and "\u274c" in line for line in conditions)


def test_the_debug_card_renders_without_gaps(tmp_path) -> None:
    """A bare Jinja statement on its own line leaves a blank line behind.

    Inside a markdown list a blank line ends the list and starts another, with
    a paragraph of air between them, which is what the conditions looked like
    before they were one card.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    decision = "sensor.az_decision"
    hass = {
        "locale": {"language": "de"},
        "devices": {
            "hub": {"id": "hub", "name": "Cover Control", "via_device_id": None},
            "az": {"id": "az", "name": "Arbeitszimmer", "via_device_id": "hub"},
        },
        "entities": {
            "switch.cc": {
                "entity_id": "switch.cc", "platform": "cover_control",
                "device_id": "hub", "translation_key": "enabled",
            },
            decision: {
                "entity_id": decision, "platform": "cover_control",
                "device_id": "az", "translation_key": "decision",
            },
        },
        "states": {
            "switch.cc": {"entity_id": "switch.cc", "state": "on", "attributes": {}},
            decision: {
                "entity_id": decision, "state": "cooling",
                "attributes": {"cover_entity": "cover.az", "window_open": False},
            },
            "sensor.az_today": {
                "entity_id": "sensor.az_today",
                "state": "0",
                "attributes": {"events": []},
            },
        },
    }
    (tmp_path / "hass.json").write_text(json.dumps(hass))
    (tmp_path / "harness.js").write_text(_GENERATE_HARNESS)
    result = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(ASSET.resolve()), str(tmp_path / "hass.json")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    debug = next(
        view for view in json.loads(result.stdout)["views"] if view.get("subview")
    )
    cards = [card for section in debug["sections"] for card in section["cards"]]

    untitled = [
        card for card in cards if card["type"] == "markdown" and not card.get("title")
    ]
    assert len(untitled) == 1, "the intent and the conditions belong in one card"

    lines = untitled[0]["content"].splitlines()

    bare = [
        line
        for line in lines
        if line.strip().startswith("{%")
        and line.strip().endswith("%}")
        and "{{" not in line
    ]
    assert all("{%-" in line or "-%}" in line for line in bare), (
        "an untrimmed Jinja statement line renders as a blank line"
    )

    conditions = [n for n, line in enumerate(lines) if line.startswith("- {%")]
    assert conditions, "expected a list of conditions"
    assert conditions == list(range(conditions[0], conditions[0] + len(conditions))), (
        "something sits between the conditions and will render as a gap"
    )


def test_every_cover_gets_its_own_view_linked_from_the_overview(tmp_path) -> None:
    """The overview answers which cover is in which state and nothing else.

    Two covers share a name here, because a view path that collided would take
    the reader to the wrong cover's detail without anything looking wrong.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    def cover(slug, device, name):
        return {
            f"sensor.{slug}_decision": {
                "entity_id": f"sensor.{slug}_decision",
                "platform": "cover_control",
                "device_id": device,
                "translation_key": "decision",
            }
        }, {
            f"sensor.{slug}_decision": {
                "entity_id": f"sensor.{slug}_decision",
                "state": "cooling",
                "attributes": {"cover_entity": f"cover.{slug}"},
            }
        }, {"id": device, "name": name, "via_device_id": "hub"}

    entities, states, devices = {}, {}, {"hub": {"id": "hub", "name": "Cover Control", "via_device_id": None}}
    for slug, device, name in (
        ("a", "a", "Küche Raffstore"),
        ("b", "b", "Küche Raffstore"),  # same name on purpose
        ("c", "c", "Bad Rolladen"),
    ):
        e, st, dev = cover(slug, device, name)
        entities.update(e)
        states.update(st)
        devices[device] = dev
    entities["switch.cc"] = {
        "entity_id": "switch.cc", "platform": "cover_control",
        "device_id": "hub", "translation_key": "enabled",
    }
    states["switch.cc"] = {"entity_id": "switch.cc", "state": "on", "attributes": {}}

    hass = {"locale": {"language": "de"}, "devices": devices,
            "entities": entities, "states": states}
    (tmp_path / "hass.json").write_text(json.dumps(hass))
    (tmp_path / "harness.js").write_text(_GENERATE_HARNESS)
    result = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(ASSET.resolve()), str(tmp_path / "hass.json")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    views = json.loads(result.stdout)["views"]

    overview = views[0]
    details = [view for view in views[1:] if view.get("subview")]
    assert len(details) == 3, "one view per cover"

    paths = [view["path"] for view in details]
    assert len(set(paths)) == 3, f"two covers share a view path: {paths}"
    assert "overview" not in paths, "a cover took the overview's own path"

    links = [
        card["tap_action"]["navigation_path"]
        for section in overview["sections"]
        for card in section["cards"]
        if card.get("tap_action", {}).get("action") == "navigate"
    ]
    # Twice each: the overview carries every cover in both halves and lets the
    # visibility conditions decide which one the reader sees.
    assert sorted(set(links)) == sorted(paths), "every cover is reachable from the overview"
    assert sorted(links) == sorted(paths + paths), "a cover is missing from a half"

    # And nothing to operate a single cover with sits on the overview.
    overview_cards = [c for s in overview["sections"] for c in s["cards"]]
    assert not any(card.get("features") for card in overview_cards), (
        "the overview grew a cover control again"
    )


def test_the_overview_splits_covers_by_whether_they_are_driven(tmp_path) -> None:
    """Which covers are being shaded right now is what this view is opened with.

    The split is left to visibility conditions rather than settled while the
    views are built, because the strategy runs when the dashboard opens and a
    cover that starts shading a minute later would sit under the wrong
    heading until the page was reloaded.
    """
    import json
    import shutil
    import subprocess

    from custom_components.cover_control.const import Intent

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    entities, states = {}, {}
    for slug, device in (("cc", "hub"), ("az", "az")):
        entities[f"switch.{slug}_enabled"] = {
            "entity_id": f"switch.{slug}_enabled", "platform": "cover_control",
            "device_id": device, "translation_key": "enabled",
        }
        states[f"switch.{slug}_enabled"] = {
            "entity_id": f"switch.{slug}_enabled", "state": "on", "attributes": {},
        }
    entities["sensor.az_decision"] = {
        "entity_id": "sensor.az_decision", "platform": "cover_control",
        "device_id": "az", "translation_key": "decision",
    }
    states["sensor.az_decision"] = {
        "entity_id": "sensor.az_decision", "state": "cooling",
        "attributes": {"cover_entity": "cover.az"},
    }

    hass = {
        "locale": {"language": "de"},
        "devices": {
            "hub": {"id": "hub", "name": "Cover Control", "via_device_id": None},
            "az": {"id": "az", "name": "Arbeitszimmer Raffstore", "via_device_id": "hub"},
        },
        "entities": entities,
        "states": states,
    }
    (tmp_path / "hass.json").write_text(json.dumps(hass))
    (tmp_path / "harness.js").write_text(_GENERATE_HARNESS)
    result = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(ASSET.resolve()), str(tmp_path / "hass.json")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    overview = json.loads(result.stdout)["views"][0]

    halves = {
        section["cards"][0]["heading"]: section
        for section in overview["sections"]
        if section["cards"][0].get("heading") in ("Wird gerade gestellt", "Bleibt in Ruhe")
    }
    assert set(halves) == {"Wird gerade gestellt", "Bleibt in Ruhe"}

    # The intent, not the switches behind it: the engine has already weighed
    # those, and the states here have to stay the ones it actually reports.
    driven = ["storm", "cooling", "heating"]
    assert set(driven) <= {intent.value for intent in Intent}, "an intent was renamed"

    held = halves["Wird gerade gestellt"]["cards"][1]
    assert held["visibility"] == [
        {"condition": "state", "entity": "sensor.az_decision", "state": driven}
    ]

    # state_not rather than a list of the other intents, so a sensor that is
    # unavailable still lands in exactly one half instead of dropping out of
    # both.
    loose = halves["Bleibt in Ruhe"]["cards"][1]
    assert loose["visibility"] == [
        {"condition": "state", "entity": "sensor.az_decision", "state_not": driven}
    ], "the halves are not complements"

    # Both headings would otherwise stand over nothing half the time.
    assert halves["Wird gerade gestellt"]["visibility"] == [
        {"condition": "or", "conditions": held["visibility"]}
    ]
    assert halves["Bleibt in Ruhe"]["visibility"] == [
        {"condition": "or", "conditions": loose["visibility"]}
    ]

    # Names are the reason the tiles span the section: "Arbeitszimmer
    # Raffstore" is cut off mid-word at half a width.
    assert held["grid_options"] == {"columns": 12}
    assert loose["grid_options"] == {"columns": 12}
