"""
Async Airtable client (mock implementation).

In production this would call the Airtable REST API v0.
The mock logs every record create/update so behaviour is observable in
tests and development without real credentials.

Usage:
    client = AirtableClient(base_id="appXXX", table_name="Invoices")
    record = await client.create_record({"Vendor": "Acme", "Amount": 1500.0})
    updated = await client.update_record(record.record_id, {"Status": "Approved"})
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AirtableRecord(BaseModel):
    """A single Airtable record returned by create or update operations."""

    record_id: str = Field(..., description="Airtable record ID (rec…)")
    table_name: str = Field(..., description="Table this record belongs to")
    fields: dict[str, object] = Field(..., description="Record field values")
    created_time: str = Field(..., description="ISO 8601 creation timestamp")


class AirtableClient:
    """
    Async Airtable integration client.

    Currently mocked — records are stored in-memory so tests can assert on
    create/update calls without real Airtable credentials.
    """

    def __init__(
        self,
        base_id: str = "",
        table_name: str = "Invoices",
        api_key: str = "",
    ) -> None:
        """
        Args:
            base_id: Airtable base identifier (e.g. appXXXXXXXXXXXXXX).
            table_name: Target table within the base.
            api_key: Airtable personal access token.
        """
        self._base_id = base_id
        self._table_name = table_name
        self._api_key = api_key
        self._records: dict[str, AirtableRecord] = {}

    @property
    def table_name(self) -> str:
        """Table this client is configured to write to."""
        return self._table_name

    @property
    def records(self) -> list[AirtableRecord]:
        """All records created or updated so far (for test assertions)."""
        return list(self._records.values())

    async def create_record(self, fields: dict[str, object]) -> AirtableRecord:
        """
        Create a new record in the configured Airtable table.

        Args:
            fields: Field name → value pairs to set on the new record.

        Returns:
            AirtableRecord with a generated record_id and creation timestamp.
        """
        record_id = f"rec{uuid4().hex[:14]}"
        record = AirtableRecord(
            record_id=record_id,
            table_name=self._table_name,
            fields=fields,
            created_time=datetime.now(UTC).isoformat(),
        )
        self._records[record_id] = record

        logger.info(
            "AirtableClient: record created",
            extra={
                "base_id": self._base_id,
                "table": self._table_name,
                "record_id": record_id,
                "field_count": len(fields),
            },
        )
        return record

    async def update_record(
        self,
        record_id: str,
        fields: dict[str, object],
    ) -> AirtableRecord:
        """
        Update fields on an existing record.

        Args:
            record_id: ID of the record to update.
            fields: Field name → value pairs to merge into the record.

        Returns:
            Updated AirtableRecord.

        Raises:
            KeyError: If *record_id* does not exist.
        """
        record = self._records.get(record_id)
        if record is None:
            raise KeyError(f"Airtable record '{record_id}' not found")

        updated_fields = {**record.fields, **fields}
        updated_record = AirtableRecord(
            record_id=record_id,
            table_name=self._table_name,
            fields=updated_fields,
            created_time=record.created_time,
        )
        self._records[record_id] = updated_record

        logger.info(
            "AirtableClient: record updated",
            extra={
                "base_id": self._base_id,
                "table": self._table_name,
                "record_id": record_id,
                "updated_fields": list(fields.keys()),
            },
        )
        return updated_record
