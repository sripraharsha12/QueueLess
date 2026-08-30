from dataclasses import dataclass
from typing import Optional


@dataclass
class Customer:
    id: Optional[int]
    name: str
    created_at: str


@dataclass
class Service:
    id: Optional[int]
    name: str
    average_service_minutes: int
    active: bool = True


@dataclass
class Counter:
    id: Optional[int]
    name: str
    status: str = "offline"


@dataclass
class QueueEntry:
    id: Optional[int]
    token: str
    customer_id: int
    service_id: int
    status: str
    counter_id: Optional[int]
    joined_at: str
    accepted_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class Notification:
    id: Optional[int]
    queue_entry_id: int
    message: str
    reminder_minutes: Optional[int]
    sent: bool
    created_at: str