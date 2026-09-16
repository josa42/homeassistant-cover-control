"""Dry run reports what would happen without touching a cover."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import CONF_DRY_RUN, SETTLE_TIME

from .conftest import COVER


def runtime(entry: MockConfigEntry):
    return next(iter(entry.runtime_data.runtimes.values()))


async def test_dry_run_does_not_move_the_cover(
    hass: HomeAssistant, dry_run_entry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene()
    await setup_entry(dry_run_entry)

    assert not cover_calls["position"], "dry run must not command the cover"
    assert not cover_calls["tilt"]


async def test_dry_run_still_reports_what_it_would_do(
    hass: HomeAssistant, dry_run_entry, set_scene, setup_entry
) -> None:
    """The whole point: the decision is real, only the command is withheld."""
    set_scene()
    await setup_entry(dry_run_entry)

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "cooling"
    assert decision.attributes["reason_code"] == "shading"
    assert decision.attributes["target_position"] == 50
    assert decision.attributes["target_tilt"] == 45
    assert decision.attributes["would_move"] is True
    assert decision.attributes["acted"] is False
    assert decision.attributes["dry_run"] is True
    assert "No command sent" in decision.attributes["message"]
    # The label belongs to the notification, not to the message itself.
    assert "Dry run" not in decision.attributes["message"]


async def test_dry_run_records_no_expected_position(
    hass: HomeAssistant, dry_run_entry, set_scene, setup_entry
) -> None:
    """Nothing was commanded, so there is nothing to compare a movement against."""
    set_scene()
    await setup_entry(dry_run_entry)

    assert runtime(dry_run_entry).expected_position is None
    assert runtime(dry_run_entry).last_command is None


async def test_dry_run_never_latches_a_manual_override(
    hass: HomeAssistant, dry_run_entry, set_scene, setup_entry, freezer
) -> None:
    """Every movement is foreign in dry run, and an override would hide the output.

    Without the guard the first movement by anything else would latch an
    override, and the decision sensor would report 'override' from then on
    instead of what the integration would have done.
    """
    set_scene()
    await setup_entry(dry_run_entry)
    assert runtime(dry_run_entry).state.active

    freezer.tick(SETTLE_TIME + timedelta(seconds=10))
    hass.states.async_set(
        COVER,
        "open",
        {
            "current_position": 20,
            "current_tilt_position": 100,
            "supported_features": 255,
        },
        context=Context(),
    )
    await hass.async_block_till_done()

    assert not runtime(dry_run_entry).state.override
    assert hass.states.get("sensor.raffstore_decision").state == "cooling"


async def test_hub_dry_run_cannot_be_cancelled_per_cover(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    """Hub and cover are OR-ed, so a master safe mode always wins."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DRY_RUN: True}
    )
    subentry = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_DRY_RUN: False}
    )
    set_scene()
    await setup_entry(entry)

    assert not cover_calls["position"]
    assert hass.states.get("sensor.raffstore_decision").attributes["dry_run"] is True


async def test_dry_run_withholds_storm_protection_too(
    hass: HomeAssistant, dry_run_entry, set_scene, setup_entry, cover_calls
) -> None:
    """Dry run means dry run, including the one case that protects hardware.

    Storm outranks everything in the engine, but dry run is applied after the
    decision, so nothing moves. That is the honest reading of "do not touch my
    covers", and the alternative is a safe mode that surprises you by moving
    them. Worth knowing before leaving a real Raffstore in dry run.
    """
    set_scene(wind=55.0)
    await setup_entry(dry_run_entry)

    decision = hass.states.get("sensor.raffstore_decision")
    assert decision.state == "storm"
    assert decision.attributes["would_move"] is True
    assert decision.attributes["acted"] is False
    assert not cover_calls["position"], "dry run withholds even a storm retract"


async def test_normal_mode_still_moves_the_cover(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry, cover_calls
) -> None:
    set_scene()
    await setup_entry(entry)

    assert cover_calls["position"][-1].data["position"] == 50
    decision = hass.states.get("sensor.raffstore_decision").attributes
    assert decision["acted"] is True
    assert decision["dry_run"] is False
