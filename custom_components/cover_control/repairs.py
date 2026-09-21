"""The fix flow for the "covers without a controller" issue.

A repair flow cannot hand over to the cover subentry flow, and it has no
business guessing a window's orientation, so it does not try to add anything.
All it does is let you take covers off the list for good.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_IGNORED_COVERS, DOMAIN
from .discovery import cover_labels, uncontrolled_covers


class UncontrolledCoversFlow(RepairsFlow):
    """Offer to stop asking about covers the user does not want controlled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entries = self.hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self.async_abort(reason="no_config_entry")
        entry = entries[0]

        covers = uncontrolled_covers(self.hass, entry)
        labels = cover_labels(self.hass, covers)

        if user_input is not None:
            ignored = set(entry.options.get(CONF_IGNORED_COVERS) or ())
            ignored.update(user_input.get(CONF_IGNORED_COVERS) or ())
            # Updating the entry reloads it, which recomputes the issue: it
            # disappears if everything left is ignored, and comes back listing
            # the rest if it is not. Either way the issue tells the truth.
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_IGNORED_COVERS: sorted(ignored)},
            )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_IGNORED_COVERS, default=[]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=entity_id, label=labels[entity_id]
                                )
                                for entity_id in covers
                            ],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={
                "covers": "\n".join(f"- {labels[e]} (`{e}`)" for e in covers)
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Build the fix flow for one of our issues."""
    return UncontrolledCoversFlow()
