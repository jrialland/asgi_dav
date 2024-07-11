from dataclasses import dataclass
import logging
import uuid

from typing import Callable, Awaitable, Literal


# ------------------------------------------------------------------------------
@dataclass
class Event:
    path: str


# ------------------------------------------------------------------------------
@dataclass
class FileUploadedEvent(Event):
    pass


# ------------------------------------------------------------------------------
@dataclass
class FileCopiedEvent(Event):
    dest_path: str


# ------------------------------------------------------------------------------
@dataclass
class FileDownloadedEvent(Event):
    pass


# ------------------------------------------------------------------------------
@dataclass
class FileDeletedEvent(Event):
    pass


# ------------------------------------------------------------------------------
@dataclass
class FileMovedEvent(Event):
    dest_path: str


# ------------------------------------------------------------------------------
@dataclass
class FileCopiedEvent(Event):
    dest_path: str


# ------------------------------------------------------------------------------
@dataclass
class DirectoryCreatedEvent(Event):
    pass


# ------------------------------------------------------------------------------
@dataclass
class DirectoryDeletedEvent(Event):
    pass


# ------------------------------------------------------------------------------
@dataclass
class DirectoryMovedEvent(Event):
    dest_path: str


# ------------------------------------------------------------------------------
@dataclass
class DirectoryCopiedEvent(Event):
    dest_path: str


# ------------------------------------------------------------------------------
callback_t = Callable[..., Awaitable[None]]

# ------------------------------------------------------------------------------
eventname_t = Literal[
    "directory.copied",
    "file.copied",
    "directory.moved",
    "file.moved",
    "file.uploaded",
    "directory.deleted",
    "file.deleted",
    "directory.created",
    "file.downloaded",
]


# ------------------------------------------------------------------------------
class EventSupport:

    def __init__(self):
        self.events: dict[eventname_t, set[str]] = {}
        self.subscriptions: dict[str, callback_t] = {}

    def on(self, event: eventname_t, callback: callback_t) -> str:
        subscription_id = str(uuid.uuid4())
        self.subscriptions[subscription_id] = callback

        subs = self.events.get(event, None)
        if not subs:
            subs = set()
        subs.add(subscription_id)
        return subscription_id

    def unsubscribe(self, subscription_id: str):
        self.subscriptions.pop(subscription_id)
        for subs in self.events.values():
            if subscription_id in subs:
                subs.remove(subscription_id)

    async def emit(self, event: eventname_t, *args, **kwargs):
        for subscription_id in self.events.get(event, []):
            try:
                await self.subscriptions[subscription_id](*args, **kwargs)
            except Exception as e:
                logging.exception(event)
