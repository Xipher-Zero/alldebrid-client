"""Slot-aware download dispatch coordinator."""
from __future__ import annotations


class DispatchCoordinator:
    def __init__(self, engine, control, ownership):
        self.engine = engine
        self.control = control
        self.ownership = ownership

    async def dispatch_queue(self, snapshot=None):
        return await self.control.coordinator.dispatch_queue(snapshot)

    async def advance_queue_locked(self, *args, **kwargs):
        return await self.control.coordinator.advance_queue_locked(*args, **kwargs)

    def schedule_ready_parent(self, *args, **kwargs):
        return self.control.coordinator.schedule_ready_parent(*args, **kwargs)
