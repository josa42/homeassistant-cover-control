"""Setup, entity creation and the end-to-end path from state to cover command."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.cover_control.const import CONF_COOL_ABOVE, DOMAIN

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
        "select.cover_control_mode",
        "button.cover_control_resume_all",
        "button.cover_control_pause_storm_protection",
        "binary_sensor.cover_control_storm_protection_paused",
        "sensor.raffstore_decision",
        "binary_sensor.raffstore_manual_override",
        "select.raffstore_mode",
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
    set_scene(tilt=45)  # slats already right, so the run is the only step
    await setup_entry(entry)

    assert cover_calls["position"], "expected the cover to be shaded"
    assert cover_calls["position"][-1].data["position"] == 50

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "cooling"
    assert decision.attributes["reason_code"] == "shading"
    assert decision.attributes["target_position"] == 50


async def test_the_slats_are_set_before_the_cover_travels(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """An actuator can be set up to put the slat angle back after a run.

    Setting it first makes that restore land on the angle we wanted. It also
    keeps a tilt out of a moving cover, which reads one as a new destination
    and abandons the run it is in the middle of.
    """
    set_scene()
    await setup_entry(entry)

    assert cover_calls["tilt"][-1].data["tilt_position"] == 45
    assert not cover_calls["position"], "the run waits for the slats"

    set_scene(tilt=45)  # the slats are set
    await hass.async_block_till_done()

    assert cover_calls["position"][-1].data["position"] == 50


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
    """The recorder writes these on every tick, so they must stay small.

    The plan is the exception and says so: the sensor marks it unrecorded, so
    it never reaches the database however long it gets.
    """
    from custom_components.cover_control.models import UNRECORDED_ATTRIBUTES

    set_scene()
    await setup_entry(entry)

    sensor = hass.states.get("sensor.raffstore_decision")
    assert UNRECORDED_ATTRIBUTES <= set(sensor.attributes), "the exception is stale"
    assert UNRECORDED_ATTRIBUTES <= sensor.state_info["unrecorded_attributes"]
    reported = {
        key: value
        for key, value in sensor.attributes.items()
        if key not in ("options", "device_class", "friendly_name")
        and key not in UNRECORDED_ATTRIBUTES
    }
    assert reported, "expected the decision attributes to be exposed"
    assert not any(isinstance(value, (dict, list)) for value in reported.values())


async def select_mode(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": option},
        blocking=True,
    )
    # The refresh a selector asks for is debounced; a second one inside the
    # cooldown would otherwise wait for it.
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_hub_mode_off_stops_control(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    await select_mode(hass, "select.cover_control_mode", "off")

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "disabled"
    assert decision.attributes["reason_code"] == "mode_off"
    assert decision.attributes["mode"] == "off"


async def test_a_cover_follows_the_hub_until_it_has_a_mode_of_its_own(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene(position=50, tilt=45)  # already shaded, so nothing is in flight
    await setup_entry(entry)
    assert hass.states.get("select.raffstore_mode").state == "hub"

    await select_mode(hass, "select.cover_control_mode", "heat")
    runtime = next(iter(entry.runtime_data.runtimes.values()))
    assert runtime.events[-1]["cause"] == "mode_changed", "ended at once"
    assert runtime.events[-1]["position"] == 100
    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.attributes["reason_code"] == "mode_excludes"

    await select_mode(hass, "select.raffstore_mode", "cool")
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"


async def test_the_enable_switches_carry_over_into_the_mode(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene
) -> None:
    """A cover switched off before the upgrade stays off after it."""
    subentry_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{subentry_id}_enabled",
        config_entry=entry,
        suggested_object_id="raffstore_enabled",
    )
    mock_restore_cache(hass, [State("switch.raffstore_enabled", "off")])
    set_scene()

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("select.raffstore_mode").state == "off"
    assert hass.states.get("select.cover_control_mode").state == "auto"
    assert registry.async_get("switch.raffstore_enabled") is None, "left behind"


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
