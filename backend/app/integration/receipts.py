"""In-memory read audit / sync receipts — no business tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

ReceiptResult = Literal[
    "ok",
    "not_found",
    "forbidden",
    "unauthorized",
    "upstream_forbidden",
]


@dataclass(frozen=True, slots=True)
class ReadReceipt:
    receipt_id: str
    direction: Literal["read"]
    operation: str
    external_ids: tuple[str, ...]
    auth_subject: str | None
    result: ReceiptResult
    recorded_at: datetime


@dataclass
class InMemoryReadReceiptStore:
    """Process-local receipt log for sandbox verification."""

    _items: list[ReadReceipt] = field(default_factory=list)

    def record(
        self,
        *,
        operation: str,
        external_ids: tuple[str, ...] = (),
        auth_subject: str | None,
        result: ReceiptResult,
    ) -> ReadReceipt:
        receipt = ReadReceipt(
            receipt_id=str(uuid4()),
            direction="read",
            operation=operation,
            external_ids=external_ids,
            auth_subject=auth_subject,
            result=result,
            recorded_at=datetime.now(UTC),
        )
        self._items.append(receipt)
        return receipt

    def all(self) -> tuple[ReadReceipt, ...]:
        return tuple(self._items)

    def clear(self) -> None:
        self._items.clear()
