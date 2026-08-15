import json
import logging
from json import JSONDecodeError

from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import InventoryItem

logger = logging.getLogger(__name__)


@require_POST
def reserve_item(request, item_id: int) -> JsonResponse:
    """指定された数量を在庫から引き当て、更新者を記録する。"""
    try:
        payload = json.loads(request.body)
    except JSONDecodeError:
        return JsonResponse({"detail": "JSON本文が不正です。"}, status=400)

    quantity = payload.get("quantity")
    reserved_by = payload.get("reserved_by")
    if not isinstance(quantity, int) or quantity <= 0:
        return JsonResponse({"detail": "quantityは正の整数で指定してください。"}, status=400)
    if not isinstance(reserved_by, str) or not reserved_by:
        return JsonResponse({"detail": "reserved_byは必須です。"}, status=400)

    item = InventoryItem.objects.filter(pk=item_id).first()
    if item is None:
        return JsonResponse({"detail": "在庫が見つかりません。"}, status=404)
    if item.available_units < quantity:
        return JsonResponse({"detail": "在庫が不足しています。"}, status=409)

    item.available_units = F("available_units") - quantity
    item.save(update_fields=["available_units"])

    logger.info(
        "在庫引当を保存しました item_id=%s available_units_type=%s",
        item.pk,
        type(item.available_units).__name__,
    )

    item.last_reserved_by = reserved_by
    item.save()

    return JsonResponse({"id": item.pk, "status": "reserved"}, status=200)
