"""Notifications go out on changes, and never on every tick."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import (
    CONF_DRY_RUN,
    CONF_NOTIFY_TARGET,
    DOMAIN,
)


@pytest.fixture
def notifications(hass: HomeAssistant, service_calls_factory):
    return service_calls_factory("notify", "test_target")


@pytest.fixture
def notify_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "notify.test_target"}
    )
    return entry


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_a_change_sends_one_notification(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    set_scene()
    await setup_entry(notify_entry)

    assert len(notifications) == 1
    data = notifications[0].data
    assert "Raffstore" in data["title"]
    assert "Shading to 50%" in data["message"]


async def test_an_unchanged_tick_sends_nothing(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    """The target drifts a percent at a time; that must not be a notification."""
    set_scene()
    await setup_entry(notify_entry)
    assert len(notifications) == 1

    await refresh(hass, notify_entry)
    await refresh(hass, notify_entry)

    assert len(notifications) == 1, "repeat evaluations must stay quiet"


async def test_a_new_intent_notifies_again(
    hass: HomeAssistant, notify_entry, set_scene, setup_entry, notifications
) -> None:
    set_scene()
    await setup_entry(notify_entry)
    assert len(notifications) == 1

    set_scene(wind=55.0)  # storm outranks shading
    await refresh(hass, notify_entry)

    assert len(notifications) == 2
    assert "Storm protection" in notifications[-1].data["message"]


async def test_no_target_means_no_notifications(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, notifications
) -> None:
    set_scene()
    await setup_entry(entry)
    assert notifications == []


async def test_dry_run_notifications_are_marked(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, notifications
) -> None:
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_NOTIFY_TARGET: "notify.test_target", CONF_DRY_RUN: True},
    )
    set_scene()
    await setup_entry(entry)

    assert len(notifications) == 1
    assert notifications[0].data["message"].startswith("[Dry run]")


async def test_a_broken_target_does_not_stop_control(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """A typo in the notify service must not take the covers down with it."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "notify.does_not_exist"}
    )
    set_scene()
    await setup_entry(entry)

    assert cover_calls["position"][-1].data["position"] == 50
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"


async def test_a_malformed_target_is_reported_not_crashed(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, caplog
) -> None:
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_NOTIFY_TARGET: "not-a-service"}
    )
    set_scene()
    await setup_entry(entry)

    assert entry.domain == DOMAIN
    assert "is not a service" in caplog.text
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"
