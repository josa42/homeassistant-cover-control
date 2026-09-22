"""One combined notification per evaluation, and only for real changes."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import (
    CONF_COVER_ENTITY,
    CONF_DRY_RUN,
    CONF_NOTIFY_TARGET,
    DOMAIN,
)

from .conftest import COVER, COVER_DATA, HUB_DATA

SECOND = "cover.second"


@pytest.fixture
def notifications(service_calls_factory):
    return service_calls_factory("notify", "test_target")


@pytest.fixture
def notify_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "notify.test_target"}
    )
    return entry


@pytest.fixture
def two_cover_entry(hass: HomeAssistant) -> MockConfigEntry:
    mock = MockConfigEntry(
        domain=DOMAIN,
        title="Cover Control",
        data={**HUB_DATA, CONF_NOTIFY_TARGET: "notify.test_target"},
        subentries_data=[
            ConfigSubentryData(data=COVER_DATA, subentry_type="cover", title="Raffstore", unique_id=None),
            ConfigSubentryData(
                data={**COVER_DATA, CONF_COVER_ENTITY: SECOND},
                subentry_type="cover",
                title="Second",
                unique_id=None,
            ),
        ],
    )
    mock.add_to_hass(hass)
    return mock


def set_second_cover(hass: HomeAssistant, position: int = 100, tilt: int = 100) -> None:
    hass.states.async_set(
        SECOND,
        "open",
        {"current_position": position, "current_tilt_position": tilt, "supported_features": 255},
    )


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_startup_only_sets_a_baseline(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """Otherwise every restart notifies about every cover."""
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)
    assert notifications == []


async def test_a_real_change_sends_one_notification(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)

    set_scene(position=50, tilt=45, wind=55.0)  # storm outranks shading
    await refresh(hass, notify_entry)

    assert len(notifications) == 1
    assert notifications[0].data["title"] == "Cover Control"
    assert notifications[0].data["message"].startswith("Raffstore: Storm protection")


async def test_changes_on_several_covers_are_combined(
    hass: HomeAssistant, two_cover_entry, set_scene, setup_entry, notifications
) -> None:
    set_scene(position=50, tilt=45)
    set_second_cover(hass, 50, tilt=45)
    await setup_entry(two_cover_entry)
    assert notifications == []

    set_scene(position=50, tilt=45, wind=55.0)
    set_second_cover(hass, 50, tilt=45)
    await refresh(hass, two_cover_entry)

    assert len(notifications) == 1, "both covers must share one notification"
    lines = notifications[0].data["message"].splitlines()
    assert [line.split(":")[0] for line in lines] == ["Raffstore", "Second"]


async def test_moving_a_cover_notifies_even_within_the_same_intent(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """Tracking the sun far enough to move the cover is a real change."""
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)

    set_scene(position=50, tilt=45, sun_elevation=35.0)
    await refresh(hass, notify_entry)

    assert len(notifications) == 1
    assert notifications[0].data["message"].startswith("Raffstore: Shading to 35%")


async def test_resending_the_same_target_while_travelling_sends_nothing(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """A travelling cover still reports the old position, so the command repeats."""
    set_scene(position=100)
    await setup_entry(notify_entry)
    assert len(notifications) == 1

    await refresh(hass, notify_entry)  # cover still at 100, same target 50 again
    await refresh(hass, notify_entry)

    assert len(notifications) == 1


async def test_a_drift_too_small_to_move_sends_nothing(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """Below the motor-protection threshold nothing moves, so nothing changed."""
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)

    set_scene(position=50, tilt=45, sun_elevation=44.0)
    await refresh(hass, notify_entry)

    assert notifications == []


async def test_a_move_right_after_startup_notifies(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """The startup baseline suppresses unchanged states, not real movements."""
    set_scene(position=100)
    await setup_entry(notify_entry)

    assert len(notifications) == 1
    assert "Shading to 50%" in notifications[0].data["message"]


async def test_an_unchanged_tick_sends_nothing(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)
    await refresh(hass, notify_entry)
    await refresh(hass, notify_entry)
    assert notifications == []


async def test_target_drift_in_dry_run_sends_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, notifications
) -> None:
    """In dry run the cover never reaches the target, which drifts every tick.

    That combination used to send a notification on every evaluation.
    """
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "notify.test_target", CONF_DRY_RUN: True}
    )
    set_scene(position=50, tilt=45)
    await setup_entry(entry)
    first = hass.states.get("sensor.raffstore_decision").attributes["target_position"]

    set_scene(position=50, tilt=45, sun_elevation=35.0)  # the sun moved: a different target, same intent
    await refresh(hass, entry)
    second = hass.states.get("sensor.raffstore_decision").attributes["target_position"]

    assert first != second, "the scenario must actually move the target"
    assert notifications == []


async def test_a_cover_briefly_unavailable_sends_nothing(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """Reloads and restarts make covers blink unavailable; that is not a change."""
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)

    hass.states.async_set(COVER, "unavailable", {})
    await refresh(hass, notify_entry)
    set_scene(position=50, tilt=45)
    await refresh(hass, notify_entry)

    assert notifications == []


async def test_a_debounce_that_recovers_sends_nothing(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """A passing cloud holds the episode briefly; the episode never ended."""
    set_scene(position=50, tilt=45)
    await setup_entry(notify_entry)

    set_scene(position=50, tilt=45, pv="100")  # brightness drops, the episode starts debouncing
    await refresh(hass, notify_entry)
    assert hass.states.get("sensor.raffstore_decision").attributes["reason_code"] == "debouncing"
    set_scene(position=50, tilt=45)  # and recovers
    await refresh(hass, notify_entry)

    assert notifications == []


async def test_no_target_means_no_notifications(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, notifications
) -> None:
    set_scene(position=50, tilt=45)
    await setup_entry(entry)
    set_scene(position=50, tilt=45, wind=55.0)
    await refresh(hass, entry)
    assert notifications == []


async def test_dry_run_lines_are_marked(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, notifications
) -> None:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "notify.test_target", CONF_DRY_RUN: True}
    )
    set_scene(position=50, tilt=45)
    await setup_entry(entry)
    set_scene(position=50, tilt=45, wind=55.0)
    await refresh(hass, entry)

    assert len(notifications) == 1
    assert notifications[0].data["message"].startswith("[Dry run] Raffstore:")


async def test_a_broken_target_does_not_stop_control(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "notify.does_not_exist"}
    )
    set_scene(position=50, tilt=45)
    await setup_entry(entry)
    set_scene(position=50, tilt=45, wind=55.0)
    await refresh(hass, entry)

    assert cover_calls["position"][-1].data["position"] == 100
    assert hass.states.get("sensor.raffstore_decision").state == "storm"


async def test_a_malformed_target_is_reported_not_crashed(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, caplog
) -> None:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "not-a-service"}
    )
    set_scene(position=50, tilt=45)
    await setup_entry(entry)
    set_scene(position=50, tilt=45, wind=55.0)
    await refresh(hass, entry)

    assert "is not a service" in caplog.text
    assert hass.states.get("sensor.raffstore_decision").state == "storm"
