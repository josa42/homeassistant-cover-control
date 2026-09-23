"""Tests for the decision engine: the priority chain and the gates."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.cover_control.const import (
    CONF_AZIMUTH,
    CONF_COOL_ABOVE,
    CONF_COVER_TYPE,
    CONF_FACADE,
    CONF_HEAT_BELOW,
    CONF_HOUSE_ORIENTATION,
    CONF_INDOOR_COOL_ABOVE,
    CONF_MAX_DEPTH,
    CONF_PV_OVERRIDE,
    CONF_PV_THRESHOLD,
    CONF_SEATING_POINT,
    CONF_SHADE_WINDOW_OPEN,
    CONF_SHADED_TILT,
    CONF_SHADING_STEP,
    CONF_SILL_HEIGHT,
    CONF_STORM_ACTION,
    CONF_TEMP_HYSTERESIS,
    CONF_WEATHER_STATES,
    CONF_WIND_RELEASE,
    CONF_WIND_THRESHOLD,
    CONF_WINDOW_HEIGHT,
    PV_OVERRIDE_SUSTAIN,
    CoverType,
    Facade,
    Intent,
    Reason,
    StormAction,
)
from custom_components.cover_control.engine import EpisodeState, Inputs, evaluate
from custom_components.cover_control.models import EffectiveConfig

NOW = datetime(2026, 7, 1, 13, 0)

HUB = {
    CONF_COOL_ABOVE: 25.0,
    CONF_WIND_THRESHOLD: 40.0,
    CONF_WIND_RELEASE: 30.0,
    CONF_PV_THRESHOLD: 800.0,
    CONF_SHADING_STEP: 0,
    CONF_PV_OVERRIDE: 2500.0,
    CONF_WEATHER_STATES: ["sunny", "partlycloudy"],
}

COVER = {
    CONF_COVER_TYPE: CoverType.RAFFSTORE,
    CONF_AZIMUTH: 180.0,
    CONF_WINDOW_HEIGHT: 2.0,
    CONF_SILL_HEIGHT: 0.0,
    CONF_MAX_DEPTH: 1.0,
    CONF_SHADED_TILT: 45,
    CONF_STORM_ACTION: StormAction.RETRACT_UP,
}

SUNNY_AND_HOT = {
    "now": NOW,
    "cover_available": True,
    "supports_position": True,
    "supports_tilt": True,
    "current_position": 100,
    "current_tilt": 100,
    "sun_elevation": 45.0,
    "sun_azimuth": 180.0,
    "outdoor_temp": 28.0,
    "pv_power": 1500.0,
    "weather": "sunny",
    "wind_speed": 10.0,
    "window_open": False,
}


def run(
    state: EpisodeState | None = None,
    cover: dict | None = None,
    hub: dict | None = None,
    master: bool = True,
    enabled: bool = True,
    **overrides,
):
    """Evaluate one cover with the sunny-and-hot baseline."""
    config = EffectiveConfig({**HUB, **(hub or {})}, {**COVER, **(cover or {})})
    inputs = Inputs(**{**SUNNY_AND_HOT, **overrides})
    return evaluate(
        inputs, config, state or EpisodeState(), "cover.test", master, enabled
    )


# --- the happy path ---------------------------------------------------------


def test_hot_sunny_noon_shades() -> None:
    decision, state = run()
    assert decision.intent is Intent.COOLING
    assert decision.reason is Reason.SHADING
    assert decision.target_position == 50  # 1 m allowed on a 2 m window at 45 deg
    assert decision.target_tilt == 45
    assert state.active


def test_shading_explains_itself_with_numbers() -> None:
    decision, _ = run()
    assert "2.00 m" in decision.message  # unshaded penetration
    assert "1.00 m" in decision.message  # what is allowed
    assert decision.geometry["required_glass_fraction"] == pytest.approx(0.5)
    assert decision.geometry["profile_angle"] == pytest.approx(45.0)


def test_cold_and_sunny_heats() -> None:
    decision, state = run(outdoor_temp=5.0)
    assert decision.intent is Intent.HEATING
    assert decision.reason is Reason.SOLAR_HEATING
    assert decision.target_position == 100
    assert state.active


def test_tilt_only_commanded_when_supported() -> None:
    decision, _ = run(supports_tilt=False)
    assert decision.target_position == 50
    assert decision.target_tilt is None


def test_rolladen_shades_within_its_glass_travel() -> None:
    """A Rolladen's last 25% closes light gaps, so shading stops at the seat."""
    decision, _ = run(
        cover={CONF_COVER_TYPE: CoverType.ROLLADEN, CONF_MAX_DEPTH: 0.0},
        supports_tilt=False,
    )
    assert decision.target_position == 25


def test_seating_point_override_wins_over_the_type_default() -> None:
    decision, _ = run(
        cover={
            CONF_COVER_TYPE: CoverType.ROLLADEN,
            CONF_SEATING_POINT: 40,
            CONF_MAX_DEPTH: 0.0,
        },
        supports_tilt=False,
    )
    assert decision.target_position == 40


# --- priority chain ---------------------------------------------------------


def test_storm_beats_shading() -> None:
    decision, state = run(wind_speed=55.0)
    assert decision.intent is Intent.STORM
    assert decision.target_position == 100
    assert not state.active


def test_storm_beats_manual_override() -> None:
    held = EpisodeState(active=True, intent=Intent.COOLING, override=True)
    decision, state = run(held, wind_speed=55.0)
    assert decision.intent is Intent.STORM
    assert not state.override


def test_storm_action_close_down() -> None:
    decision, _ = run(
        cover={CONF_STORM_ACTION: StormAction.CLOSE_DOWN}, wind_speed=55.0
    )
    assert decision.target_position == 0


def test_storm_action_ignore_falls_through_to_shading() -> None:
    decision, _ = run(cover={CONF_STORM_ACTION: StormAction.IGNORE}, wind_speed=55.0)
    assert decision.intent is Intent.COOLING


def test_storm_latches_until_wind_drops_below_release() -> None:
    """Between release and trigger the latch holds, so gusts do not oscillate covers."""
    _, latched = run(wind_speed=45.0)
    assert latched.storm_latched

    decision, still = run(latched, wind_speed=35.0)
    assert still.storm_latched
    assert decision.intent is Intent.STORM

    decision, cleared = run(still, wind_speed=25.0)
    assert not cleared.storm_latched
    assert decision.intent is Intent.COOLING


def test_open_window_blocks_movement() -> None:
    decision, _ = run(window_open=True)
    assert decision.intent is Intent.WINDOW_OPEN
    assert decision.target_position is None
    assert decision.blocked_by == "window_open"


def test_open_window_can_be_opted_out_per_cover() -> None:
    decision, _ = run(cover={CONF_SHADE_WINDOW_OPEN: True}, window_open=True)
    assert decision.intent is Intent.COOLING
    assert decision.target_position == 50


def test_master_switch_off_stops_everything() -> None:
    decision, _ = run(master=False)
    assert decision.intent is Intent.DISABLED
    assert decision.reason is Reason.MASTER_DISABLED


def test_cover_switch_off_stops_that_cover() -> None:
    decision, _ = run(enabled=False)
    assert decision.reason is Reason.COVER_DISABLED


def test_unavailable_cover_is_not_evaluated() -> None:
    decision, _ = run(cover_available=False)
    assert decision.intent is Intent.UNAVAILABLE


def test_missing_sun_position_is_reported_explicitly() -> None:
    """A missing sun.sun must be legible, not a silent no-op."""
    decision, _ = run(sun_elevation=None)
    assert decision.intent is Intent.UNAVAILABLE
    assert decision.reason is Reason.SUN_UNAVAILABLE
    assert decision.blocked_by == "sun_unavailable"


def test_cover_without_position_support_cannot_shade() -> None:
    decision, _ = run(supports_position=False)
    assert decision.reason is Reason.NO_POSITION_SUPPORT
    assert decision.target_position is None


# --- manual override --------------------------------------------------------


def test_override_blocks_movement_while_the_episode_runs() -> None:
    held = EpisodeState(active=True, intent=Intent.COOLING, override=True)
    decision, state = run(held)
    assert decision.intent is Intent.OVERRIDE
    assert decision.target_position is None
    assert state.override


def test_episode_end_releases_the_override_and_opens() -> None:
    stale = EpisodeState(
        active=True,
        intent=Intent.COOLING,
        override=True,
        gate_false_since=NOW - timedelta(minutes=11),
    )
    decision, state = run(stale, sun_azimuth=20.0)
    assert decision.reason is Reason.EPISODE_ENDED
    assert decision.target_position == 100
    assert not state.override
    assert not state.active


# --- debounce ---------------------------------------------------------------


def test_gates_dropping_does_not_end_the_episode_immediately() -> None:
    """A curtailing inverter or a passing cloud must not fling the covers open."""
    running = EpisodeState(active=True, intent=Intent.COOLING)
    decision, state = run(running, pv_power=0.0)
    assert decision.reason is Reason.DEBOUNCING
    assert decision.target_position is None
    assert state.active
    assert state.gate_false_since == NOW


def test_episode_ends_once_the_gates_stay_false() -> None:
    running = EpisodeState(
        active=True, intent=Intent.COOLING, gate_false_since=NOW - timedelta(minutes=11)
    )
    decision, state = run(running, pv_power=0.0)
    assert decision.reason is Reason.EPISODE_ENDED
    assert not state.active


def test_gates_recovering_cancels_the_debounce() -> None:
    wobbling = EpisodeState(
        active=True, intent=Intent.COOLING, gate_false_since=NOW - timedelta(minutes=5)
    )
    decision, state = run(wobbling)
    assert decision.intent is Intent.COOLING
    assert state.gate_false_since is None


# --- gates ------------------------------------------------------------------


def test_sun_off_the_window_does_nothing() -> None:
    decision, state = run(sun_azimuth=20.0)
    assert decision.reason is Reason.SUN_NOT_ON_WINDOW
    assert not state.active


def test_low_pv_is_not_bright_enough() -> None:
    decision, _ = run(pv_power=100.0)
    assert decision.reason is Reason.NOT_BRIGHT


def test_disallowed_weather_is_not_bright_enough() -> None:
    decision, _ = run(weather="rainy")
    assert decision.reason is Reason.NOT_BRIGHT


# --- sustained PV outranking the weather -----------------------------------


def test_high_pv_starts_the_override_timer() -> None:
    _, state = run(weather="cloudy", pv_power=4000.0)
    assert state.pv_high_since == NOW


def test_high_pv_alone_does_not_beat_the_weather_yet() -> None:
    """Twenty minutes short of the sustain period the weather still wins."""
    started = EpisodeState(pv_high_since=NOW - timedelta(minutes=19))
    decision, _ = run(started, weather="cloudy", pv_power=4000.0)
    assert decision.reason is Reason.NOT_BRIGHT


def test_sustained_high_pv_beats_a_disallowed_weather_state() -> None:
    sustained = EpisodeState(pv_high_since=NOW - timedelta(minutes=20))
    decision, _ = run(sustained, weather="cloudy", pv_power=4000.0)
    assert decision.intent is Intent.COOLING
    assert decision.reason is Reason.SHADING


def test_pv_dropping_below_the_override_resets_the_timer() -> None:
    sustained = EpisodeState(pv_high_since=NOW - timedelta(minutes=30))
    decision, state = run(sustained, weather="cloudy", pv_power=2400.0)
    assert state.pv_high_since is None
    assert decision.reason is Reason.NOT_BRIGHT


def test_the_override_timer_runs_while_the_sun_is_off_the_window() -> None:
    """Otherwise a west window would never reach the sustain period."""
    decision, state = run(sun_azimuth=20.0, pv_power=4000.0)
    assert decision.reason is Reason.SUN_NOT_ON_WINDOW
    assert state.pv_high_since == NOW


def test_a_zero_override_threshold_switches_the_override_off() -> None:
    sustained = EpisodeState(pv_high_since=NOW - timedelta(minutes=30))
    decision, state = run(
        sustained,
        hub={CONF_PV_OVERRIDE: 0.0},
        weather="cloudy",
        pv_power=9000.0,
    )
    assert state.pv_high_since is None
    assert decision.reason is Reason.NOT_BRIGHT


# --- what the sensor reports about brightness --------------------------------


def test_the_attributes_explain_a_passing_brightness_gate() -> None:
    decision, _ = run()
    attributes = decision.as_attributes()
    assert attributes["bright"] is True
    assert attributes["weather_ok"] is True


def test_the_attributes_name_the_half_that_failed() -> None:
    """Raw weather and pv readings alone never said which one blocked it."""
    decision, _ = run(weather="cloudy")
    attributes = decision.as_attributes()
    assert attributes["bright"] is False
    assert attributes["weather_ok"] is False


def test_the_attributes_carry_the_moment_the_override_engages() -> None:
    decision, _ = run(weather="cloudy", pv_power=4000.0)
    attributes = decision.as_attributes()
    assert attributes["pv_override_active"] is False
    assert attributes["pv_override_at"] == (NOW + PV_OVERRIDE_SUSTAIN).isoformat()


def test_the_attributes_report_an_engaged_override() -> None:
    sustained = EpisodeState(pv_high_since=NOW - timedelta(minutes=25))
    decision, _ = run(sustained, weather="cloudy", pv_power=4000.0)
    attributes = decision.as_attributes()
    assert attributes["pv_override_active"] is True
    assert attributes["bright"] is True


def test_there_is_no_override_moment_while_pv_is_low() -> None:
    decision, _ = run(pv_power=100.0)
    assert decision.as_attributes()["pv_override_at"] is None


def test_brightness_is_still_reported_with_the_sun_off_the_window() -> None:
    """That gate does not return early, so the sky is still described."""
    decision, _ = run(sun_azimuth=20.0, pv_power=4000.0)
    attributes = decision.as_attributes()
    assert decision.reason is Reason.SUN_NOT_ON_WINDOW
    assert attributes["bright"] is True
    assert attributes["pv_override_at"] == (NOW + PV_OVERRIDE_SUSTAIN).isoformat()


def test_brightness_is_unevaluated_when_an_earlier_gate_returns() -> None:
    """An unavailable cover is decided before the sky is ever looked at."""
    decision, _ = run(cover_available=False)
    attributes = decision.as_attributes()
    assert attributes["bright"] is None
    assert attributes["weather_ok"] is None


def test_sustained_pv_does_not_rescue_a_cold_day() -> None:
    """Brightness is only one gate; the temperature still has to call."""
    sustained = EpisodeState(pv_high_since=NOW - timedelta(minutes=30))
    decision, _ = run(sustained, weather="cloudy", pv_power=4000.0, outdoor_temp=18.0)
    assert decision.reason is Reason.TEMP_NEUTRAL


def test_pv_is_optional() -> None:
    decision, _ = run(pv_power=None)
    assert decision.intent is Intent.COOLING


def test_mild_weather_is_neutral() -> None:
    decision, _ = run(outdoor_temp=18.0)
    assert decision.reason is Reason.TEMP_NEUTRAL


def test_forecast_high_shades_before_it_is_hot_outside() -> None:
    """Shading is preventive: once the room is hot the gain already happened."""
    decision, _ = run(outdoor_temp=21.0, forecast_max=31.0)
    assert decision.intent is Intent.COOLING


def test_indoor_temperature_can_veto_shading() -> None:
    decision, _ = run(indoor_temp=19.0)
    assert decision.reason is Reason.TEMP_NEUTRAL


def test_indoor_temperature_can_confirm_shading() -> None:
    decision, _ = run(indoor_temp=26.0)
    assert decision.intent is Intent.COOLING


def test_indoor_temperature_can_veto_heating() -> None:
    decision, _ = run(outdoor_temp=5.0, indoor_temp=23.0)
    assert decision.reason is Reason.TEMP_NEUTRAL


# --- the decision record ----------------------------------------------------


def test_cover_override_beats_hub_default_and_says_so() -> None:
    decision, _ = run(cover={CONF_COOL_ABOVE: 30.0}, outdoor_temp=28.0)
    assert decision.reason is Reason.TEMP_NEUTRAL
    assert decision.settings[CONF_COOL_ABOVE] == {"value": 30.0, "source": "cover"}


def test_hub_value_is_reported_as_inherited() -> None:
    decision, _ = run()
    assert decision.settings[CONF_COOL_ABOVE] == {"value": 25.0, "source": "hub"}


def test_unset_value_falls_back_to_the_documented_default() -> None:
    decision, _ = run(hub={CONF_PV_THRESHOLD: None})
    assert decision.settings[CONF_PV_THRESHOLD]["source"] == "default"


def test_every_decision_records_the_gates_it_applied() -> None:
    decision, _ = run()
    names = [gate.name for gate in decision.gates]
    assert names == [
        "cover_available",
        "master_enabled",
        "cover_enabled",
        "storm",
        "window_closed",
        "not_paused",
        "sun_available",
        "sun_on_window",
        "bright",
        "temperature",
    ]
    assert all(gate.detail or gate.passed for gate in decision.gates)


def test_compact_attributes_stay_flat_for_the_recorder() -> None:
    decision, _ = run()
    attributes = decision.as_attributes()
    assert not any(isinstance(value, (dict, list)) for value in attributes.values())
    assert attributes["reason_code"] == "shading"


def test_full_record_is_serialisable() -> None:
    import json

    decision, _ = run()
    assert json.loads(json.dumps(decision.as_dict()))["reason_code"] == "shading"


# --- pause ------------------------------------------------------------------


def test_a_pause_leaves_the_cover_alone() -> None:
    paused = EpisodeState(paused_until=NOW + timedelta(hours=8))
    decision, state = run(paused)
    assert decision.intent is Intent.PAUSED
    assert decision.reason is Reason.PAUSED
    assert decision.target_position is None
    assert decision.blocked_by == "paused"
    assert state.paused_until == NOW + timedelta(hours=8)


def test_a_pause_expires_on_the_clock() -> None:
    """At the deadline control resumes in the same evaluation, not one later."""
    expired = EpisodeState(paused_until=NOW)
    decision, state = run(expired)
    assert decision.intent is Intent.COOLING
    assert state.paused_until is None


def test_storm_outranks_a_pause_without_cancelling_it() -> None:
    """Hardware protection still acts, and the cover is still paused afterwards."""
    until = NOW + timedelta(hours=8)
    decision, state = run(EpisodeState(paused_until=until), wind_speed=55.0)
    assert decision.intent is Intent.STORM
    assert decision.target_position == 100
    assert state.paused_until == until

    decision, state = run(state, wind_speed=10.0)
    assert decision.intent is Intent.PAUSED
    assert state.paused_until == until


def test_an_open_window_still_reports_first_while_paused() -> None:
    decision, _ = run(EpisodeState(paused_until=NOW + timedelta(hours=8)), window_open=True)
    assert decision.intent is Intent.WINDOW_OPEN


def test_a_pause_ending_overnight_does_not_open_the_cover() -> None:
    """Regression: a pause pressed during an afternoon episode kept that episode
    frozen overnight. When the pause ran out after sunrise the episode ended,
    and ending an episode opens the cover fully."""
    _, afternoon = run(EpisodeState(), now=NOW)
    assert afternoon.active
    sunrise = NOW + timedelta(hours=15, minutes=50)
    paused = replace(afternoon, override=True, paused_until=sunrise)

    morning = dict(sun_azimuth=70.0, sun_elevation=3.0, outdoor_temp=14.0)
    first, state = run(paused, now=sunrise + timedelta(minutes=5), **morning)
    later, state = run(state, now=sunrise + timedelta(minutes=20), **morning)

    for decision in (first, later):
        assert decision.target_position is None
        assert decision.reason is not Reason.EPISODE_ENDED
    assert not state.active
    assert not state.override, "the stale episode's override goes with it"


# --- which way the window faces -------------------------------------------


@pytest.mark.parametrize(
    ("facade", "expected"),
    [(Facade.SOUTH, 180.0), (Facade.WEST, 270.0), (Facade.NORTH, 0.0), (Facade.EAST, 90.0)],
)
def test_a_square_house_puts_each_side_on_its_compass_point(
    facade: Facade, expected: float
) -> None:
    decision, _ = run(cover={CONF_AZIMUTH: None, CONF_FACADE: facade})
    assert decision.geometry["window_azimuth"] == expected


@pytest.mark.parametrize(
    ("facade", "expected"),
    [(Facade.SOUTH, 195.0), (Facade.WEST, 285.0), (Facade.NORTH, 15.0), (Facade.EAST, 105.0)],
)
def test_a_house_off_the_grid_turns_every_side_with_it(
    facade: Facade, expected: float
) -> None:
    """The whole point: correct the house once, not every window."""
    decision, _ = run(
        cover={CONF_AZIMUTH: None, CONF_FACADE: facade},
        hub={CONF_HOUSE_ORIENTATION: 195.0},
    )
    assert decision.geometry["window_azimuth"] == expected


def test_a_window_with_its_own_bearing_ignores_the_house() -> None:
    """A bay or a dormer sits on none of the four sides."""
    decision, _ = run(
        cover={CONF_AZIMUTH: 135.0, CONF_FACADE: Facade.SOUTH},
        hub={CONF_HOUSE_ORIENTATION: 195.0},
    )
    assert decision.geometry["window_azimuth"] == 135.0


def test_a_cover_set_up_before_the_house_was_keeps_its_bearing() -> None:
    """The baseline fixture is a cover from before sides existed: a bearing
    and nothing else. Adding the house must not move a single one of them."""
    assert CONF_AZIMUTH in COVER and CONF_FACADE not in COVER
    decision, _ = run(hub={CONF_HOUSE_ORIENTATION: 195.0})
    assert decision.geometry["window_azimuth"] == COVER[CONF_AZIMUTH]


# --- hysteresis -------------------------------------------------------------


def test_a_sensor_resting_on_the_threshold_does_not_end_the_episode() -> None:
    """The case from a real morning: indoor alternating 22.0 / 22.1 against 22.

    Every crossing ended the episode and started it again a few minutes later,
    so the cover drove its whole travel twice per wobble.
    """
    running = EpisodeState(active=True, intent=Intent.COOLING)
    decision, state = run(
        running,
        hub={CONF_INDOOR_COOL_ABOVE: 22.0, CONF_TEMP_HYSTERESIS: 0.5},
        indoor_temp=22.0,
    )
    assert decision.reason is Reason.SHADING, "a tenth of a degree dropped the gates"
    assert state.gate_false_since is None, "the episode started counting itself out"


def test_the_hysteresis_only_holds_an_episode_that_is_already_running() -> None:
    """Relaxing the threshold before anything runs would just lower it."""
    decision, state = run(
        hub={CONF_INDOOR_COOL_ABOVE: 22.0, CONF_TEMP_HYSTERESIS: 0.5},
        indoor_temp=22.0,
    )
    assert decision.intent is Intent.NEUTRAL
    assert not state.active


def test_a_real_drop_still_ends_the_episode() -> None:
    """Held, not latched: past the relaxed threshold it goes."""
    running = EpisodeState(active=True, intent=Intent.COOLING)
    decision, state = run(
        running,
        hub={CONF_INDOOR_COOL_ABOVE: 22.0, CONF_TEMP_HYSTERESIS: 0.5},
        indoor_temp=21.4,
    )
    assert decision.reason is Reason.DEBOUNCING, "the gates should have dropped"
    assert state.gate_false_since == NOW


def test_solar_heating_is_held_from_the_other_side() -> None:
    """Heating starts below a threshold, so its hysteresis relaxes upwards."""
    running = EpisodeState(active=True, intent=Intent.HEATING)
    decision, state = run(
        running,
        hub={CONF_HEAT_BELOW: 12.0, CONF_TEMP_HYSTERESIS: 0.5},
        outdoor_temp=12.3,
        indoor_temp=19.0,
        forecast_max=12.3,
    )
    assert decision.intent is Intent.HEATING
    assert state.active


def test_a_cooling_episode_does_not_relax_the_heating_threshold() -> None:
    """The hysteresis belongs to the episode that is running, not to both."""
    running = EpisodeState(active=True, intent=Intent.COOLING)
    decision, _ = run(
        running,
        hub={CONF_HEAT_BELOW: 12.0, CONF_TEMP_HYSTERESIS: 0.5},
        outdoor_temp=12.3,
        forecast_max=12.3,
        indoor_temp=19.0,
    )
    assert decision.intent is not Intent.HEATING


# --- shading steps ----------------------------------------------------------


def test_shading_snaps_to_the_step() -> None:
    """Same window and sun as the happy path, which lands on 50% unrounded."""
    decision, _ = run(hub={CONF_SHADING_STEP: 25})
    assert decision.target_position == 50


def test_a_target_between_steps_rounds_towards_more_cover() -> None:
    decision, _ = run(hub={CONF_SHADING_STEP: 25}, sun_elevation=35.0)
    assert decision.geometry["required_glass_fraction"] > 0.25
    assert decision.geometry["glass_fraction"] == 0.25
    assert decision.target_position == 25


def test_the_record_keeps_what_the_geometry_asked_for() -> None:
    """So the debug view can say the step rounded it, not the sun."""
    decision, _ = run(hub={CONF_SHADING_STEP: 25}, sun_elevation=35.0)
    assert decision.geometry["shading_step"] == 25
    assert decision.geometry["required_glass_fraction"] != (
        decision.geometry["glass_fraction"]
    )


def test_the_reported_depth_is_the_one_the_cover_will_actually_let_in() -> None:
    stepped, _ = run(hub={CONF_SHADING_STEP: 25}, sun_elevation=35.0)
    smooth, _ = run(hub={CONF_SHADING_STEP: 0}, sun_elevation=35.0)
    assert stepped.geometry["penetration_depth"] < smooth.geometry["penetration_depth"]


def test_covers_step_by_a_quarter_of_the_glass_out_of_the_box() -> None:
    """Nothing configured must not mean following the sun by the percent."""
    decision, _ = run(hub={CONF_SHADING_STEP: None})  # unset, so the default
    assert decision.geometry["shading_step"] == 25.0
    assert decision.geometry["glass_fraction"] in (0.0, 0.25, 0.5, 0.75, 1.0)


def test_a_roller_shutter_steps_by_glass_and_not_by_travel() -> None:
    """Its light gaps sit below the seating point, so the two differ.

    A quarter of the glass is 18.75 points of travel here, which lands on 62.
    Stepping the travel instead would land on 50 and cover a third more.
    """
    decision, _ = run(
        cover={CONF_COVER_TYPE: CoverType.ROLLADEN},
        hub={CONF_SHADING_STEP: 25},
    )
    assert decision.geometry["glass_fraction"] == 0.5
    assert decision.target_position == 62


def test_a_cover_can_step_differently_from_the_rest_of_the_house() -> None:
    """The hub value is the house default; a window may disagree with it."""
    decision, _ = run(
        hub={CONF_SHADING_STEP: 25},
        cover={CONF_SHADING_STEP: 50},
    )
    assert decision.geometry["shading_step"] == 50


def test_a_cover_with_no_step_of_its_own_follows_the_hub() -> None:
    decision, _ = run(hub={CONF_SHADING_STEP: 25}, cover={CONF_SHADING_STEP: None})
    assert decision.geometry["shading_step"] == 25


def test_one_cover_can_switch_stepping_off_while_the_rest_keep_it() -> None:
    """0 is a real value, not an empty field, so it has to win over the hub."""
    stepped, _ = run(hub={CONF_SHADING_STEP: 25}, sun_elevation=35.0)
    smooth, _ = run(
        hub={CONF_SHADING_STEP: 25}, cover={CONF_SHADING_STEP: 0}, sun_elevation=35.0
    )
    assert stepped.geometry["glass_fraction"] == 0.25
    assert smooth.geometry["glass_fraction"] == smooth.geometry[
        "required_glass_fraction"
    ]
