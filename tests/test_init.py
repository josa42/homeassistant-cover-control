"""Setup, entity creation and the end-to-end path from state to cover command."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import CONF_COOL_ABOVE

from .conftest import COVER


async def test_entry_sets_up_and_unloads(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_creates_hub_and_cover_entities(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    for entity_id in (
        "sensor.cover_control_status",
        "binary_sensor.cover_control_storm_protection",
        "switch.cover_control_enabled",
        "button.cover_control_resume_all",
        "sensor.raffstore_decision",
        "binary_sensor.raffstore_manual_override",
        "switch.raffstore_enabled",
        "button.raffstore_resume",
    ):
        assert hass.states.get(entity_id) is not None, f"{entity_id} was not created"


async def test_hub_and_cover_are_separate_devices(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    by_name = {device.name: device for device in devices}
    assert "Cover Control" in by_name
    assert "Raffstore" in by_name
    # The cover hangs off the hub, so the UI nests them.
    assert by_name["Raffstore"].via_device_id == by_name["Cover Control"].id


async def test_shades_a_hot_sunny_window(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene()
    await setup_entry(entry)

    assert cover_calls["position"], "expected the cover to be shaded"
    assert cover_calls["position"][-1].data["position"] == 50

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "cooling"
    assert decision.attributes["reason_code"] == "shading"
    assert decision.attributes["target_position"] == 50


async def test_the_slats_are_set_only_once_the_cover_has_arrived(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """A tilt command sent into a running cover is read as a new destination.

    The cover abandons the run and settles back where it started, so it never
    reaches its position and the same pair of commands goes out again on the
    state change that caused. Position first, tilt after arrival, breaks that.
    """
    set_scene()
    await setup_entry(entry)

    assert not cover_calls["tilt"], "the cover is still travelling"

    set_scene(position=50)  # it arrives
    await hass.async_block_till_done()

    assert cover_calls["tilt"][-1].data["tilt_position"] == 45


async def test_decision_message_explains_the_number(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    message = hass.states.get("sensor.raffstore_decision").attributes["message"]
    assert "2.00 m" in message and "1.00 m" in message


async def test_decision_attributes_stay_flat(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """The recorder writes these on every tick, so they must stay small."""
    set_scene()
    await setup_entry(entry)

    attributes = hass.states.get("sensor.raffstore_decision").attributes
    reported = {
        key: value
        for key, value in attributes.items()
        if key not in ("options", "device_class", "friendly_name")
    }
    assert reported, "expected the decision attributes to be exposed"
    assert not any(isinstance(value, (dict, list)) for value in reported.values())


async def test_master_switch_off_stops_control(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.cover_control_enabled"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.raffstore_decision").state == "disabled"


async def test_per_cover_switch_off_stops_only_that_cover(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.raffstore_enabled"}, blocking=True
    )
    await hass.async_block_till_done()

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "disabled"
    assert decision.attributes["reason_code"] == "cover_disabled"


async def test_storm_retracts_and_outranks_shading(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene(wind=55.0)
    await setup_entry(entry)

    assert cover_calls["position"][-1].data["position"] == 100
    assert hass.states.get("sensor.raffstore_decision").state == "storm"
    assert hass.states.get("binary_sensor.cover_control_storm_protection").state == "on"


async def test_hub_status_counts_controlled_covers(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    status = hass.states.get("sensor.cover_control_status")
    assert status.state == "1"
    assert status.attributes["shading"] == 1
    assert status.attributes["total"] == 1


async def test_a_decision_event_is_fired(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    from custom_components.cover_control.const import EVENT_DECISION

    events = []
    hass.bus.async_listen(EVENT_DECISION, events.append)

    set_scene()
    await setup_entry(entry)

    assert events, "expected a decision event"
    assert events[-1].data["reason_code"] == "shading"
    assert events[-1].data["gates"][0]["name"] == "cover_available"


async def test_diagnostics_carry_the_full_trace(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    from custom_components.cover_control.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    set_scene()
    await setup_entry(entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    cover = diagnostics["covers"][COVER]
    assert cover["decisions"], "expected at least one recorded decision"
    last = cover["decisions"][-1]
    assert last["reason_code"] == "shading"
    assert next(gate["name"] for gate in last["gates"]) == "cover_available"
    assert last["geometry"]["profile_angle"] == 45.0
    assert last["settings"][CONF_COOL_ABOVE]["source"] == "hub"
