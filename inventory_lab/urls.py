"""在庫APIのURL設定。"""

from django.urls import path

from catalog.views import reserve_item

urlpatterns = [
    path("items/<int:item_id>/reserve/", reserve_item, name="reserve-item"),
]
