"""Explicit offline evidence for legacy integration tests; no test-skip approval."""

from fastapi import HTTPException


def mock_receipts(monkeypatch, receipts):
    class Gateway:
        async def get(self, path, **kwargs):
            row = receipts.get(path)
            if row is None:
                raise HTTPException(404, "Receipt absent from offline test corpus")
            return dict(row, source="fixture", live_verified=False, status="POSTED",
                        verifiable=True, cancelled=False, reversed=False)

    monkeypatch.setattr("app.services.accurate_evidence.ReadGateway", Gateway)
