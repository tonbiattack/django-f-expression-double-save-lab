#!/usr/bin/env python3
"""Django管理コマンドのエントリーポイント。"""

import os
import sys


def main() -> None:
    """設定モジュールを指定してDjango管理コマンドを実行する。"""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "inventory_lab.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
