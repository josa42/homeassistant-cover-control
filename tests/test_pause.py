"""Pause buttons, their availability, the sunrise deadline and restarts."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.cover_control.const import PAUSE_FALLBACK

PAUSE = "button.raffstore_pause"
RESUME = "button.raffstore_resume"
PAUSE_ALL = "button.cover_control_pause_all"
RESUME_ALL = "button.cover_control_resume_all"
PAUSED = "binary_sensor.raffstore_paused"


def runtime(entry: MockConfigEntry):
    return next(iter(entry.runtime_data.runtimes.values()))


def set_sunrise(hass: HomeAssistant, when) -> None:
    sun = hass.states.get("sun.sun")
    hass.states.async_set("sun.sun", sun.state, {**sun.attributes, "next_rising": when.isoformat()})


async def press(hass: HomeAssistant, entry: MockConfigEntry, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_pause_runs_until_the_next_sunrise(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene(position=50)
    await setup_entry(entry)
    sunrise = dt_util.utcnow() + timedelta(hours=9)
    set_sunrise(hass, sunrise)

    await press(hass, entry, PAUSE)

    assert runtime(entry).state.paused_until == sunrise
    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "paused"
    assert decision.attributes["blocked_by"] == "paused"
    assert hass.states.get(PAUSED).state == "on"
    assert hass.states.get(PAUSED).attributes["paused_until"] == sunrise.isoformat()


async def test_a_paused_cover_is_not_moved(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene(position=50)
    await setup_entry(entry)
    set_sunrise(hass, dt_util.utcnow() + timedelta(hours=9))
    await press(hass, entry, PAUSE)
    calls_before = len(cover_calls["position"])

    set_scene(position=50, sun_elevation=35.0)  # would move the cover to 35%
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(cover_calls["position"]) == calls_before


async def test_pause_falls_back_when_sunrise_is_unknown(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer, caplog
) -> None:
    set_scene(position=50)  # the test scene's sun.sun has no next_rising
    await setup_entry(entry)

    await press(hass, entry, PAUSE)

    assert runtime(entry).state.paused_until == dt_util.utcnow() + PAUSE_FALLBACK
    assert "reports no next_rising" in caplog.text


async def test_buttons_are_only_available_when_they_do_something(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene(position=50)
    await setup_entry(entry)
    set_sunrise(hass, dt_util.utcnow() + timedelta(hours=9))

    assert hass.states.get(PAUSE).state != "unavailable"
    assert hass.states.get(PAUSE_ALL).state != "unavailable"
    assert hass.states.get(RESUME).state == "unavailable", "nothing to resume yet"
    assert hass.states.get(RESUME_ALL).state == "unavailable"

    await press(hass, entry, PAUSE_ALL)

    assert hass.states.get(PAUSE).state == "unavailable", "already paused"
    assert hass.states.get(PAUSE_ALL).state == "unavailable"
    assert hass.states.get(RESUME).state != "unavailable"
    assert hass.states.get(RESUME_ALL).state != "unavailable"


async def test_resume_ends_a_pause_and_control_continues(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene(position=50)
    await setup_entry(entry)
    set_sunrise(hass, dt_util.utcnow() + timedelta(hours=9))
    await press(hass, entry, PAUSE)

    await press(hass, entry, RESUME)

    assert runtime(entry).state.paused_until is None
    assert hass.states.get(PAUSED).state == "off"
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"


async def test_resuming_a_pause_at_night_does_not_open_the_cover(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls, freezer
) -> None:
    """Resume must not revive the afternoon's episode, which would end and open."""
    set_scene(position=50)
    await setup_entry(entry)
    assert runtime(entry).state.active
    set_sunrise(hass, dt_util.utcnow() + timedelta(hours=15))
    await press(hass, entry, PAUSE)

    freezer.tick(timedelta(hours=6))
    set_scene(position=50, sun_elevation=-10.0)
    set_sunrise(hass, dt_util.utcnow() + timedelta(hours=9))
    calls_before = len(cover_calls["position"])
    await press(hass, entry, RESUME)
    freezer.tick(timedelta(minutes=15))  # past the debounce
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(cover_calls["position"]) == calls_before
    assert not runtime(entry).state.active


async def test_status_sensor_counts_paused_covers(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene(position=50)
    await setup_entry(entry)
    set_sunrise(hass, dt_util.utcnow() + timedelta(hours=9))
    await press(hass, entry, PAUSE)
    assert hass.states.get("sensor.cover_control_status").attributes["paused"] == 1


async def test_a_pause_survives_a_restart(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene
) -> None:
    """Episode state is rebuilt on every start; the pause must not be lost with it."""
    until = dt_util.utcnow() + timedelta(hours=6)
    mock_restore_cache(hass, [State(PAUSED, "on", {"paused_until": until.isoformat()})])
    set_scene(position=50)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert runtime(entry).is_paused
    assert hass.states.get("sensor.raffstore_decision").state == "paused"


async def test_an_expired_pause_is_not_restored(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene
) -> None:
    past = dt_util.utcnow() - timedelta(hours=1)
    mock_restore_cache(hass, [State(PAUSED, "on", {"paused_until": past.isoformat()})])
    set_scene(position=50)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert not runtime(entry).is_paused
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"
