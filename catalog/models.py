from django.db import models


class InventoryItem(models.Model):
    """引当可能な在庫と、その直近の更新者を保持する。"""

    sku = models.CharField(max_length=32, unique=True)
    available_units = models.PositiveIntegerField()
    last_reserved_by = models.CharField(max_length=64, blank=True)

    def __str__(self) -> str:
        return f"{self.sku}: {self.available_units}"
