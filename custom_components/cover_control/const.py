"""Constants for the Cover Control integration."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

DOMAIN = "cover_control"

SUBENTRY_TYPE_COVER = "cover"

EVENT_DECISION = f"{DOMAIN}_decision"

#: Repair issue raised when covers exist that no controller has claimed.
ISSUE_UNCONTROLLED_COVERS = "uncontrolled_covers"

#: How often every cover is re-evaluated even if nothing changed.
TICK_INTERVAL = timedelta(minutes=5)

#: A gate must stay false this long before it is allowed to end an episode.
#: Protects against short dips (a cloud, or the PV inverter curtailing when
#: the battery is full) flinging the covers open on a sunny afternoon.
GATE_DEBOUNCE = timedelta(minutes=10)

#: How long PV power must stay above the weather override threshold before
#: it is believed over the weather condition. Long enough that a bright gap
#: in an overcast sky does not count as a sunny afternoon.
PV_OVERRIDE_SUSTAIN = timedelta(minutes=20)

#: Smaller target changes than this are not sent to the motor.
MIN_MOVEMENT_DELTA = 5

#: How long a cover is assumed to need to finish a run. Two things hang off
#: it: position reports inside the window are treated as the cover travelling
#: rather than as a human at the wall switch, and an identical command is not
#: sent again until the window has passed, which caps how fast a cover that
#: never reaches its target can be re-commanded.
SETTLE_TIME = timedelta(seconds=90)

#: How long a context id we created stays recognisable as ours.
CONTEXT_TTL = timedelta(minutes=5)

#: Number of decisions kept per cover for the diagnostics download.
DECISION_HISTORY = 50

#: Where a pause ends when the sun's next rising is unknown. Only reached if
#: ``sun.sun`` is missing or has no ``next_rising``, which normally cannot
#: happen, so a whole day off is the safer guess than a few minutes.
PAUSE_FALLBACK = timedelta(hours=12)


class CoverType(StrEnum):
    """Physical type of the cover, which fixes the motor/glass mapping."""

    RAFFSTORE = "raffstore"
    ROLLADEN = "rolladen"
    OTHER = "other"


class Facade(StrEnum):
    """Which side of the house a window is on.

    Stored rather than the compass bearing, so that a house discovered to be
    turned a few degrees off the grid is corrected in one place instead of
    once per window.
    """

    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"


#: Degrees to add to the orientation of the house to face each side. South is
#: the reference because that is the side the orientation names.
FACADE_OFFSET: dict[Facade, float] = {
    Facade.SOUTH: 0.0,
    Facade.WEST: 90.0,
    Facade.NORTH: 180.0,
    Facade.EAST: 270.0,
}


class StormAction(StrEnum):
    """What a storm should do to a particular cover."""

    RETRACT_UP = "retract_up"
    CLOSE_DOWN = "close_down"
    IGNORE = "ignore"


class Intent(StrEnum):
    """The state machine's intent, highest priority first."""

    STORM = "storm"
    WINDOW_OPEN = "window_open"
    PAUSED = "paused"
    OVERRIDE = "override"
    COOLING = "cooling"
    HEATING = "heating"
    NEUTRAL = "neutral"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class Reason(StrEnum):
    """Stable machine-readable reason codes.

    The human sentence is built from these plus the decision's numbers, so
    automations can match on the code and never on translated prose.
    """

    MASTER_DISABLED = "master_disabled"
    COVER_DISABLED = "cover_disabled"
    COVER_UNAVAILABLE = "cover_unavailable"
    STORM_WIND = "storm_wind"
    WINDOW_IS_OPEN = "window_is_open"
    PAUSED = "paused"
    MANUAL_OVERRIDE = "manual_override"
    SUN_NOT_ON_WINDOW = "sun_not_on_window"
    NOT_BRIGHT = "not_bright"
    TEMP_NEUTRAL = "temp_neutral"
    SHADING = "shading"
    SOLAR_HEATING = "solar_heating"
    EPISODE_ENDED = "episode_ended"
    DEBOUNCING = "debouncing"
    NO_POSITION_SUPPORT = "no_position_support"
    SUN_UNAVAILABLE = "sun_unavailable"


#: Glass-travel defaults per cover type. ``seating_point`` is the position at
#: which the cover has fully covered the glass; travel below it only closes the
#: light gaps between the slats and buys no extra shading.
DEFAULT_SEATING_POINT: dict[CoverType, int] = {
    CoverType.RAFFSTORE: 0,
    CoverType.ROLLADEN: 25,
    CoverType.OTHER: 0,
}

# --- Hub configuration keys -------------------------------------------------

CONF_OUTDOOR_TEMP = "outdoor_temp_entity"
CONF_WEATHER = "weather_entity"
CONF_PV_POWER = "pv_power_entity"
CONF_WIND_SOURCE = "wind_source_entity"
CONF_COOL_ABOVE = "cool_above"
CONF_HEAT_BELOW = "heat_below"
CONF_INDOOR_COOL_ABOVE = "indoor_cool_above"
CONF_INDOOR_HEAT_BELOW = "indoor_heat_below"
CONF_TEMP_HYSTERESIS = "temp_hysteresis"
CONF_SHADING_STEP = "shading_step"
CONF_PV_THRESHOLD = "pv_threshold"
CONF_PV_OVERRIDE = "pv_override_threshold"
CONF_WEATHER_STATES = "allowed_weather_states"
CONF_WIND_THRESHOLD = "wind_threshold"
CONF_WIND_RELEASE = "wind_release"
CONF_NOTIFY_TARGET = "notify_target"
CONF_HOUSE_ORIENTATION = "house_orientation"
#: Covers the user has told the discovery issue to stop asking about.
CONF_IGNORED_COVERS = "ignored_covers"
CONF_DRY_RUN = "dry_run"

# --- Cover configuration keys ----------------------------------------------

CONF_COVER_ENTITY = "cover_entity"
CONF_COVER_TYPE = "cover_type"
CONF_AZIMUTH = "azimuth"
CONF_FACADE = "facade"
CONF_WINDOW_HEIGHT = "window_height"
CONF_SILL_HEIGHT = "sill_height"
CONF_FOV_LEFT = "fov_left"
CONF_FOV_RIGHT = "fov_right"
CONF_MAX_DEPTH = "max_penetration_depth"
CONF_SEATING_POINT = "seating_point"
CONF_SHADED_TILT = "shaded_tilt"
CONF_INDOOR_TEMP = "indoor_temp_entity"
CONF_WINDOW_SENSOR = "window_sensor_entity"
CONF_SHADE_WINDOW_OPEN = "shade_with_window_open"
CONF_STORM_ACTION = "storm_action"

#: Dry run is deliberately NOT here: hub and cover values are OR-ed, so a
#: master safe-mode cannot be cancelled by a per-cover checkbox.
#: Hub settings a cover may override. Anything listed here is resolved through
#: :meth:`EffectiveConfig.resolve`, which also records where the value came from.
OVERRIDABLE = (
    CONF_OUTDOOR_TEMP,
    CONF_WEATHER,
    CONF_PV_POWER,
    CONF_WIND_SOURCE,
    CONF_COOL_ABOVE,
    CONF_HEAT_BELOW,
    CONF_INDOOR_COOL_ABOVE,
    CONF_INDOOR_HEAT_BELOW,
    CONF_TEMP_HYSTERESIS,
    CONF_SHADING_STEP,
    CONF_PV_THRESHOLD,
    CONF_PV_OVERRIDE,
    CONF_WEATHER_STATES,
    CONF_WIND_THRESHOLD,
    CONF_WIND_RELEASE,
)

DEFAULTS: dict[str, object] = {
    CONF_COOL_ABOVE: 25.0,
    CONF_HEAT_BELOW: 12.0,
    CONF_INDOOR_COOL_ABOVE: 23.0,
    CONF_INDOOR_HEAT_BELOW: 21.0,
    # Half a degree is more than a sensor's noise and less than a change
    # anybody feels, which is the whole job of this number.
    CONF_TEMP_HYSTERESIS: 0.5,
    # A quarter of the glass per step. Fewer and larger movements, at the
    # cost of up to one step more covering than the depth rule asks for.
    CONF_SHADING_STEP: 25.0,
    CONF_PV_THRESHOLD: 800.0,
    CONF_PV_OVERRIDE: 2500.0,
    CONF_WEATHER_STATES: ["sunny", "partlycloudy"],
    CONF_WIND_THRESHOLD: 40.0,
    CONF_WIND_RELEASE: 30.0,
    CONF_DRY_RUN: False,
    # The bearing of the side of the house called south. 180 is a house
    # squared to the compass, which is the only guess worth making.
    CONF_HOUSE_ORIENTATION: 180.0,
}

COVER_DEFAULTS: dict[str, object] = {
    CONF_FOV_LEFT: 90.0,
    CONF_FOV_RIGHT: 90.0,
    CONF_MAX_DEPTH: 0.0,
    CONF_SILL_HEIGHT: 0.0,
    CONF_FACADE: Facade.SOUTH,
    CONF_SHADED_TILT: 45,
    CONF_SHADE_WINDOW_OPEN: False,
    CONF_STORM_ACTION: StormAction.IGNORE,
    CONF_COVER_TYPE: CoverType.OTHER,
}
