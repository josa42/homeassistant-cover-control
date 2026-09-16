"""Shared entity base classes."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CoverControlCoordinator, CoverRuntime


class HubEntity(CoordinatorEntity[CoverControlCoordinator]):
    """An entity on the central Cover Control device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CoverControlCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Cover Control",
            model="Controller",
            entry_type=DeviceEntryType.SERVICE,
        )


class ControlledCoverEntity(CoordinatorEntity[CoverControlCoordinator]):
    """An entity on one controlled cover's device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime, key: str
    ) -> None:
        super().__init__(coordinator)
        self._subentry_id = runtime.subentry_id
        self._attr_unique_id = f"{runtime.subentry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.subentry_id)},
            name=runtime.title,
            manufacturer="Cover Control",
            model="Controlled cover",
            via_device_id=coordinator.hub_device_id,
        )

    @property
    def runtime(self) -> CoverRuntime | None:
        """The runtime this entity belongs to, if it still exists."""
        return self.coordinator.runtimes.get(self._subentry_id)
