"""The decision engine.

A pure function of (inputs, config, previous state). It never touches Home
Assistant and never moves anything: it returns a :class:`Decision` describing
what should happen and why, plus the new episode state. The caller is
responsible for actually sending commands.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from . import geometry
from .const import (
    CONF_AZIMUTH,
    CONF_COOL_ABOVE,
    CONF_FACADE,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_HEAT_BELOW,
    CONF_HOUSE_ORIENTATION,
    CONF_INDOOR_COOL_ABOVE,
    CONF_INDOOR_HEAT_BELOW,
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
    COVER_DEFAULTS,
    DEFAULT_SEATING_POINT,
    FACADE_OFFSET,
    GATE_DEBOUNCE,
    PV_OVERRIDE_SUSTAIN,
    CoverType,
    Facade,
    Intent,
    Reason,
    StormAction,
)
from .models import Decision, EffectiveConfig, Gate


@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything the engine is allowed to look at."""

    now: datetime
    cover_available: bool = False
    supports_position: bool = False
    supports_tilt: bool = False
    current_position: int | None = None
    current_tilt: int | None = None
    #: The motor is running right now. The engine ignores it; it is what stops
    #: a command being sent into a run that is still going.
    is_moving: bool = False
    sun_elevation: float | None = None
    sun_azimuth: float | None = None
    outdoor_temp: float | None = None
    forecast_max: float | None = None
    indoor_temp: float | None = None
    pv_power: float | None = None
    weather: str | None = None
    wind_speed: float | None = None
    window_open: bool | None = None


@dataclass(frozen=True, slots=True)
class EpisodeState:
    """Runtime state carried between evaluations."""

    active: bool = False
    intent: Intent | None = None
    override: bool = False
    storm_latched: bool = False
    gate_false_since: datetime | None = None
    #: Set by the pause button. Until this moment nothing but storm protection
    #: touches the cover. Unlike ``override``, which the engine releases when
    #: the episode ends, this one expires on the clock.
    paused_until: datetime | None = None
    #: Since when PV power has been continuously above the weather override
    #: threshold. Tracks the sky rather than the episode, so it survives
    #: everything the episode bookkeeping resets.
    pv_high_since: datetime | None = None


def released_from_pause(state: EpisodeState) -> EpisodeState:
    """The state a cover returns to when a pause ends, however it ends.

    Only the storm latch and the PV timer survive: both track the weather,
    not the episode.
    """
    return EpisodeState(
        storm_latched=state.storm_latched, pv_high_since=state.pv_high_since
    )


def _seating_point(config: EffectiveConfig) -> int:
    """Per-cover seating point, falling back to the cover type's default."""
    explicit = config.cover(CONF_SEATING_POINT)
    if explicit is not None:
        return int(explicit)
    cover_type = CoverType(config.cover("cover_type", CoverType.OTHER))
    return DEFAULT_SEATING_POINT[cover_type]


def _cover_setting(config: EffectiveConfig, key: str):
    return config.cover(key, COVER_DEFAULTS.get(key))


def _window_azimuth(config: EffectiveConfig) -> float:
    """Which way the window faces, in degrees.

    Normally the side of the house it is on, turned by however far the house
    is off the compass. A window that sits on neither of the four sides, in a
    bay or a dormer, carries its own bearing and that wins.
    """
    explicit = config.cover(CONF_AZIMUTH)
    if explicit is not None:
        return float(explicit)
    facade = Facade(_cover_setting(config, CONF_FACADE))
    orientation = float(config.get(CONF_HOUSE_ORIENTATION))
    return (orientation + FACADE_OFFSET[facade]) % 360.0


def evaluate(
    inputs: Inputs,
    config: EffectiveConfig,
    state: EpisodeState,
    cover_entity: str,
    master_enabled: bool,
    cover_enabled: bool,
) -> tuple[Decision, EpisodeState]:
    """Evaluate one cover and return its decision plus the new state."""
    gates: list[Gate] = []
    brightness: dict[str, Any] = {}
    raw_inputs = {
        "sun_elevation": inputs.sun_elevation,
        "sun_azimuth": inputs.sun_azimuth,
        "outdoor_temp": inputs.outdoor_temp,
        "forecast_max": inputs.forecast_max,
        "indoor_temp": inputs.indoor_temp,
        "pv_power": inputs.pv_power,
        "weather": inputs.weather,
        "wind_speed": inputs.wind_speed,
        "window_open": inputs.window_open,
        "current_position": inputs.current_position,
        "current_tilt": inputs.current_tilt,
    }

    def decide(
        intent: Intent,
        reason: Reason,
        message: str,
        *,
        position: int | None = None,
        tilt: int | None = None,
        blocked_by: str | None = None,
        geom: dict | None = None,
        new_state: EpisodeState | None = None,
    ) -> tuple[Decision, EpisodeState]:
        if position == 100:
            # A raffstore driven fully up has wound its slats into the box, so
            # there is no angle left to set. Asking for one is a motor run that
            # turns nothing, and on an actuator that restores the angle it had
            # before a run it is a second one undoing the first.
            tilt = None
        decision = Decision(
            timestamp=inputs.now,
            cover_entity=cover_entity,
            intent=intent,
            reason=reason,
            message=message,
            target_position=position,
            target_tilt=tilt,
            blocked_by=blocked_by,
            episode_active=(new_state or state).active,
            inputs=raw_inputs,
            gates=gates,
            geometry=geom or {},
            settings=config.snapshot(),
            brightness=brightness,
        )
        return decision, (new_state if new_state is not None else state)

    # --- sustained PV, tracked before any gate can return early ------------
    # The timer has to run even while the cover is unavailable or the sun is
    # off this window, otherwise a west-facing cover would start counting at
    # the moment the sun arrives and never reach the sustain period on the
    # afternoon it matters.
    pv_override = float(config.get(CONF_PV_OVERRIDE) or 0.0)
    pv_high = (
        pv_override > 0
        and inputs.pv_power is not None
        and inputs.pv_power >= pv_override
    )
    pv_high_since = (state.pv_high_since or inputs.now) if pv_high else None
    pv_sustained = (
        pv_high_since is not None and inputs.now - pv_high_since >= PV_OVERRIDE_SUSTAIN
    )
    state = replace(state, pv_high_since=pv_high_since)
    brightness["pv_override_active"] = pv_sustained
    # When the override takes over, rather than how long it has been
    # waiting: the question people actually ask is how much longer.
    brightness["pv_override_at"] = (
        (pv_high_since + PV_OVERRIDE_SUSTAIN).isoformat()
        if pv_high_since is not None
        else None
    )

    # --- availability and enable switches ---------------------------------
    if not inputs.cover_available:
        gates.append(Gate("cover_available", False, "cover entity is unavailable"))
        return decide(
            Intent.UNAVAILABLE,
            Reason.COVER_UNAVAILABLE,
            "Cover entity is unavailable; nothing evaluated.",
            blocked_by="cover_unavailable",
        )
    gates.append(Gate("cover_available", True))

    if not master_enabled:
        gates.append(Gate("master_enabled", False, "hub switch is off"))
        return decide(
            Intent.DISABLED,
            Reason.MASTER_DISABLED,
            "Cover Control is switched off globally.",
            blocked_by="master_switch",
        )
    gates.append(Gate("master_enabled", True))

    if not cover_enabled:
        gates.append(Gate("cover_enabled", False, "per-cover switch is off"))
        return decide(
            Intent.DISABLED,
            Reason.COVER_DISABLED,
            "Control for this cover is switched off.",
            blocked_by="cover_switch",
        )
    gates.append(Gate("cover_enabled", True))

    # --- storm, which outranks everything including override ---------------
    storm_action = StormAction(_cover_setting(config, CONF_STORM_ACTION))
    threshold = float(config.get(CONF_WIND_THRESHOLD))
    release = float(config.get(CONF_WIND_RELEASE))
    wind = inputs.wind_speed
    storm_latched = state.storm_latched
    if wind is not None:
        if wind >= threshold:
            storm_latched = True
        elif wind <= release:
            storm_latched = False
    gates.append(
        Gate(
            "storm",
            storm_latched,
            f"wind {wind} km/h vs trigger {threshold} / release {release}",
        )
    )

    if storm_latched and storm_action is not StormAction.IGNORE:
        target = 100 if storm_action is StormAction.RETRACT_UP else 0
        new_state = EpisodeState(
            active=False,
            intent=None,
            override=False,
            storm_latched=True,
            gate_false_since=None,
            # A storm outranks a pause for the length of the storm, but it does
            # not cancel it: once the wind drops the cover stays paused.
            paused_until=state.paused_until,
            pv_high_since=pv_high_since,
        )
        return decide(
            Intent.STORM,
            Reason.STORM_WIND,
            f"Storm protection: wind {wind} km/h reached the {threshold} km/h "
            f"threshold, moving to {target}%.",
            position=target,
            tilt=100 if inputs.supports_tilt else None,
            new_state=new_state,
        )

    state = replace(state, storm_latched=storm_latched)

    # --- window contact -----------------------------------------------------
    shade_with_open = bool(_cover_setting(config, CONF_SHADE_WINDOW_OPEN))
    if inputs.window_open and not shade_with_open:
        gates.append(Gate("window_closed", False, "window contact reports open"))
        return decide(
            Intent.WINDOW_OPEN,
            Reason.WINDOW_IS_OPEN,
            "Window is open, so the cover is left alone.",
            blocked_by="window_open",
        )
    gates.append(
        Gate(
            "window_closed",
            True,
            "shading continues with the window open" if inputs.window_open else "",
        )
    )

    # --- pause, which the user asked for by hand ---------------------------
    # Deliberately before the episode bookkeeping: while paused the engine
    # freezes rather than tracking gates it is not allowed to act on.
    if state.paused_until is not None and inputs.now >= state.paused_until:
        # Whatever episode was running when the pause started is hours old. If
        # it resumed, it would find the sun gone and end, and ending an episode
        # opens the cover: a pause pressed on a hot afternoon would open the
        # bedroom blinds just after sunrise. Start fresh instead, without a
        # command; a new episode begins once the conditions call for one.
        state = released_from_pause(state)
    gates.append(
        Gate(
            "not_paused",
            state.paused_until is None,
            ""
            if state.paused_until is None
            else f"paused until {state.paused_until.isoformat()}",
        )
    )
    if state.paused_until is not None:
        return decide(
            Intent.PAUSED,
            Reason.PAUSED,
            "Paused by hand; leaving this cover alone until the next sunrise.",
            blocked_by="paused",
            new_state=state,
        )

    # --- solar gates --------------------------------------------------------
    if inputs.sun_elevation is None or inputs.sun_azimuth is None:
        gates.append(Gate("sun_available", False, "sun.sun reports no position"))
        return decide(
            Intent.UNAVAILABLE,
            Reason.SUN_UNAVAILABLE,
            "Sun position is unavailable, so no geometry can be computed.",
            blocked_by="sun_unavailable",
        )
    gates.append(Gate("sun_available", True))

    azimuth = _window_azimuth(config)
    fov_left = float(_cover_setting(config, CONF_FOV_LEFT))
    fov_right = float(_cover_setting(config, CONF_FOV_RIGHT))
    elevation = inputs.sun_elevation
    sun_azimuth = inputs.sun_azimuth

    delta = geometry.azimuth_delta(sun_azimuth, azimuth)
    on_window = geometry.sun_on_window(elevation, delta, fov_left, fov_right)
    profile = geometry.profile_angle(elevation, delta) if on_window else 0.0
    gates.append(
        Gate(
            "sun_on_window",
            on_window,
            f"sun at {delta:+.1f} deg from the window normal, "
            f"elevation {elevation:.1f} deg, field of view -{fov_left}/+{fov_right}",
        )
    )

    allowed_states = config.get(CONF_WEATHER_STATES) or []
    pv_threshold = float(config.get(CONF_PV_THRESHOLD))
    weather_ok = inputs.weather is None or inputs.weather in allowed_states
    pv_ok = inputs.pv_power is None or inputs.pv_power > pv_threshold
    # Sustained PV outranks the weather condition. A forecast reporting
    # cloudy while the roof has been making full power for twenty minutes is
    # wrong about this house, and the inverter is the instrument actually
    # measuring the light falling on it.
    bright = (weather_ok and pv_ok) or pv_sustained
    detail = (
        f"weather {inputs.weather!r} allowed={weather_ok}, "
        f"pv {inputs.pv_power} W > {pv_threshold} W = {pv_ok}"
    )
    if pv_sustained:
        detail += (
            f", weather overridden by pv >= {pv_override} W since {pv_high_since:%H:%M}"
        )
    gates.append(Gate("bright", bright, detail))
    brightness["bright"] = bright
    brightness["weather_ok"] = weather_ok

    cool_above = float(config.get(CONF_COOL_ABOVE))
    heat_below = float(config.get(CONF_HEAT_BELOW))
    indoor_cool = float(config.get(CONF_INDOOR_COOL_ABOVE))
    indoor_heat = float(config.get(CONF_INDOOR_HEAT_BELOW))

    # A sensor resting on a threshold crosses it on its own noise, which ends
    # the episode and starts it again a minute later, all day. While an episode
    # runs, the thresholds that started it are relaxed by the hysteresis, so
    # only a real change in temperature ends it.
    hysteresis = float(config.get(CONF_TEMP_HYSTERESIS))
    holding_cool = state.active and state.intent is Intent.COOLING
    holding_heat = state.active and state.intent is Intent.HEATING
    cool_at = cool_above - hysteresis if holding_cool else cool_above
    indoor_cool_at = indoor_cool - hysteresis if holding_cool else indoor_cool
    heat_at = heat_below + hysteresis if holding_heat else heat_below
    indoor_heat_at = indoor_heat + hysteresis if holding_heat else indoor_heat

    outdoor_hot = inputs.outdoor_temp is not None and inputs.outdoor_temp > cool_at
    forecast_hot = inputs.forecast_max is not None and inputs.forecast_max > cool_at
    indoor_confirms_cool = (
        inputs.indoor_temp is None or inputs.indoor_temp > indoor_cool_at
    )
    wants_cooling = (outdoor_hot or forecast_hot) and indoor_confirms_cool

    outdoor_cold = inputs.outdoor_temp is not None and inputs.outdoor_temp < heat_at
    indoor_confirms_heat = (
        inputs.indoor_temp is None or inputs.indoor_temp < indoor_heat_at
    )
    wants_heating = outdoor_cold and indoor_confirms_heat

    gates.append(
        Gate(
            "temperature",
            wants_cooling or wants_heating,
            f"outdoor {inputs.outdoor_temp} / forecast max {inputs.forecast_max} "
            f"vs cool>{cool_at} heat<{heat_at}; "
            f"indoor {inputs.indoor_temp} vs cool>{indoor_cool_at} "
            f"heat<{indoor_heat_at}"
            + (f"; held by {hysteresis} C" if holding_cool or holding_heat else ""),
        )
    )

    desired: Intent
    if on_window and bright and wants_cooling:
        desired = Intent.COOLING
    elif on_window and bright and wants_heating:
        desired = Intent.HEATING
    else:
        desired = Intent.NEUTRAL

    geom = {
        "window_azimuth": azimuth,
        "azimuth_delta": round(delta, 2),
        "sun_elevation": round(elevation, 2),
        "profile_angle": round(profile, 2),
        "sun_on_window": on_window,
    }

    # --- episode bookkeeping ------------------------------------------------
    if desired in (Intent.COOLING, Intent.HEATING):
        state = EpisodeState(
            active=True,
            intent=desired,
            override=state.override,
            storm_latched=storm_latched,
            gate_false_since=None,
            paused_until=state.paused_until,
            pv_high_since=pv_high_since,
        )
    elif state.active:
        # An episode is running but the gates no longer support it. Hold the
        # cover until the gates have been false long enough to be believed;
        # a passing cloud or a curtailing inverter must not end the episode.
        since = state.gate_false_since or inputs.now
        if inputs.now - since < GATE_DEBOUNCE:
            state = replace(state, gate_false_since=since)
            failing = (
                "sun left the window"
                if not on_window
                else "it is no longer bright"
                if not bright
                else "the temperature no longer calls for it"
            )
            remaining = GATE_DEBOUNCE - (inputs.now - since)
            return decide(
                state.intent or Intent.NEUTRAL,
                Reason.DEBOUNCING,
                f"Holding position: {failing}, waiting "
                f"{int(remaining.total_seconds() // 60)} more minutes before "
                "ending the episode.",
                blocked_by="debounce",
                geom=geom,
                new_state=state,
            )
        # Debounce elapsed: the episode is genuinely over.
        state = EpisodeState(
            active=False,
            intent=None,
            override=False,
            storm_latched=storm_latched,
            gate_false_since=None,
            paused_until=state.paused_until,
            pv_high_since=pv_high_since,
        )
        return decide(
            Intent.NEUTRAL,
            Reason.EPISODE_ENDED,
            "Episode ended, opening fully and releasing any manual override.",
            position=100,
            tilt=100 if inputs.supports_tilt else None,
            geom=geom,
            new_state=state,
        )

    # --- manual override blocks movement, but not the bookkeeping above -----
    if state.override:
        return decide(
            Intent.OVERRIDE,
            Reason.MANUAL_OVERRIDE,
            "Manually moved; leaving it alone until this episode ends.",
            blocked_by="manual_override",
            geom=geom,
        )

    if desired is Intent.NEUTRAL:
        if not on_window:
            reason, message = Reason.SUN_NOT_ON_WINDOW, "Sun is not on this window."
        elif not bright:
            reason, message = Reason.NOT_BRIGHT, "Not bright enough to act."
        else:
            reason, message = (
                Reason.TEMP_NEUTRAL,
                "Temperature calls for neither shading nor solar heating.",
            )
        return decide(Intent.NEUTRAL, reason, message, geom=geom)

    if not inputs.supports_position:
        return decide(
            desired,
            Reason.NO_POSITION_SUPPORT,
            "Cover does not report or accept a position, so it cannot be shaded.",
            blocked_by="no_position_support",
            geom=geom,
        )

    # --- geometry decides the number ---------------------------------------
    seating = _seating_point(config)
    tilt_angle = int(_cover_setting(config, CONF_SHADED_TILT))

    if desired is Intent.HEATING:
        geom["penetration_depth"] = round(
            geometry.penetration_depth(
                1.0,
                float(_cover_setting(config, CONF_SILL_HEIGHT)),
                float(config.cover(CONF_WINDOW_HEIGHT, 1.0)),
                profile,
            ),
            2,
        )
        return decide(
            Intent.HEATING,
            Reason.SOLAR_HEATING,
            f"Solar heating: outdoor {inputs.outdoor_temp} C is below "
            f"{heat_below} C and the sun is on the window, opening fully.",
            position=100,
            tilt=100 if inputs.supports_tilt else None,
            geom=geom,
            new_state=state,
        )

    max_depth = float(_cover_setting(config, CONF_MAX_DEPTH))
    sill = float(_cover_setting(config, CONF_SILL_HEIGHT))
    height = float(config.cover(CONF_WINDOW_HEIGHT, 1.0))
    step = float(config.get(CONF_SHADING_STEP))
    ideal = geometry.required_glass_fraction(max_depth, sill, height, profile)
    # Everything below reports the stepped fraction, because that is what the
    # cover is about to do. The ideal is kept beside it so the record shows
    # what the geometry asked for before the step rounded it down.
    fraction = geometry.step_glass_fraction(ideal, step)
    position = geometry.glass_to_position(fraction, seating)

    geom.update(
        {
            "max_penetration_depth": max_depth,
            "sill_height": sill,
            "window_height": height,
            "seating_point": seating,
            "shading_step": step,
            "required_glass_fraction": round(ideal, 3),
            "glass_fraction": round(fraction, 3),
            "penetration_depth": round(
                geometry.penetration_depth(fraction, sill, height, profile), 2
            ),
        }
    )

    return decide(
        Intent.COOLING,
        Reason.SHADING,
        f"Shading to {position}%: the sun would otherwise reach "
        f"{geometry.penetration_depth(1.0, sill, height, profile):.2f} m into "
        f"the room, and at most {max_depth:.2f} m is allowed.",
        position=position,
        tilt=tilt_angle if inputs.supports_tilt else None,
        geom=geom,
        new_state=state,
    )
