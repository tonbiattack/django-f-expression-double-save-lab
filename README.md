# Djangoの`F()`式が二度保存されて在庫を二重減算する再現ラボ

このリポジトリは、Django 5.2系で在庫を引き当てるHTTP APIを題材にした、再現可能なデバッグ教材です。`F()`式で在庫を減算した後、同じモデルインスタンスを通常の`save()`で再保存すると、先の減算式が再びSQLへ送られます。その結果、HTTPは`200 OK`でも在庫が要求数量の二倍減ります。

| 項目 | 期待値 | 不具合時の実測値 | 修正後 |
| --- | ---: | ---: | ---: |
| 初期在庫 | 10 | 10 | 10 |
| 引当数量 | 2 | 2 | 2 |
| API応答 | `200 OK` | `200 OK` | `200 OK` |
| DB再読込後の在庫 | 8 | 6 | 8 |

## 対象と前提

この教材はPython 3.12.3、Django 5.2.17、pytest 9.1.1、pytest-django 4.14.0で検証しました。Django 6.0では、対応するデータベースで`F()`代入後の値を`save()`時に更新する仕様が追加されています。この教材は、当該仕様変更前のDjango 5.2系で、同一インスタンスを再保存するコードがどう壊れるかを扱います。

| コンポーネント | このラボでの役割 |
| --- | --- |
| `catalog/views.py` | 不具合を含む在庫引当APIと最小修正を置きます。 |
| `tests/test_reservation.py` | HTTP応答だけでなくDB再読込後の状態まで検証します。 |
| `scripts/observe_reservation.py` | HTTP応答、ログ、実行SQL、DB再読込結果を表示します。 |
| `docs/debugging-record.md` | 実測した証拠、仮説、根本原因、修正を記録します。 |

## セットアップ

次のコマンドで依存関係を導入します。仮想環境を使う場合は、任意の方法で有効化してから実行してください。

```bash
python -m pip install -r requirements.txt
```

修正済みの全テストは次で実行します。

```bash
python -m pytest -q
```

期待する結果は、2件のテストが成功することです。

```text
2 passed
```

## 不具合を再現する

不具合を露出するテストだけを追加したコミットは`85ba391`です。修正済みの`main`から次のように切り替えると、期待値`8`に対して実際値`6`で失敗します。

```bash
git checkout 85ba391
python -m pytest tests/test_reservation.py -q
```

失敗は構文エラーや設定不備ではありません。リクエストは正常に処理され、HTTP応答も`200`です。テストがDBから読み直した最終状態だけが、次のように契約を破っていることを示します。

```text
E       assert 6 == 8
```

修正済みの状態へ戻して回帰を確認します。

```bash
git switch main
python -m pytest -q
```

## 観測を再現する

次のスクリプトは、単一のHTTPリクエストについて、HTTP応答、アプリケーションログ、発行した`UPDATE`、DB再読込後の値を順に表示します。

```bash
python scripts/observe_reservation.py
```

修正前には`UPDATE`が2回出力され、どちらにも`available_units - 2`が含まれます。修正後は最初の`UPDATE`だけが式を使い、二度目は`refresh_from_db()`で読み戻した数値を保存します。詳細な実測値とデバッガーの確認手順は[調査記録](docs/debugging-record.md)を参照してください。

## 最小修正

根本原因は、`item.available_units = F("available_units") - quantity`が通常の整数代入ではなく、SQL式をモデル属性に保持することです。最初の`save()`の直後に、二度目の通常保存へ進む前に実値をDBから再読込します。

```python
item.available_units = F("available_units") - quantity
item.save(update_fields=["available_units"])
item.refresh_from_db(fields=["available_units"])

item.last_reserved_by = reserved_by
item.save()
```

この修正は`F()`式による原子的な減算を残しつつ、後続の`save()`に式を持ち越さないためのものです。再読込を省いて二度目だけ`update_fields=["last_reserved_by"]`とする回避もありますが、実務では後続の通常保存が追加された時点で再発します。このラボでは、再保存する前に属性の意味を実値へ戻すほうを採用しています。

## 参考資料

- [Django公式: Query Expressions](https://docs.djangoproject.com/en/6.0/ref/models/expressions/)
- [Django公式: Model instance reference](https://docs.djangoproject.com/en/6.0/ref/models/instances/)
