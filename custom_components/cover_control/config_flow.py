"""Config and subentry flows.

The hub entry holds the shared sensors and thresholds. One subentry per cover
holds that cover's geometry and may override any hub setting.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AZIMUTH,
    CONF_COOL_ABOVE,
    CONF_COVER_ENTITY,
    CONF_COVER_TYPE,
    CONF_DRY_RUN,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_HEAT_BELOW,
    CONF_INDOOR_COOL_ABOVE,
    CONF_INDOOR_HEAT_BELOW,
    CONF_INDOOR_TEMP,
    CONF_MAX_DEPTH,
    CONF_NOTIFY_TARGET,
    CONF_OUTDOOR_TEMP,
    CONF_PV_OVERRIDE,
    CONF_PV_POWER,
    CONF_PV_THRESHOLD,
    CONF_SEATING_POINT,
    CONF_SHADE_WINDOW_OPEN,
    CONF_SHADED_TILT,
    CONF_SILL_HEIGHT,
    CONF_STORM_ACTION,
    CONF_WEATHER,
    CONF_WEATHER_STATES,
    CONF_WIND_RELEASE,
    CONF_WIND_SOURCE,
    CONF_WIND_THRESHOLD,
    CONF_WINDOW_HEIGHT,
    CONF_WINDOW_SENSOR,
    DEFAULTS,
    DOMAIN,
    SUBENTRY_TYPE_COVER,
    CoverType,
    StormAction,
)

WEATHER_CONDITIONS = [
    "clear-night",
    "cloudy",
    "exceptional",
    "fog",
    "hail",
    "lightning",
    "lightning-rainy",
    "partlycloudy",
    "pouring",
    "rainy",
    "snowy",
    "snowy-rainy",
    "sunny",
    "windy",
    "windy-variant",
]


def _number(minimum: float, maximum: float, step: float, unit: str | None = None):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _notify_services(hass) -> list[str]:
    """Every notify service currently registered, as domain.service strings."""
    services = hass.services.async_services().get("notify", {})
    return [f"notify.{name}" for name in services]


def _hub_schema(
    defaults: dict[str, Any], notify_services: list[str] | None = None
) -> vol.Schema:
    def default(key: str):
        return defaults.get(key, DEFAULTS.get(key))

    return vol.Schema(
        {
            vol.Required(
                CONF_OUTDOOR_TEMP, default=default(CONF_OUTDOOR_TEMP)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "climate"])
            ),
            vol.Required(
                CONF_WEATHER, default=default(CONF_WEATHER)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
            vol.Optional(
                CONF_PV_POWER,
                description={"suggested_value": default(CONF_PV_POWER)},
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_WIND_SOURCE,
                description={"suggested_value": default(CONF_WIND_SOURCE)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "weather"])
            ),
            vol.Required(CONF_COOL_ABOVE, default=default(CONF_COOL_ABOVE)): _number(
                -20, 50, 0.5, "°C"
            ),
            vol.Required(CONF_HEAT_BELOW, default=default(CONF_HEAT_BELOW)): _number(
                -20, 50, 0.5, "°C"
            ),
            vol.Required(
                CONF_INDOOR_COOL_ABOVE, default=default(CONF_INDOOR_COOL_ABOVE)
            ): _number(0, 40, 0.5, "°C"),
            vol.Required(
                CONF_INDOOR_HEAT_BELOW, default=default(CONF_INDOOR_HEAT_BELOW)
            ): _number(0, 40, 0.5, "°C"),
            vol.Required(
                CONF_PV_THRESHOLD, default=default(CONF_PV_THRESHOLD)
            ): _number(0, 30000, 50, "W"),
            vol.Required(CONF_PV_OVERRIDE, default=default(CONF_PV_OVERRIDE)): _number(
                0, 30000, 50, "W"
            ),
            vol.Required(
                CONF_WEATHER_STATES, default=default(CONF_WEATHER_STATES)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=WEATHER_CONDITIONS,
                    translation_key="weather_condition",
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_WIND_THRESHOLD, default=default(CONF_WIND_THRESHOLD)
            ): _number(0, 200, 1, "km/h"),
            vol.Required(
                CONF_WIND_RELEASE, default=default(CONF_WIND_RELEASE)
            ): _number(0, 200, 1, "km/h"),
            vol.Optional(
                CONF_NOTIFY_TARGET,
                description={"suggested_value": default(CONF_NOTIFY_TARGET)},
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=sorted(notify_services or []),
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_DRY_RUN, default=bool(default(CONF_DRY_RUN))
            ): selector.BooleanSelector(),
        }
    )


class CoverControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the hub config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single hub entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Cover Control", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_hub_schema({}, _notify_services(self.hass)),
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_COVER: CoverSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CoverControlOptionsFlow()


class CoverControlOptionsFlow(OptionsFlow):
    """Edit the hub defaults."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_hub_schema(current))


class CoverSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one controlled cover."""

    def __init__(self) -> None:
        self._cover_entity: str | None = None
        self._existing: dict[str, Any] = {}

    def _supports_tilt(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        features = CoverEntityFeature(state.attributes.get("supported_features", 0))
        return bool(features & CoverEntityFeature.SET_TILT_POSITION)

    def _suggest_type(self, entity_id: str) -> str:
        """A cover with tilt is almost always a Raffstore; without, a Rolladen.

        Only a suggestion: the user confirms it in the next step.
        """
        if self._supports_tilt(entity_id):
            return CoverType.RAFFSTORE
        return CoverType.ROLLADEN

    def _default_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state is None:
            return entity_id
        return state.attributes.get("friendly_name") or entity_id

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the cover entity to control."""
        if user_input is not None:
            self._cover_entity = user_input[CONF_COVER_ENTITY]
            return await self.async_step_configure()

        configured = {
            subentry.data[CONF_COVER_ENTITY]
            for subentry in self._get_entry().subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_COVER
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COVER_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="cover", exclude_entities=sorted(configured)
                        )
                    )
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing cover."""
        subentry = self._get_reconfigure_subentry()
        self._existing = dict(subentry.data)
        self._cover_entity = self._existing[CONF_COVER_ENTITY]
        return await self.async_step_configure(user_input)

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Geometry, cover type and the optional per-cover overrides."""
        assert self._cover_entity is not None
        entity_id = self._cover_entity

        if user_input is not None:
            data = {CONF_COVER_ENTITY: entity_id, **user_input}
            title = data.pop("name", None) or self._default_name(entity_id)
            if self._existing:
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    data=data,
                    title=title,
                )
            return self.async_create_entry(title=title, data=data)

        existing = self._existing
        supports_tilt = self._supports_tilt(entity_id)

        def suggest(key: str, fallback: Any = None):
            return {"suggested_value": existing.get(key, fallback)}

        fields: dict[Any, Any] = {
            vol.Required(
                "name", description=suggest("name", self._default_name(entity_id))
            ): selector.TextSelector(),
            vol.Required(
                CONF_COVER_TYPE,
                default=(
                    existing.get(CONF_COVER_TYPE) or self._suggest_type(entity_id)
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[t.value for t in CoverType],
                    translation_key="cover_type",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_AZIMUTH, default=existing.get(CONF_AZIMUTH, 180)
            ): _number(0, 359, 1, "°"),
            vol.Required(
                CONF_WINDOW_HEIGHT, default=existing.get(CONF_WINDOW_HEIGHT, 1.5)
            ): _number(0.1, 10, 0.05, "m"),
            vol.Required(
                CONF_SILL_HEIGHT, default=existing.get(CONF_SILL_HEIGHT, 0.0)
            ): _number(0, 5, 0.05, "m"),
            vol.Required(
                CONF_MAX_DEPTH, default=existing.get(CONF_MAX_DEPTH, 0.0)
            ): _number(0, 10, 0.1, "m"),
            vol.Required(
                CONF_FOV_LEFT, default=existing.get(CONF_FOV_LEFT, 90)
            ): _number(0, 90, 1, "°"),
            vol.Required(
                CONF_FOV_RIGHT, default=existing.get(CONF_FOV_RIGHT, 90)
            ): _number(0, 90, 1, "°"),
            vol.Required(
                CONF_STORM_ACTION,
                default=existing.get(CONF_STORM_ACTION, StormAction.IGNORE),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[a.value for a in StormAction],
                    translation_key="storm_action",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(
                CONF_INDOOR_TEMP, description=suggest(CONF_INDOOR_TEMP)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "climate"])
            ),
            vol.Optional(
                CONF_WINDOW_SENSOR, description=suggest(CONF_WINDOW_SENSOR)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Required(
                CONF_SHADE_WINDOW_OPEN,
                default=existing.get(CONF_SHADE_WINDOW_OPEN, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SEATING_POINT, description=suggest(CONF_SEATING_POINT)
            ): _number(0, 90, 1, "%"),
            vol.Required(
                CONF_DRY_RUN, default=bool(existing.get(CONF_DRY_RUN, False))
            ): selector.BooleanSelector(),
        }
        if supports_tilt:
            fields[
                vol.Required(
                    CONF_SHADED_TILT, default=existing.get(CONF_SHADED_TILT, 45)
                )
            ] = _number(0, 100, 1, "%")

        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(fields),
            description_placeholders={"cover": self._default_name(entity_id)},
        )
