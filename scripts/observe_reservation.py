"""在庫引当のHTTP応答、SQL、DB再読込結果を観測する補助スクリプト。"""

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "inventory_lab.settings")

import django


django.setup()

from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from catalog.models import InventoryItem


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

call_command("migrate", verbosity=0)
InventoryItem.objects.all().delete()
item = InventoryItem.objects.create(
    sku="CHAIR-RED",
    available_units=10,
    last_reserved_by="",
)

with CaptureQueriesContext(connection) as queries:
    response = Client().post(
        f"/items/{item.pk}/reserve/",
        data=json.dumps({"quantity": 2, "reserved_by": "operator-42"}),
        content_type="application/json",
    )

item.refresh_from_db()

print(f"HTTP status: {response.status_code}")
print(f"HTTP body: {response.json()}")
print(f"DB after reload: available_units={item.available_units}, last_reserved_by={item.last_reserved_by!r}")
print("Captured UPDATE statements:")
for query in queries.captured_queries:
    if 'UPDATE "catalog_inventoryitem"' in query["sql"]:
        print(query["sql"])
