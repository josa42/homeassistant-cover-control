"""Discovery of covers that no controller has claimed yet."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cover_control.const import (
    CONF_IGNORED_COVERS,
    DOMAIN,
    ISSUE_UNCONTROLLED_COVERS,
)
from custom_components.cover_control.discovery import uncontrolled_covers
from custom_components.cover_control.repairs import async_create_fix_flow

# The controlled cover from conftest, plus a second one nobody has set up.
SPARE = "cover.kitchen_blind"

# Position control and tilt, which is what a shadeable cover reports.
FULL_FEATURES = 255


def add_cover(hass: HomeAssistant, entity_id: str = SPARE, **attributes) -> None:
    """Put a cover on the bus with the attributes discovery reads."""
    hass.states.async_set(
        entity_id,
        "open",
        {
            "friendly_name": "Kitchen blind",
            "current_position": 100,
            "supported_features": FULL_FEATURES,
            **attributes,
        },
    )


def issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_UNCONTROLLED_COVERS)


# --- what counts as a candidate ---------------------------------------------


async def test_a_cover_without_a_controller_is_found(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    add_cover(hass)
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == [SPARE]


async def test_a_controlled_cover_is_not_offered_again(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """The one cover in the fixture already has a subentry."""
    set_scene()
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == []


async def test_a_cover_that_cannot_be_positioned_is_skipped(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """Without SET_POSITION the engine could only report NO_POSITION_SUPPORT."""
    set_scene()
    add_cover(hass, supported_features=3)  # open and close only
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == []


@pytest.mark.parametrize("device_class", ["garage", "gate", "door", "damper"])
async def test_covers_that_are_not_windows_are_skipped(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    set_scene,
    setup_entry,
    device_class: str,
) -> None:
    set_scene()
    add_cover(hass, device_class=device_class)
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == []


@pytest.mark.parametrize("device_class", ["blind", "shutter", "awning", "curtain"])
async def test_window_device_classes_are_candidates(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    set_scene,
    setup_entry,
    device_class: str,
) -> None:
    set_scene()
    add_cover(hass, device_class=device_class)
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == [SPARE]


async def test_a_hidden_cover_is_skipped(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """Hidden entities still have a state, so the registry has to be consulted."""
    set_scene()
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "cover", "demo", "kitchen", suggested_object_id="kitchen_blind"
    )
    registry.async_update_entity(SPARE, hidden_by=er.RegistryEntryHider.USER)
    add_cover(hass)
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == []


async def test_an_ignored_cover_is_not_offered(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    add_cover(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_IGNORED_COVERS: [SPARE]}
    )
    await setup_entry(entry)

    assert uncontrolled_covers(hass, entry) == []


# --- the repair issue --------------------------------------------------------


async def test_the_issue_is_raised_and_names_the_covers(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    add_cover(hass)
    await setup_entry(entry)

    raised = issue(hass)
    assert raised is not None
    assert raised.translation_placeholders == {
        "count": "1",
        "covers": "Kitchen blind",
    }


async def test_no_issue_when_every_cover_is_controlled(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    await setup_entry(entry)

    assert issue(hass) is None


async def test_the_issue_clears_once_the_cover_is_ignored(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    add_cover(hass)
    await setup_entry(entry)
    assert issue(hass) is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_IGNORED_COVERS: [SPARE]}
    )
    await hass.async_block_till_done()

    assert issue(hass) is None


# --- the fix flow ------------------------------------------------------------


async def test_the_fix_flow_ignores_the_picked_covers(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    set_scene()
    add_cover(hass)
    await setup_entry(entry)

    flow = await async_create_fix_flow(hass, ISSUE_UNCONTROLLED_COVERS, None)
    flow.hass = hass
    form = await flow.async_step_init()
    assert form["step_id"] == "confirm"

    await flow.async_step_confirm({CONF_IGNORED_COVERS: [SPARE]})
    await hass.async_block_till_done()

    assert entry.options[CONF_IGNORED_COVERS] == [SPARE]
    assert issue(hass) is None


async def test_the_fix_flow_ignoring_nothing_leaves_the_issue_standing(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """Submitting an empty selection must not look like the covers went away."""
    set_scene()
    add_cover(hass)
    await setup_entry(entry)

    flow = await async_create_fix_flow(hass, ISSUE_UNCONTROLLED_COVERS, None)
    flow.hass = hass
    await flow.async_step_init()
    await flow.async_step_confirm({CONF_IGNORED_COVERS: []})
    await hass.async_block_till_done()

    assert uncontrolled_covers(hass, entry) == [SPARE]
    assert issue(hass) is not None


async def test_editing_hub_options_keeps_the_ignore_list(
    hass: HomeAssistant, entry: MockConfigEntry, set_scene, setup_entry
) -> None:
    """Options are replaced wholesale, and the list is not on that form."""
    set_scene()
    add_cover(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_IGNORED_COVERS: [SPARE]}
    )
    await setup_entry(entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {str(key): key for key in result["data_schema"].schema}
    assert CONF_IGNORED_COVERS not in fields, "not meant to be edited here"
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_hub_form(result),
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_IGNORED_COVERS] == [SPARE]
    assert uncontrolled_covers(hass, entry) == []


def _hub_form(result) -> dict:
    """The options form filled in with whatever it already defaults to."""
    filled = {}
    for key in result["data_schema"].schema:
        default = key.default() if callable(key.default) else key.default
        if default is not vol.UNDEFINED:
            filled[str(key)] = default
    return filled
