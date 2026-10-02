"""Runtime: reads Home Assistant, runs the engine, moves the covers."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from astral import Observer
from astral.sun import zenith_and_azimuth
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_CLOSING,
    STATE_ON,
    STATE_OPENING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
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
    EVENTS_SAVE_DELAY,
    HOLDING_INTENTS,
    MANUAL_GROUP,
    MIN_MOVEMENT_DELTA,
    NOTIFY_WINDOW,
    PAUSE_FALLBACK,
    SETTLE_TIME,
    STORAGE_KEY,
    STORAGE_VERSION,
    SUBENTRY_TYPE_COVER,
    TICK_INTERVAL,
    Cause,
    Intent,
)
from .discovery import async_refresh_issue
from .engine import EpisodeState, Inputs, evaluate, released_from_pause
from .models import Decision, EffectiveConfig

_LOGGER = logging.getLogger(__name__)

#: Wind speeds are compared in km/h; anything else is converted first.
_WIND_TO_KMH = {"km/h": 1.0, "m/s": 3.6, "mph": 1.609344, "kn": 1.852}


def _is_travelling(state: State | None) -> bool:
    """Whether a cover state says the motor is running."""
    return state is not None and state.state in (STATE_OPENING, STATE_CLOSING)


@dataclass(frozen=True, slots=True)
class Command:
    """One service call to a cover, and what the cover must read back when done."""

    service: str
    field: str
    value: int
    #: Send it however small the correction is. Protecting the hardware is
    #: always worth a motor start; nothing else is.
    force: bool = False


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
        #: Whether something was holding this cover back at the last
        #: evaluation. None until the first one, which only sets the baseline.
        self.was_held: bool | None = None
        self.history: deque[Decision] = deque(maxlen=DECISION_HISTORY)
        self.decision: Decision | None = None
        self._contexts: dict[str, datetime] = {}
        self.expected_position: int | None = None
        self.last_command: datetime | None = None
        #: Commands still to send, the one the cover is working on, and when it
        #: went out. Only ever one is outstanding: a cover that is still
        #: travelling reads the next command as a new destination and abandons
        #: the run, so each command waits for the one before it to finish.
        self.queue: deque[Command] = deque()
        self.in_flight: Command | None = None
        self.sent_at: datetime | None = None
        #: The target the queue is working towards, so a decision that still
        #: wants the same thing does not restart it.
        self.queued_for: tuple[int | None, int | None] | None = None
        #: What happened to this cover today, in order. Kept on the runtime and
        #: published by an entity of its own, because the decision sensor
        #: writes on every evaluation and would copy the whole list each time.
        self.events: list[dict[str, Any]] = []
        #: When the cover was last moved by someone other than us, which is
        #: what the grouping of those movements is measured from.
        self.last_manual_at: datetime | None = None
        #: Called whenever the day's list changes, so it can be written to
        #: disk. The runtime knows nothing about where that is.
        self.on_events_changed: Callable[[], None] | None = None
        #: Where the cover was before the run it is reporting now, and when it
        #: last reported anything at all. A cover driven by hand reports its
        #: way through the run a percent or two at a time, so whether it has
        #: moved can only be asked of where the run started. Asked of the
        #: report before this one, the answer is always no.
        self.resting_position: int | None = None
        self.last_report_at: datetime | None = None

    def note_report(self, was: int | None, now: datetime) -> int | None:
        """Take in a position report and answer what it should be judged against.

        The reference only moves on once the cover has been still long enough
        for a run to be over. Everything inside a run is judged against the
        position that run started from.
        """
        if (
            self.resting_position is None
            or self.last_report_at is None
            or now - self.last_report_at >= SETTLE_TIME
        ):
            # Having none at all is not the same as having a stale one: the
            # first report after a restart carries no previous position, and
            # without this the run that follows it would have nothing to be
            # judged against and would pass for ours.
            self.resting_position = was
        self.last_report_at = now
        return self.resting_position

    def restore_events(self, events: list[Any], now: datetime) -> None:
        """Take back a list written before a restart.

        Only today's survives, judged here rather than trusted from the file,
        because a Home Assistant that was off overnight comes back to a file
        full of yesterday. Entries that cannot be read at all are dropped: a
        day's list is worth having, never worth failing a setup for.
        """
        self.events = [
            event
            for event in events
            if isinstance(event, dict)
            and dt_util.parse_datetime(str(event.get("at"))) is not None
        ]
        self.events = self.events_on(now)
        manual = [event for event in self.events if event["kind"] == "override"]
        # So a restart in the middle of someone adjusting a cover does not
        # split that one go at it into two entries.
        self.last_manual_at = (
            dt_util.parse_datetime(manual[-1]["at"]) if manual else None
        )

    def events_on(self, now: datetime) -> list[dict[str, Any]]:
        """The list as it stands on the day `now` falls in.

        Read through here rather than off `events` directly: the list is only
        trimmed when something is recorded, and a day where nothing has
        happened yet would otherwise go on showing yesterday under today's
        heading.
        """
        today = dt_util.as_local(now).date()
        return [
            event
            for event in self.events
            if dt_util.as_local(dt_util.parse_datetime(event["at"])).date() == today
        ]

    def record_event(self, kind: str, now: datetime, **detail: Any) -> None:
        """Note something worth seeing in the day's list.

        A movement is two commands, the slats and then the run, and reads as
        one thing: they are merged while the second still belongs to the first.
        """
        self.events = self.events_on(now)
        if kind == "move" and self.events:
            last = self.events[-1]
            since = now - dt_util.parse_datetime(last["at"])
            if last["kind"] == "move" and since < SETTLE_TIME:
                # Everything but the cause: the slats and the run are one
                # movement, and what caused it is what caused the first of them.
                last.update(
                    {
                        key: value
                        for key, value in detail.items()
                        if value is not None and key != "cause"
                    }
                )
                self._events_changed()
                return
        self.events.append({"at": now.isoformat(), "kind": kind, **detail})
        self._events_changed()

    def record_manual(self, position: int, now: datetime, handed_over: bool) -> None:
        """Note a movement nothing here made.

        A cover being driven by hand reports a position every step of the way,
        and a person adjusting a blind has two or three goes at it. One entry
        per report would bury the rest of the day, so anything within
        MANUAL_GROUP of the last one updates that entry instead: it keeps the
        time the fiddling started and carries where the cover ended up. The
        window runs from the last movement rather than the first, so a long
        session stays one entry as long as it never pauses for five minutes.
        """
        self.events = self.events_on(now)
        grouped = (
            self.events
            and self.events[-1]["kind"] == "override"
            and self.last_manual_at is not None
            and now - self.last_manual_at < MANUAL_GROUP
        )
        self.last_manual_at = now
        if grouped:
            self.events[-1]["position"] = position
            if handed_over:
                self.events[-1]["cause"] = str(Cause.HANDED_OVER)
            self._events_changed()
            return
        self.record_event(
            "override",
            now,
            position=position,
            cause=str(Cause.HANDED_OVER) if handed_over else None,
        )

    def _events_changed(self) -> None:
        if self.on_events_changed is not None:
            self.on_events_changed()

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

    @property
    def is_idle(self) -> bool:
        """Whether the cover has been sent everything the last decision wanted."""
        return not self.queue and self.in_flight is None

    def load_queue(
        self, commands: list[Command], destination: tuple[int | None, int | None]
    ) -> None:
        """Start on a new destination, dropping whatever was still pending."""
        self.queue = deque(commands)
        self.queued_for = destination

    def clear_queue(self) -> None:
        """Stop sending: the cover is not ours to move any more."""
        self.queue.clear()
        self.in_flight = None
        self.sent_at = None
        self.queued_for = None

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
        self._events_store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        #: What is waiting to be told, one line per cover, the latest winning.
        self._pending_notice: dict[str, str] = {}
        self._notify_unsub: Callable[[], None] | None = None

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
                runtime = CoverRuntime(subentry)
                runtime.on_events_changed = self._save_events
                self.runtimes[subentry.subentry_id] = runtime
        for stale in set(self.runtimes) - seen:
            del self.runtimes[stale]

    async def async_restore_events(self) -> None:
        """Put back what every cover did earlier today.

        Read before the first evaluation, so that whatever this session records
        lands after what the last one left behind rather than being replaced by
        it. A file that cannot be read costs the day's list and nothing else.
        """
        try:
            stored = await self._events_store.async_load() or {}
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not read the day's lists back: %s", err)
            return
        now = dt_util.utcnow()
        for subentry_id, events in (stored.get("covers") or {}).items():
            runtime = self.runtimes.get(subentry_id)
            if runtime is not None and isinstance(events, list):
                runtime.restore_events(events, now)

    @callback
    def _save_events(self) -> None:
        """Write the day's lists out, a little after they stop changing.

        Delayed because a cover being driven by hand changes its list every
        second it travels, and each of those is the same file.
        """
        self._events_store.async_delay_save(self._stored_events, EVENTS_SAVE_DELAY)

    @callback
    def _stored_events(self) -> dict[str, Any]:
        """Every cover's day, keyed by the subentry it belongs to.

        Built from the runtimes that exist now, so a cover that has been
        removed takes its list with it.
        """
        return {
            "covers": {
                subentry_id: runtime.events
                for subentry_id, runtime in self.runtimes.items()
                if runtime.events
            }
        }

    async def async_save_events_now(self) -> None:
        """Write the day's lists out at once, for an unload that cannot wait."""
        await self._events_store.async_save(self._stored_events())

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
        if self._notify_unsub is not None:
            self._notify_unsub()
            self._notify_unsub = None

    async def _handle_state_change(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        travelling = False
        for runtime in self.runtimes.values():
            if runtime.cover_entity != entity_id:
                continue
            self._detect_manual_move(runtime, event)
            travelling = travelling or _is_travelling(event.data.get("new_state"))
        if travelling:
            # A cover that is on its way reports every step it takes, and each
            # report would otherwise ask for another evaluation whose command
            # lands in the middle of the run and abandons it. The cover fires
            # another event when it comes to rest, which is when the next
            # command is actually due.
            return
        await self.async_request_refresh()

    @callback
    def _foreign_position(self, runtime: CoverRuntime, event: Event) -> int | None:
        """The position a movement nothing here made left the cover at.

        Context is the primary signal and is conclusive when it matches. It is
        not conclusive when it does *not* match: radio covers report their
        position back from the device itself, with a fresh context. So a
        non-matching context only counts once the cover has had time to finish
        travelling, and a report that agrees with where we sent it is ours
        however foreign the context looks.

        Until something has actually been commanded there is no such position
        to judge against, which is every cover's state after a restart and the
        whole life of one that was already where it needed to be. Where the
        cover was resting before this run began stands in for it then: leaving
        a position nothing here asked it to leave is the same signal.
        """
        new_state, old_state = event.data.get("new_state"), event.data.get("old_state")
        if new_state is None:
            return None
        position = new_state.attributes.get("current_position")
        if position is None:
            return None
        # Every report, ours or not, so that what counts as resting is judged
        # on how long the cover has been quiet rather than on who moved it.
        resting = runtime.note_report(
            None if old_state is None else old_state.attributes.get("current_position"),
            dt_util.utcnow(),
        )
        if runtime.is_ours(event.context):
            return None
        last = runtime.last_command
        if last is not None and dt_util.utcnow() - last < SETTLE_TIME:
            return None
        reference = runtime.expected_position
        if reference is None:
            reference = resting
        if reference is None:
            # The very first report after a restart: nothing to have moved
            # away from yet.
            return None
        if abs(position - reference) <= MIN_MOVEMENT_DELTA:
            return None
        return position

    @callback
    def _detect_manual_move(self, runtime: CoverRuntime, event: Event) -> None:
        """Note a movement by hand, and leave that cover alone until sunrise.

        Moving a cover by hand means "leave it there", so it pauses that cover
        exactly as the pause button does. It used to need a running episode to
        hand anything over, and lasted only as long as that episode: a cover
        closed by hand in the morning was opened again the moment the sun
        called for shading, and one closed during an episode was opened by the
        end of it, which is the opposite of what the hand asked for.
        """
        position = self._foreign_position(runtime, event)
        if position is None:
            return
        old_state = event.data.get("old_state")
        moved = (
            old_state is None
            or position != old_state.attributes.get("current_position")
        )
        # In dry run nothing we do is ever ours, so every movement looks like a
        # human. Recording them is right, but pausing is not: that would stop
        # the one thing a dry run is for, which is saying what it would do.
        taken = not runtime.dry_run
        if taken:
            _LOGGER.debug(
                "%s moved to %s%% by someone else (we last asked for %s); "
                "leaving it there until the next sunrise",
                runtime.cover_entity,
                position,
                runtime.expected_position,
            )
            runtime.state = replace(
                runtime.state, override=True, paused_until=self.next_sunrise()
            )
        if taken or moved:
            # A report that repeats the position the cover already had moved
            # nothing, and only belongs in the list when it is the report that
            # took the cover off the engine.
            runtime.record_manual(position, dt_util.utcnow(), taken)

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

    def _sun_track(self, now: datetime) -> tuple[tuple[datetime, float, float], ...]:
        """Where the sun will be from now until the end of the local day.

        One entry per evaluation interval, worked out once per tick and shared
        by every cover, because the sun is the same for all of them. The first
        entry is the present moment, which is what lets the plan start from
        where this evaluation is about to leave the cover.

        The day it covers is the local one, so the end of it is worked out in
        local time. The moments themselves are UTC, like every other time this
        integration hands around, so that comparing one against the clock is
        never a comparison between two ways of writing the same instant.
        """
        observer = Observer(
            self.hass.config.latitude,
            self.hass.config.longitude,
            self.hass.config.elevation,
        )
        local = dt_util.as_local(now)
        end = dt_util.start_of_local_day(local) + timedelta(days=1)
        track: list[tuple[datetime, float, float]] = []
        when = local
        while when < end:
            zenith, azimuth = zenith_and_azimuth(observer, when)
            track.append((dt_util.as_utc(when), 90.0 - zenith, azimuth))
            when += TICK_INTERVAL
        return tuple(track)

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
        self,
        runtime: CoverRuntime,
        config: EffectiveConfig,
        sun_track: tuple[tuple[datetime, float, float], ...] = (),
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
            is_moving=_is_travelling(cover),
            sun_elevation=sun.attributes.get("elevation") if sun else None,
            sun_azimuth=sun.attributes.get("azimuth") if sun else None,
            sun_track=sun_track,
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
        sun_track = self._sun_track(dt_util.utcnow())
        decisions: dict[str, Decision] = {}
        changes: list[tuple[CoverRuntime, Decision]] = []
        for runtime in self.runtimes.values():
            config = EffectiveConfig(self.hub_config, runtime.config)
            # Either level can force dry run; neither can cancel the other.
            runtime.dry_run = bool(self.hub_config.get(CONF_DRY_RUN)) or bool(
                runtime.config.get(CONF_DRY_RUN)
            )
            inputs = await self._build_inputs(runtime, config, sun_track)
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
        # Here rather than at setup, so a cover paired after startup is
        # noticed on the next tick instead of at the next restart.
        async_refresh_issue(self.hass, self.entry)
        return decisions

    @staticmethod
    def _is_change(runtime: CoverRuntime, decision: Decision) -> bool:
        """Record the decision and report whether it is worth notifying about.

        Two things are: the cover was moved, and what is holding it back
        changed. A reason code turning over while the cover stands still is
        not, and was most of the traffic: an episode ending on a cover that is
        already open moves nothing, and nor does one starting on a cover that
        is already where it needs to be.

        The first evaluation after startup only sets the baseline, or every
        restart would notify about every cover. A movement is the exception,
        because a movement at startup is still a movement.

        Dry run never sends a command, so target drift there stays silent; a
        storm or a takeover still reads as what it would do.
        """
        signature = decision.notify_signature
        if signature is None:
            return False
        runtime.last_signature = signature
        held, was_held = decision.intent in HOLDING_INTENTS, runtime.was_held
        runtime.was_held = held
        if decision.acted:
            # While a cover travels it keeps reporting positions short of the
            # target, so the same command is sent again; only a new target is
            # a new movement.
            destination = (decision.target_position, decision.target_tilt)
            if destination != runtime.last_notified_destination:
                runtime.last_notified_destination = destination
                return True
            return False
        return was_held is not None and held != was_held

    async def _async_notify(self, changes: list[tuple[CoverRuntime, Decision]]) -> None:
        """Hold a change back for a while, so that a sweep arrives as one message.

        Covers move a few minutes apart as the sun crosses them, and six
        notifications for one sweep of the house is five too many. Whatever
        has gathered in the window goes out together, one line per cover with
        the latest state of it, so a cover that moved twice is still one line.

        A storm does not wait: it is the one change that wants reading now.
        """
        if not self.hub_config.get(CONF_NOTIFY_TARGET) or not changes:
            return
        for runtime, decision in changes:
            self._pending_notice[runtime.subentry_id] = (
                f"{'[Dry run] ' if decision.dry_run else ''}{runtime.title}: "
                f"{decision.message}"
            )
        if any(decision.intent is Intent.STORM for _, decision in changes):
            await self._async_send_pending()
        elif self._notify_unsub is None:
            self._notify_unsub = async_call_later(
                self.hass, NOTIFY_WINDOW, self._async_send_pending
            )

    async def _async_send_pending(self, _now: datetime | None = None) -> None:
        """Send everything that has gathered, as one notification."""
        if self._notify_unsub is not None:
            self._notify_unsub()
            self._notify_unsub = None
        lines = list(self._pending_notice.values())
        self._pending_notice.clear()
        target = self.hub_config.get(CONF_NOTIFY_TARGET)
        if not target or not lines:
            return
        domain, _, service = str(target).partition(".")
        if not domain or not service:
            _LOGGER.warning("Notification target %r is not a service", target)
            return
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

    @staticmethod
    def _worth_moving(target: int | None, current: int | None) -> bool:
        """Whether a target sits far enough from the cover to be worth a motor start."""
        return target is not None and (
            current is None or abs(target - current) >= MIN_MOVEMENT_DELTA
        )

    @staticmethod
    def _reading(command: Command, inputs: Inputs) -> int | None:
        """What the cover currently reads back for the value a command sets."""
        return (
            inputs.current_position
            if command.field == "position"
            else inputs.current_tilt
        )

    def _steps_for(self, decision: Decision, inputs: Inputs) -> list[Command]:
        """The commands that carry out a decision, in the order they must be sent.

        Slats first, then the run.

        An actuator can be set up to put the slat angle back to whatever it was
        before a run. Setting the angle first makes that restore land on the
        angle we wanted, instead of on the one the cover happened to have.

        An actuator that does not restore is corrected on the next evaluation:
        the queue empties, the steps are worked out again from where the cover
        now is, and the angle is due. So the check after the run is there, it
        just does not need a step of its own.

        A cover going fully up carries no tilt, so it is a single run.
        """
        tilt = (
            Command("set_cover_tilt_position", "tilt_position", decision.target_tilt)
            if inputs.supports_tilt and decision.target_tilt is not None
            else None
        )
        drive = Command(
            "set_cover_position",
            "position",
            decision.target_position,
            force=decision.intent is Intent.STORM,
        )
        return [tilt, drive] if tilt is not None else [drive]

    def _is_due(self, command: Command, inputs: Inputs) -> bool:
        """Whether a command still needs sending, judged against the cover now."""
        if command.force:
            return True
        return self._worth_moving(command.value, self._reading(command, inputs))

    def _command_arrived(self, runtime: CoverRuntime, inputs: Inputs) -> bool:
        """Whether the cover reads back what the command in flight asked for."""
        command = runtime.in_flight
        if command is None:
            return True
        if inputs.is_moving:
            return False
        reached = self._reading(command, inputs)
        return reached is not None and abs(reached - command.value) <= MIN_MOVEMENT_DELTA

    async def _apply(
        self, runtime: CoverRuntime, decision: Decision, inputs: Inputs
    ) -> Decision:
        """Queue what a decision asks for and send the next command that is due.

        The queue outlives the decision that filled it. Opening a cover at the
        end of an episode takes two commands, and by the time the second one is
        due the episode is over and the decisions carry no target at all.
        """
        dry_run = runtime.dry_run
        now = dt_util.utcnow()

        if dry_run:
            # Everything above still ran, so the decision is the real one. Only
            # the commands are withheld, and nothing is queued or recorded,
            # because the cover is never asked to go anywhere.
            if decision.target_position is None:
                return replace(decision, dry_run=True)
            steps = self._steps_for(decision, inputs)
            if not any(self._is_due(step, inputs) for step in steps):
                return replace(
                    decision,
                    would_move=False,
                    acted=False,
                    dry_run=True,
                    message=f"{decision.message} Already within "
                    f"{MIN_MOVEMENT_DELTA}% of target, not moving.",
                )
            return replace(
                decision,
                would_move=True,
                acted=False,
                dry_run=True,
                message=f"{decision.message} No command sent.",
            )

        if decision.target_position is None and decision.blocked_by is not None:
            # Paused, overridden, a window opened: whatever is still queued was
            # decided under conditions that no longer hold.
            runtime.clear_queue()
            return replace(decision, dry_run=False)

        is_storm = decision.intent is Intent.STORM
        if is_storm and runtime.queued_for != (
            decision.target_position,
            decision.target_tilt,
        ):
            # Protecting the hardware does not wait its turn behind a shading
            # run, and cancelling that run is the point rather than the risk.
            runtime.clear_queue()

        if runtime.in_flight is not None:
            command = runtime.in_flight
            timed_out = (
                runtime.sent_at is not None and now - runtime.sent_at >= SETTLE_TIME
            )
            if self._command_arrived(runtime, inputs):
                runtime.in_flight = None
            elif timed_out:
                # Long enough that the cover is not going to carry it out.
                # Whatever was queued behind it was worked out from a position
                # the cover never reached, so the destination is re-decided
                # from where it actually is rather than continued blindly.
                _LOGGER.warning(
                    "%s did not reach %s %s within %s; starting over",
                    runtime.cover_entity,
                    command.field,
                    command.value,
                    SETTLE_TIME,
                )
                runtime.clear_queue()
            else:
                return replace(
                    decision,
                    would_move=True,
                    acted=False,
                    blocked_by="awaiting_travel",
                    message=f"{decision.message} Waiting for the cover to finish "
                    "the command before this one.",
                )

        if inputs.is_moving and not is_storm:
            # Someone else is driving it. Commanding it now would cancel their
            # run the same way a second command of ours would.
            return replace(
                decision,
                would_move=True,
                acted=False,
                blocked_by="awaiting_travel",
                message=f"{decision.message} Waiting for the cover to stop moving.",
            )

        # Only now that the cover is idle is what it still needs knowable: a
        # command that timed out leaves the cover short of where it was sent.
        if decision.target_position is not None:
            destination = (decision.target_position, decision.target_tilt)
            if destination != runtime.queued_for or runtime.is_idle:
                runtime.load_queue(self._steps_for(decision, inputs), destination)

        # Steps the cover no longer needs are dropped here rather than when
        # they were queued, which is the whole point of queueing them whole.
        command = None
        while runtime.queue:
            candidate = runtime.queue.popleft()
            if self._is_due(candidate, inputs):
                command = candidate
                break

        if command is None:
            if decision.target_position is None:
                return replace(decision, dry_run=False)
            return replace(
                decision,
                would_move=False,
                acted=False,
                dry_run=False,
                message=f"{decision.message} Already within "
                f"{MIN_MOVEMENT_DELTA}% of target, not moving.",
            )

        context = Context()
        runtime.remember_context(context)
        # The position the queue is driving towards, which is what a later
        # position report is judged against. The current decision may have no
        # target of its own by now.
        runtime.expected_position = (
            runtime.queued_for[0] if runtime.queued_for else None
        )
        runtime.last_command = now
        runtime.in_flight = command
        runtime.sent_at = now
        runtime.record_event(
            "move",
            now,
            cause=None if decision.cause is None else str(decision.cause),
            **(
                {
                    "position": command.value,
                    "up": command.value > (inputs.current_position or 0),
                }
                if command.field == "position"
                else {"tilt": command.value}
            ),
        )

        try:
            await self.hass.services.async_call(
                "cover",
                command.service,
                {ATTR_ENTITY_ID: runtime.cover_entity, command.field: command.value},
                blocking=False,
                context=context,
            )
        except (HomeAssistantError, vol.Invalid) as err:
            # One cover refusing a command must not take down the whole
            # integration, and the reason has to end up in the record.
            _LOGGER.warning(
                "Could not send %s %s to %s: %s",
                command.field,
                command.value,
                runtime.cover_entity,
                err,
            )
            runtime.clear_queue()
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
        runtime.record_event("paused", dt_util.utcnow())
        await self.async_request_refresh()

    async def async_pause_all(self) -> None:
        """Leave every cover alone until the next sunrise."""
        until = self.next_sunrise()
        now = dt_util.utcnow()
        for runtime in self.runtimes.values():
            runtime.state = replace(runtime.state, paused_until=until)
            runtime.record_event("paused", now)
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
        runtime.record_event("resumed", dt_util.utcnow())
        await self.async_request_refresh()

    async def async_resume_all(self) -> None:
        """Hand control back for every cover, however it was suspended."""
        now = dt_util.utcnow()
        for runtime in self.runtimes.values():
            runtime.state = self._resumed(runtime)
            runtime.record_event("resumed", now)
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
