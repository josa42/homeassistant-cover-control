"""Manual-override detection, motor protection and failure handling."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import SETTLE_TIME

from .conftest import COVER


def runtime(entry: MockConfigEntry):
    return next(iter(entry.runtime_data.runtimes.values()))


async def report_position(
    hass: HomeAssistant, position: int, context: Context | None = None
) -> None:
    """Report a cover position, as the device itself would."""
    hass.states.async_set(
        COVER,
        "open",
        {
            "current_position": position,
            "current_tilt_position": 100,
            "supported_features": 255,
        },
        context=context or Context(),
    )
    await hass.async_block_till_done()


async def arrive(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Let the cover report that it reached the position we commanded.

    Mock services record the call without moving anything, so without this the
    cover would keep reporting its old position and no state change would fire.
    """
    await report_position(hass, runtime(entry).expected_position)


async def human_moves(hass: HomeAssistant, position: int) -> None:
    """Someone presses the wall switch: a foreign context, a real change."""
    await report_position(hass, position, context=Context())


async def test_shading_starts_an_episode(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)
    assert runtime(entry).state.active
    assert runtime(entry).expected_position == 50


async def test_a_foreign_move_after_settling_is_a_manual_override(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    set_scene()
    await setup_entry(entry)
    await arrive(hass, entry)
    assert not runtime(entry).state.override

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 100)

    assert runtime(entry).state.override


async def test_our_own_command_is_never_an_override(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    """Context is conclusive when it matches, even long after the command."""
    set_scene()
    await setup_entry(entry)
    ours = next(iter(runtime(entry)._contexts))

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await report_position(hass, 20, context=Context(id=ours))

    assert not runtime(entry).state.override


async def test_a_child_context_is_still_ours(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    set_scene()
    await setup_entry(entry)
    ours = next(iter(runtime(entry)._contexts))

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await report_position(hass, 20, context=Context(parent_id=ours))

    assert not runtime(entry).state.override


async def test_position_reports_while_travelling_are_not_overrides(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """Radio covers report their own position with a fresh context mid-travel."""
    set_scene()
    await setup_entry(entry)

    await human_moves(hass, 80)  # still on its way down to 50
    assert not runtime(entry).state.override


async def test_landing_near_our_target_is_not_an_override(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    """A cover that stops a couple of percent off is not a human."""
    set_scene()
    await setup_entry(entry)

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 53)

    assert not runtime(entry).state.override


async def test_no_override_is_recorded_outside_an_episode(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    """With no episode running the integration is not driving it."""
    set_scene(outdoor="18.0")
    await setup_entry(entry)
    assert not runtime(entry).state.active

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 10)

    assert not runtime(entry).state.override


async def test_resume_button_hands_control_back(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    set_scene()
    await setup_entry(entry)
    await arrive(hass, entry)
    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 100)
    assert runtime(entry).state.override

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.raffstore_resume"}, blocking=True
    )
    await hass.async_block_till_done()

    assert not runtime(entry).state.override


async def test_resume_all_clears_every_override(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    set_scene()
    await setup_entry(entry)
    await arrive(hass, entry)
    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 100)
    assert runtime(entry).state.override

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.cover_control_resume_all"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert not runtime(entry).state.override
    assert hass.states.get("binary_sensor.raffstore_manual_override").state == "off"


async def test_override_is_visible_on_the_binary_sensor(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    set_scene()
    await setup_entry(entry)
    await arrive(hass, entry)
    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 100)
    # The refresh is debounced, and the test clock is frozen, so drive it.
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.raffstore_manual_override").state == "on"
    assert hass.states.get("sensor.raffstore_decision").state == "override"


async def test_small_corrections_do_not_start_the_motor(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Target 50 against a current 52 is not worth a motor start."""
    set_scene(position=52)
    await setup_entry(entry)

    assert not cover_calls["position"]
    assert (
        "not moving"
        in hass.states.get("sensor.raffstore_decision").attributes["message"]
    )


async def test_storm_ignores_the_motor_protection_threshold(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Hardware protection is always worth a motor start."""
    set_scene(position=98, wind=55.0)
    await setup_entry(entry)

    assert cover_calls["position"][-1].data["position"] == 100


async def test_a_failing_cover_does_not_break_the_integration(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """One cover refusing a command must not take the whole entry down."""
    hass.services.async_remove("cover", "set_cover_position")

    set_scene()
    await setup_entry(entry)

    assert entry.state is ConfigEntryState.LOADED
    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.attributes["blocked_by"] == "command_failed"
    assert decision.state == "cooling"
