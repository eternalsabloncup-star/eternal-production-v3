"""ERP V2 integration foundation (sandbox / read-only)."""

from app.integration.adapter import ErpV2ReadAdapter
from app.integration.errors import (
    IntegrationError,
    IntegrationForbidden,
    IntegrationNotFound,
    IntegrationUnauthorized,
    IntegrationUpstreamForbidden,
)
from app.integration.fixture_adapter import FixtureErpV2ReadAdapter
from app.integration.models import (
    AuthContext,
    CustomerRef,
    MeProfile,
    ProductRef,
    SalesOrderLineRef,
    SalesOrderRef,
)
from app.integration.receipts import InMemoryReadReceiptStore, ReadReceipt

__all__ = [
    "AuthContext",
    "CustomerRef",
    "ErpV2ReadAdapter",
    "FixtureErpV2ReadAdapter",
    "InMemoryReadReceiptStore",
    "IntegrationError",
    "IntegrationForbidden",
    "IntegrationNotFound",
    "IntegrationUnauthorized",
    "IntegrationUpstreamForbidden",
    "MeProfile",
    "ProductRef",
    "ReadReceipt",
    "SalesOrderLineRef",
    "SalesOrderRef",
]
