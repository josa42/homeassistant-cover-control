"""Finding covers that no controller has claimed yet.

The integration cannot set one up on its own: a cover needs the orientation of
its window, and nothing in Home Assistant knows which way a window faces. So
this only ever reports what is missing, and the repair issue it feeds points at
the normal "Add a cover" flow.
"""

from __future__ import annotations

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_COVER_ENTITY,
    CONF_IGNORED_COVERS,
    DOMAIN,
    ISSUE_UNCONTROLLED_COVERS,
    SUBENTRY_TYPE_COVER,
)

#: Covers in the API sense that are not windows. Suggesting the garage door
#: for solar shading is noise, and noise is what makes people ignore an issue
#: permanently. Anything else, including a cover with no device class at all,
#: stays a candidate.
SKIP_DEVICE_CLASSES = frozenset({"damper", "door", "garage", "gate"})


@callback
def configured_covers(entry: ConfigEntry) -> set[str]:
    """Every cover entity that already has a controller."""
    return {
        subentry.data[CONF_COVER_ENTITY]
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_COVER
    }


@callback
def uncontrolled_covers(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Covers that could be controlled but are not, ignoring the dismissed ones."""
    configured = configured_covers(entry)
    ignored = set(entry.options.get(CONF_IGNORED_COVERS) or ())
    registry = er.async_get(hass)

    found = []
    for entity_id in hass.states.async_entity_ids("cover"):
        if entity_id in configured or entity_id in ignored:
            continue
        # Disabled entities have no state at all, so only hidden ones need
        # filtering here. An entity missing from the registry is a YAML or
        # template cover, which is a perfectly good candidate.
        registered = registry.async_get(entity_id)
        if registered is not None and registered.hidden_by is not None:
            continue
        state = hass.states.get(entity_id)
        if state is None:
            continue
        if state.attributes.get("device_class") in SKIP_DEVICE_CLASSES:
            continue
        # Without a settable position the engine can only report
        # NO_POSITION_SUPPORT, and even storm protection has nothing to send.
        features = CoverEntityFeature(state.attributes.get("supported_features", 0))
        if not features & CoverEntityFeature.SET_POSITION:
            continue
        found.append(entity_id)
    return sorted(found)


@callback
def cover_labels(hass: HomeAssistant, entity_ids: list[str]) -> dict[str, str]:
    """Friendly names for the discovered covers, falling back to the entity id."""
    labels = {}
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        name = state.attributes.get("friendly_name") if state else None
        labels[entity_id] = name or entity_id
    return labels


@callback
def async_refresh_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Raise, update or clear the "covers without a controller" issue."""
    covers = uncontrolled_covers(hass, entry)
    if not covers:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_UNCONTROLLED_COVERS)
        return

    labels = cover_labels(hass, covers)
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_UNCONTROLLED_COVERS,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="uncontrolled_covers",
        translation_placeholders={
            "count": str(len(covers)),
            "covers": ", ".join(labels[entity_id] for entity_id in covers),
        },
    )
