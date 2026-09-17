"""Runtime: reads Home Assistant, runs the engine, moves the covers."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import replace
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DRY_RUN,
    CONF_INDOOR_TEMP,
    CONF_NOTIFY_TARGET,
    CONF_OUTDOOR_TEMP,
    CONF_PV_POWER,
    CONF_WEATHER,
    CONF_WIND_SOURCE,
    CONF_WINDOW_SENSOR,
    CONTEXT_TTL,
    DECISION_HISTORY,
    DOMAIN,
    EVENT_DECISION,
    MIN_MOVEMENT_DELTA,
    PAUSE_FALLBACK,
    SETTLE_TIME,
    SUBENTRY_TYPE_COVER,
    TICK_INTERVAL,
    Intent,
)
from .engine import EpisodeState, Inputs, evaluate, released_from_pause
from .models import Decision, EffectiveConfig

_LOGGER = logging.getLogger(__name__)

#: Wind speeds are compared in km/h; anything else is converted first.
_WIND_TO_KMH = {"km/h": 1.0, "m/s": 3.6, "mph": 1.609344, "kn": 1.852}


class CoverRuntime:
    """Per-cover runtime state that must survive between evaluations."""

    def __init__(self, subentry: ConfigSubentry) -> None:
        self.subentry_id = subentry.subentry_id
        self.title = subentry.title
        self.config: dict[str, Any] = dict(subentry.data)
        self.cover_entity: str = self.config["cover_entity"]
        self.state = EpisodeState()
        self.enabled = True
        self.dry_run = False
        self.last_signature: tuple | None = None
        self.last_notified_destination: tuple | None = None
        self.history: deque[Decision] = deque(maxlen=DECISION_HISTORY)
        self.decision: Decision | None = None
        self._contexts: dict[str, datetime] = {}
        self.expected_position: int | None = None
        self.last_command: datetime | None = None

    @property
    def is_paused(self) -> bool:
        """Whether a pause is still running.

        The engine clears an expired deadline on its next evaluation, so the
        clock is what decides here, not the field being set.
        """
        until = self.state.paused_until
        return until is not None and dt_util.utcnow() < until

    @property
    def is_suspended(self) -> bool:
        """Whether anything at all is holding this cover back from control."""
        return self.is_paused or self.state.override

    def remember_context(self, context: Context) -> None:
        """Record a context we created so its state changes are known as ours."""
        now = dt_util.utcnow()
        self._contexts[context.id] = now
        cutoff = now - CONTEXT_TTL
        self._contexts = {k: v for k, v in self._contexts.items() if v > cutoff}

    def is_ours(self, context: Context) -> bool:
        return context.id in self._contexts or (
            context.parent_id is not None and context.parent_id in self._contexts
        )


class CoverControlCoordinator(DataUpdateCoordinator[dict[str, Decision]]):
    """Evaluates every configured cover on a tick and on relevant state changes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=TICK_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self.hub_device_id: str | None = None
        self.master_enabled = True
        self.runtimes: dict[str, CoverRuntime] = {}
        self._unsub_tracker = None
        self._forecast_cache: dict[str, tuple[datetime, float | None]] = {}

    @property
    def hub_config(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    # --- wiring -------------------------------------------------------------

    def load_subentries(self) -> None:
        """Sync runtimes with the entry's cover subentries."""
        seen: set[str] = set()
        for subentry in self.entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_COVER:
                continue
            seen.add(subentry.subentry_id)
            if subentry.subentry_id in self.runtimes:
                self.runtimes[subentry.subentry_id].config = dict(subentry.data)
            else:
                self.runtimes[subentry.subentry_id] = CoverRuntime(subentry)
        for stale in set(self.runtimes) - seen:
            del self.runtimes[stale]

    @callback
    def async_setup_listeners(self) -> None:
        """Re-evaluate whenever anything the engine reads changes."""
        if self._unsub_tracker is not None:
            self._unsub_tracker()
        entities = {"sun.sun"}
        hub = self.hub_config
        for key in (CONF_OUTDOOR_TEMP, CONF_WEATHER, CONF_PV_POWER, CONF_WIND_SOURCE):
            if hub.get(key):
                entities.add(hub[key])
        for runtime in self.runtimes.values():
            entities.add(runtime.cover_entity)
            for key in (
                CONF_INDOOR_TEMP,
                CONF_WINDOW_SENSOR,
                CONF_OUTDOOR_TEMP,
                CONF_WEATHER,
                CONF_PV_POWER,
                CONF_WIND_SOURCE,
            ):
                if runtime.config.get(key):
                    entities.add(runtime.config[key])
        self._unsub_tracker = async_track_state_change_event(
            self.hass, sorted(entities), self._handle_state_change
        )

    @callback
    def async_stop_listeners(self) -> None:
        """Drop the state tracker so unloading leaves nothing behind."""
        if self._unsub_tracker is not None:
            self._unsub_tracker()
            self._unsub_tracker = None

    async def _handle_state_change(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        for runtime in self.runtimes.values():
            if runtime.cover_entity == entity_id:
                self._detect_manual_move(runtime, event)
        await self.async_request_refresh()

    @callback
    def _detect_manual_move(self, runtime: CoverRuntime, event: Event) -> None:
        """Decide whether a cover movement came from a human.

        Context is the primary signal and is conclusive when it matches. It is
        not conclusive when it does *not* match: radio covers report their
        position back from the device itself, with a fresh context. So a
        non-matching context is only treated as manual once the cover has had
        time to finish travelling and the reported position still disagrees
        with what we asked for.
        """
        if not runtime.state.active or runtime.state.override:
            return
        if runtime.dry_run:
            # In dry run nothing we do is ever ours, so every movement would
            # look like a human and latch an override on the first tick, which
            # is exactly the state that stops reporting what it would do.
            return
        if runtime.is_ours(event.context):
            return
        now = dt_util.utcnow()
        last = runtime.last_command
        if last is not None and now - last < SETTLE_TIME:
            return
        new_state = event.data.get("new_state")
        if new_state is None or runtime.expected_position is None:
            return
        position = new_state.attributes.get("current_position")
        if position is None:
            return
        if abs(position - runtime.expected_position) <= MIN_MOVEMENT_DELTA:
            return
        _LOGGER.debug(
            "%s moved to %s%% by someone else (we asked for %s%%); "
            "handing control over until this episode ends",
            runtime.cover_entity,
            position,
            runtime.expected_position,
        )
        runtime.state = replace(runtime.state, override=True)

    # --- reading Home Assistant --------------------------------------------

    def _float_state(self, entity_id: str | None) -> float | None:
        """Read a numeric state, accepting a climate entity's current temperature."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if entity_id.startswith("climate."):
            value = state.attributes.get("current_temperature")
            return float(value) if value is not None else None
        try:
            return float(state.state)
        except TypeError, ValueError:
            return None

    def _wind_kmh(self, config: EffectiveConfig) -> float | None:
        """Wind speed in km/h from a dedicated sensor or the weather entity."""
        source = config.get(CONF_WIND_SOURCE)
        if source and not source.startswith("weather."):
            return self._float_state(source)
        weather_entity = source or config.get(CONF_WEATHER)
        if not weather_entity:
            return None
        state = self.hass.states.get(weather_entity)
        if state is None:
            return None
        speed = state.attributes.get("wind_speed")
        if speed is None:
            return None
        unit = state.attributes.get("wind_speed_unit", "km/h")
        try:
            return float(speed) * _WIND_TO_KMH.get(unit, 1.0)
        except TypeError, ValueError:
            return None

    async def _forecast_max(self, weather_entity: str | None) -> float | None:
        """Today's forecast high, cached for one tick.

        This is what lets shading act before the room is already hot; without
        it the integration can only react once the heat is inside.
        """
        if not weather_entity:
            return None
        now = dt_util.utcnow()
        cached = self._forecast_cache.get(weather_entity)
        if cached and now - cached[0] < TICK_INTERVAL:
            return cached[1]
        value: float | None = None
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": "daily"},
                target={ATTR_ENTITY_ID: weather_entity},
                blocking=True,
                return_response=True,
            )
        except Exception as err:
            _LOGGER.debug("Could not fetch forecast from %s: %s", weather_entity, err)
        else:
            forecasts = (response or {}).get(weather_entity, {}).get("forecast") or []
            if forecasts:
                raw = forecasts[0].get("temperature")
                value = float(raw) if raw is not None else None
        self._forecast_cache[weather_entity] = (now, value)
        return value

    async def _build_inputs(
        self, runtime: CoverRuntime, config: EffectiveConfig
    ) -> Inputs:
        cover = self.hass.states.get(runtime.cover_entity)
        available = cover is not None and cover.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        features = (
            CoverEntityFeature(cover.attributes.get("supported_features", 0))
            if cover
            else CoverEntityFeature(0)
        )
        sun = self.hass.states.get("sun.sun")

        window_entity = runtime.config.get(CONF_WINDOW_SENSOR)
        window_open: bool | None = None
        if window_entity:
            window_state = self.hass.states.get(window_entity)
            if window_state is not None and window_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                window_open = window_state.state == STATE_ON

        weather_entity = config.get(CONF_WEATHER)
        weather_state = self.hass.states.get(weather_entity) if weather_entity else None

        return Inputs(
            now=dt_util.utcnow(),
            cover_available=available,
            supports_position=bool(features & CoverEntityFeature.SET_POSITION),
            supports_tilt=bool(features & CoverEntityFeature.SET_TILT_POSITION),
            current_position=(
                cover.attributes.get("current_position") if cover else None
            ),
            current_tilt=(
                cover.attributes.get("current_tilt_position") if cover else None
            ),
            sun_elevation=sun.attributes.get("elevation") if sun else None,
            sun_azimuth=sun.attributes.get("azimuth") if sun else None,
            outdoor_temp=self._float_state(config.get(CONF_OUTDOOR_TEMP)),
            forecast_max=await self._forecast_max(weather_entity),
            indoor_temp=self._float_state(runtime.config.get(CONF_INDOOR_TEMP)),
            pv_power=self._float_state(config.get(CONF_PV_POWER)),
            weather=weather_state.state if weather_state else None,
            wind_speed=self._wind_kmh(config),
            window_open=window_open,
        )

    # --- the tick -----------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Decision]:
        self.load_subentries()
        decisions: dict[str, Decision] = {}
        changes: list[tuple[CoverRuntime, Decision]] = []
        for runtime in self.runtimes.values():
            config = EffectiveConfig(self.hub_config, runtime.config)
            # Either level can force dry run; neither can cancel the other.
            runtime.dry_run = bool(self.hub_config.get(CONF_DRY_RUN)) or bool(
                runtime.config.get(CONF_DRY_RUN)
            )
            inputs = await self._build_inputs(runtime, config)
            decision, state = evaluate(
                inputs,
                config,
                runtime.state,
                runtime.cover_entity,
                self.master_enabled,
                runtime.enabled,
            )
            runtime.state = state
            decision = await self._apply(runtime, decision, inputs)
            runtime.decision = decision
            runtime.history.append(decision)
            decisions[runtime.subentry_id] = decision
            self.hass.bus.async_fire(EVENT_DECISION, decision.as_dict())
            _LOGGER.debug(
                "%s:%s %s",
                runtime.cover_entity,
                " [dry run]" if decision.dry_run else "",
                decision.message,
            )
            if self._is_change(runtime, decision):
                changes.append((runtime, decision))
        # One notification for the whole evaluation, however many covers changed.
        await self._async_notify(changes)
        return decisions

    @staticmethod
    def _is_change(runtime: CoverRuntime, decision: Decision) -> bool:
        """Record the decision and report whether it is worth notifying about.

        A cover actually being moved always is. Otherwise only a changed intent
        or reason counts, and the first evaluation after startup just sets the
        baseline, or every restart would notify about every cover.

        Dry run never sends a command, so target drift there stays silent.
        """
        signature = decision.notify_signature
        if signature is None:
            return False
        previous = runtime.last_signature
        runtime.last_signature = signature
        if decision.acted:
            # While a cover travels it keeps reporting positions short of the
            # target, so the same command is sent again; only a new target is
            # a new movement.
            destination = (decision.target_position, decision.target_tilt)
            if destination != runtime.last_notified_destination:
                runtime.last_notified_destination = destination
                return True
        return previous is not None and previous != signature

    async def _async_notify(self, changes: list[tuple[CoverRuntime, Decision]]) -> None:
        """Send a single notification describing every cover that changed."""
        target = self.hub_config.get(CONF_NOTIFY_TARGET)
        if not target or not changes:
            return
        domain, _, service = str(target).partition(".")
        if not domain or not service:
            _LOGGER.warning("Notification target %r is not a service", target)
            return

        lines = [
            f"{'[Dry run] ' if decision.dry_run else ''}{runtime.title}: "
            f"{decision.message}"
            for runtime, decision in changes
        ]
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {"title": "Cover Control", "message": "\n".join(lines)},
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            # A broken notify target must never stop covers from being managed.
            _LOGGER.warning("Could not notify %s: %s", target, err)

    async def _apply(
        self, runtime: CoverRuntime, decision: Decision, inputs: Inputs
    ) -> Decision:
        """Send the commands a decision asks for, if they are worth sending."""
        dry_run = runtime.dry_run
        if decision.target_position is None:
            return replace(decision, dry_run=dry_run)

        target = decision.target_position
        current = inputs.current_position
        is_storm = decision.intent is Intent.STORM
        # Small corrections are not worth a motor start, but protection always is.
        if (
            not is_storm
            and current is not None
            and abs(target - current) < MIN_MOVEMENT_DELTA
        ):
            return replace(
                decision,
                would_move=False,
                acted=False,
                dry_run=dry_run,
                message=f"{decision.message} Already within "
                f"{MIN_MOVEMENT_DELTA}% of target, not moving.",
            )

        if dry_run:
            # Everything above still ran, so the decision is the real one. Only
            # the command is withheld, and no expected position is recorded
            # because the cover was never asked to go anywhere.
            return replace(
                decision,
                would_move=True,
                acted=False,
                dry_run=True,
                message=f"{decision.message} No command sent.",
            )

        context = Context()
        runtime.remember_context(context)
        runtime.expected_position = target
        runtime.last_command = dt_util.utcnow()

        try:
            await self.hass.services.async_call(
                "cover",
                "set_cover_position",
                {ATTR_ENTITY_ID: runtime.cover_entity, "position": target},
                blocking=False,
                context=context,
            )
            if decision.target_tilt is not None and inputs.supports_tilt:
                await self.hass.services.async_call(
                    "cover",
                    "set_cover_tilt_position",
                    {
                        ATTR_ENTITY_ID: runtime.cover_entity,
                        "tilt_position": decision.target_tilt,
                    },
                    blocking=False,
                    context=context,
                )
        except (HomeAssistantError, vol.Invalid) as err:
            # One cover refusing a command must not take down the whole
            # integration, and the reason has to end up in the record.
            _LOGGER.warning(
                "Could not move %s to %s%%: %s", runtime.cover_entity, target, err
            )
            runtime.expected_position = None
            return replace(
                decision,
                would_move=True,
                acted=False,
                blocked_by="command_failed",
                message=f"{decision.message} The command failed: {err}",
            )
        return replace(decision, would_move=True, acted=True)

    # --- commands from the entities ----------------------------------------

    def next_sunrise(self) -> datetime:
        """When a pause started now should end.

        ``sun.sun`` always reports the *next* rising, so pausing at noon runs
        to tomorrow morning and pausing at midnight runs to the same morning,
        which is what "not today" means in both cases.
        """
        sun = self.hass.states.get("sun.sun")
        raw = sun.attributes.get("next_rising") if sun else None
        parsed = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
        if parsed is None:
            _LOGGER.warning(
                "sun.sun reports no next_rising; pausing for %s instead",
                PAUSE_FALLBACK,
            )
            return dt_util.utcnow() + PAUSE_FALLBACK
        return dt_util.as_utc(parsed)

    async def async_pause(self, subentry_id: str) -> None:
        """Leave one cover alone until the next sunrise."""
        runtime = self.runtimes.get(subentry_id)
        if runtime is None:
            return
        runtime.state = replace(runtime.state, paused_until=self.next_sunrise())
        await self.async_request_refresh()

    async def async_pause_all(self) -> None:
        """Leave every cover alone until the next sunrise."""
        until = self.next_sunrise()
        for runtime in self.runtimes.values():
            runtime.state = replace(runtime.state, paused_until=until)
        await self.async_request_refresh()

    async def async_set_paused_until(
        self, subentry_id: str, until: datetime | None
    ) -> None:
        """Set a pause deadline directly, for restoring one across a restart."""
        runtime = self.runtimes.get(subentry_id)
        if runtime is None:
            return
        runtime.state = replace(runtime.state, paused_until=until)
        await self.async_request_refresh()

    @staticmethod
    def _resumed(runtime: CoverRuntime) -> EpisodeState:
        """The state after pressing resume.

        Resuming a pause starts fresh, exactly like a pause running out, so a
        resume pressed in the evening cannot revive the afternoon's episode
        and open the cover. Resuming only a manual override keeps the episode:
        it is current, and resuming it is the point.
        """
        if runtime.state.paused_until is not None:
            return released_from_pause(runtime.state)
        return replace(runtime.state, override=False)

    async def async_resume(self, subentry_id: str) -> None:
        """Hand control back for one cover, however it was suspended."""
        runtime = self.runtimes.get(subentry_id)
        if runtime is None:
            return
        runtime.state = self._resumed(runtime)
        await self.async_request_refresh()

    async def async_resume_all(self) -> None:
        """Hand control back for every cover, however it was suspended."""
        for runtime in self.runtimes.values():
            runtime.state = self._resumed(runtime)
        await self.async_request_refresh()

    async def async_set_master(self, enabled: bool) -> None:
        self.master_enabled = enabled
        await self.async_request_refresh()

    async def async_set_cover_enabled(self, subentry_id: str, enabled: bool) -> None:
        runtime = self.runtimes.get(subentry_id)
        if runtime is None:
            return
        runtime.enabled = enabled
        await self.async_request_refresh()
