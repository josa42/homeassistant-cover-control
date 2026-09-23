"""Manual-override detection, motor protection and failure handling."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import GATE_DEBOUNCE, SETTLE_TIME

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
    set_scene(tilt=45)  # slats already right, so this is one position step
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
    set_scene(position=52, tilt=45)
    await setup_entry(entry)

    assert not cover_calls["position"]
    assert (
        "not moving"
        in hass.states.get("sensor.raffstore_decision").attributes["message"]
    )


async def test_a_cover_at_its_position_still_gets_its_slats_set(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """The position threshold must not swallow the tilt along with the travel."""
    set_scene(position=52, tilt=100)
    await setup_entry(entry)

    assert not cover_calls["position"]
    assert cover_calls["tilt"][-1].data["tilt_position"] == 45


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

    set_scene(tilt=45)  # so the position command is the one refused
    await setup_entry(entry)

    assert entry.state is ConfigEntryState.LOADED
    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.attributes["blocked_by"] == "command_failed"
    assert decision.state == "cooling"


async def report(
    hass: HomeAssistant, state: str, position: int, tilt: int, context: Context
) -> None:
    """Report a cover state exactly as the device would, travel states included."""
    hass.states.async_set(
        COVER,
        state,
        {
            "current_position": position,
            "current_tilt_position": tilt,
            "supported_features": 255,
        },
        context=context,
    )
    await hass.async_block_till_done()


async def test_a_cover_that_never_arrives_is_not_re_commanded_on_every_report(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """The oscillation: a cover that starts, gives up and reports its old position.

    Every report asked for a fresh evaluation, which re-sent the very command
    that produced the report, so the cover twitched on the coordinator's
    debounce interval for as long as the episode ran.
    """
    set_scene(tilt=45)  # slats already right, so this is one position step
    await setup_entry(entry)
    assert len(cover_calls["position"]) == 1
    ours = Context(id=next(iter(runtime(entry)._contexts)))

    # One aborted run: it sets off, stops and settles back at 100.
    for _ in range(3):
        await report(hass, "closing", 100, 100, ours)
        await report(hass, "open", 99, 95, ours)
        await report(hass, "opening", 99, 95, ours)
        await report(hass, "open", 100, 100, ours)

    assert len(cover_calls["position"]) == 1, "the command was repeated"
    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.attributes["blocked_by"] == "awaiting_travel"
    assert not decision.attributes["acted"]


async def test_the_command_is_retried_once_the_cover_has_had_its_time(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls, freezer
) -> None:
    """The resend guard is a rate limit, not a one-shot."""
    set_scene(tilt=45)  # slats already right, so this is one position step
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))

    await report(hass, "open", 100, 45, ours)
    await entry.runtime_data.async_refresh()
    assert len(cover_calls["position"]) == 1

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["position"]) == 2
    assert cover_calls["position"][-1].data["position"] == 50
    assert not cover_calls["tilt"], (
        "the slats were set for a position the cover never reached"
    )


async def test_nothing_is_sent_into_a_cover_that_is_still_moving(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls, freezer
) -> None:
    """A tilt sent mid-run is read as a new destination and abandons the run."""
    set_scene(position=52, tilt=100)  # at its position, slats still due
    await setup_entry(entry)
    assert len(cover_calls["tilt"]) == 1

    # Far enough on that the resend guard is not what holds the command back.
    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await report(hass, "closing", 52, 100, Context())
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == 1, "commanded a cover that was still moving"

    await report(hass, "open", 52, 100, Context())
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == 2, "expected the slats once the run ended"


async def test_a_travelling_cover_does_not_ask_for_an_evaluation(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, monkeypatch
) -> None:
    """Every step of a run reported is a step that must not re-open the question."""
    set_scene()
    await setup_entry(entry)

    refreshes = []

    async def record_refresh() -> None:
        refreshes.append(1)

    monkeypatch.setattr(entry.runtime_data, "async_request_refresh", record_refresh)

    await report(hass, "closing", 90, 100, Context())
    await report(hass, "opening", 90, 100, Context())
    assert refreshes == [], "a moving cover asked to be re-evaluated"

    await report(hass, "open", 90, 100, Context())
    assert len(refreshes) == 1, "a settled cover must be re-evaluated"


async def test_the_next_command_waits_for_the_cover_to_stop(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Reaching the position is not the same as being done with the run."""
    set_scene(tilt=45)  # slats already right, so this is one position step
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))
    assert len(cover_calls["position"]) == 1

    # The reported position is already the target, but the motor is still going.
    await report(hass, "opening", 50, 100, ours)
    await entry.runtime_data.async_refresh()
    assert not cover_calls["tilt"], "commanded a cover that was still moving"

    await report(hass, "open", 50, 100, ours)
    await entry.runtime_data.async_refresh()

    assert cover_calls["tilt"][-1].data["tilt_position"] == 45


async def test_a_cover_taken_over_by_hand_stops_being_driven(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Whatever is still queued was decided under conditions that no longer hold."""
    set_scene(tilt=45)  # slats already right, so this is one position step
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))
    assert len(cover_calls["position"]) == 1

    await entry.runtime_data.async_pause(runtime(entry).subentry_id)
    await hass.async_block_till_done()

    await report(hass, "open", 50, 100, ours)  # it arrives; the slats are not due
    await entry.runtime_data.async_refresh()

    assert not cover_calls["tilt"]
    assert runtime(entry).is_idle


async def test_a_storm_does_not_wait_behind_a_shading_run(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Protecting the hardware is the one thing worth cancelling a run for."""
    set_scene(tilt=45)  # slats already right, so this is one position step
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))
    assert cover_calls["position"][-1].data["position"] == 50

    await report(hass, "closing", 80, 100, ours)  # still on its way down
    set_scene(position=80, wind=55.0)
    await entry.runtime_data.async_refresh()

    assert cover_calls["position"][-1].data["position"] == 100
    assert hass.states.get("sensor.raffstore_decision").state == "storm"


async def test_a_step_the_cover_no_longer_needs_is_dropped(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    set_scene,
    setup_entry,
    cover_calls,
    freezer,
) -> None:
    """The other half of judging late: no motor start for a slat angle it has."""
    set_scene()
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))
    await report(hass, "open", 50, 45, ours)
    await entry.runtime_data.async_refresh()
    tilts = len(cover_calls["tilt"])

    set_scene(position=50, tilt=45, sun_azimuth=20.0)
    await entry.runtime_data.async_refresh()
    freezer.tick(GATE_DEBOUNCE + timedelta(minutes=1))
    set_scene(position=50, tilt=45, sun_azimuth=20.0)
    await entry.runtime_data.async_refresh()

    # It opens and the slats end up where the open wanted them anyway.
    await report(hass, "open", 100, 45, ours)
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == tilts, "started the motor for nothing"


async def test_opening_fully_asks_for_no_slat_angle(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    set_scene,
    setup_entry,
    cover_calls,
    freezer,
) -> None:
    """A raffstore at the top has wound its slats into the box.

    There is no angle left to set, so asking for one is a motor run that turns
    nothing, and on an actuator that restores the angle it had before a run it
    is a second one undoing the first.
    """
    set_scene(tilt=45)
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))
    await report(hass, "open", 50, 45, ours)
    await entry.runtime_data.async_refresh()
    tilts = len(cover_calls["tilt"])

    set_scene(position=50, tilt=45, sun_azimuth=20.0)  # the sun leaves
    await entry.runtime_data.async_refresh()
    freezer.tick(GATE_DEBOUNCE + timedelta(minutes=1))
    set_scene(position=50, tilt=45, sun_azimuth=20.0)
    await entry.runtime_data.async_refresh()

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.attributes["reason_code"] == "episode_ended"
    assert decision.attributes["target_position"] == 100
    assert decision.attributes["target_tilt"] is None, "an angle at the top"
    assert cover_calls["position"][-1].data["position"] == 100

    await report(hass, "open", 100, 45, ours)  # it arrives, slats left anywhere
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == tilts, "set an angle on a cover at the top"


async def test_the_slats_are_set_before_the_run(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """An actuator can be set up to put the slat angle back after a run.

    Setting the angle first makes that restore land on the angle we wanted,
    instead of on the one the cover happened to have before.
    """
    set_scene()  # slats wide open at 100, shading wants 45
    await setup_entry(entry)

    assert cover_calls["tilt"][-1].data["tilt_position"] == 45, "slats go first"
    assert not cover_calls["position"], "the run waits for the slats"


async def test_an_actuator_that_restores_the_angle_needs_no_correction(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Which kind of actuator it is can only be known once the run is over."""
    set_scene()
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))

    await report(hass, "open", 100, 45, ours)  # slats set
    await entry.runtime_data.async_refresh()
    assert cover_calls["position"][-1].data["position"] == 50

    await report(hass, "open", 50, 45, ours)  # it put the angle back itself
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == 1, "corrected an angle that was already right"


async def test_an_actuator_that_forgets_the_angle_is_corrected_once(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene()
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))

    await report(hass, "open", 100, 45, ours)
    await entry.runtime_data.async_refresh()

    # It arrives with the angle the run left behind, not the one we set.
    await report(hass, "open", 50, 0, ours)
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == 2
    assert cover_calls["tilt"][-1].data["tilt_position"] == 45


async def test_the_day_list_holds_only_today(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    """It is the day's list, not a rolling window, so yesterday drops out."""
    set_scene(tilt=45)
    await setup_entry(entry)
    assert runtime(entry).events, "the shading command should be in the list"

    freezer.tick(timedelta(days=1))
    await entry.runtime_data.async_pause(runtime(entry).subentry_id)
    await hass.async_block_till_done()

    kinds = [event["kind"] for event in runtime(entry).events]
    assert kinds == ["paused"], "yesterday's movements are still listed"


async def test_a_movement_is_one_entry_not_two(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """The slats and the run are two commands and one thing that happened."""
    set_scene()  # slats at 100, so both steps are due
    await setup_entry(entry)
    ours = Context(id=next(iter(runtime(entry)._contexts)))
    await report(hass, "open", 100, 45, ours)
    await entry.runtime_data.async_refresh()

    assert len(cover_calls["tilt"]) == 1
    assert len(cover_calls["position"]) == 1
    events = runtime(entry).events
    assert len(events) == 1, f"one movement, {len(events)} entries"
    assert events[0]["tilt"] == 45
    assert events[0]["position"] == 50
    assert events[0]["up"] is False


async def test_pausing_and_resuming_are_in_the_day_list(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene(tilt=45)
    await setup_entry(entry)
    subentry = runtime(entry).subentry_id

    await entry.runtime_data.async_pause(subentry)
    await entry.runtime_data.async_resume(subentry)
    await hass.async_block_till_done()

    assert [e["kind"] for e in runtime(entry).events][-2:] == ["paused", "resumed"]


async def test_a_manual_takeover_is_in_the_day_list(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, freezer
) -> None:
    set_scene(tilt=45)
    await setup_entry(entry)

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    await human_moves(hass, 100)

    last = runtime(entry).events[-1]
    assert last["kind"] == "override"
    assert last["position"] == 100
