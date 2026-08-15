import json

import pytest
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection

from catalog.models import InventoryItem


@pytest.mark.django_db(transaction=True)
def test_reservation_decrements_inventory_only_once_and_records_operator(caplog):
    """引当後に在庫が一度だけ減り、更新者が記録されることを期待する。"""
    item = InventoryItem.objects.create(
        sku="CHAIR-RED",
        available_units=10,
        last_reserved_by="",
    )

    client = Client()
    with CaptureQueriesContext(connection) as queries:
        response = client.post(
            f"/items/{item.pk}/reserve/",
            data=json.dumps({"quantity": 2, "reserved_by": "operator-42"}),
            content_type="application/json",
        )

    item.refresh_from_db()

    assert response.status_code == 200
    assert response.json() == {"id": item.pk, "status": "reserved"}
    assert item.available_units == 8
    assert item.last_reserved_by == "operator-42"
    assert any("available_units_type=CombinedExpression" in message for message in caplog.messages)
    assert sum('UPDATE "catalog_inventoryitem"' in query["sql"] for query in queries.captured_queries) == 2
