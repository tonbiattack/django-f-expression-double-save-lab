# 調査記録: Djangoの`F()`式が二度保存され、在庫が二重減算される

## 事象の定義

在庫10個の商品に対して2個の引当を要求すると、APIは`200 OK`と`{"status": "reserved"}`を返します。しかし、トランザクション完了後にDBから在庫を読み直すと、期待値8ではなく6になります。HTTPの成功だけでは、最終的な永続状態が契約を守ったと判断できません。

| 観測境界 | 期待値 | 実測値（修正前） | 実測値（修正後） |
| --- | --- | --- | --- |
| HTTPステータス | `200` | `200` | `200` |
| レスポンスJSON | `{"id": 1, "status": "reserved"}` | 同じ | 同じ |
| DB再読込後の`available_units` | `8` | `6` | `8` |
| DB再読込後の`last_reserved_by` | `operator-42` | `operator-42` | `operator-42` |

再現環境はPython 3.12.3、Django 5.2.17、pytest 9.1.1、pytest-django 4.14.0、SQLiteです。`tests/test_reservation.py`はDjangoのテストクライアントで実際にHTTPリクエストを送り、応答を確認した後に`refresh_from_db()`で最終状態を検証します。

## 失敗テスト

次のコマンドを、再現テストを導入したコミット`85ba391`で実行しました。

```bash
python -m pytest tests/test_reservation.py -q
```

実測した失敗は次のとおりです。

```text
INFO     catalog.views:views.py:38 在庫引当を保存しました item_id=1 available_units_type=CombinedExpression
E       assert 6 == 8
```

この失敗は、テストの設定不備でもHTTPエラーでもありません。`available_units`だけが要求数量の二倍減っています。そのため、入力値、HTTP応答、アプリケーション内のモデル属性、発行SQL、DB再読込後の行を順に分離して観測しました。

## 仮説と検証

| 仮説 | 検証方法 | 結果 | 判断 |
| --- | --- | --- | --- |
| クライアントが同一リクエストを二重送信した | テスト内で`Client.post()`の呼び出し数を確認する | 呼び出しは1回 | 棄却 |
| APIはエラーを隠している | HTTPステータスとJSON本文を確認する | `200`かつ想定どおりの本文 | 棄却 |
| 引当処理が2回呼ばれている | `CaptureQueriesContext`で`UPDATE`文を確認する | `UPDATE`は2回、二度目も減算式を持つ | 採用 |
| `F()`式が一度目の保存で数値に戻る | ログとデバッガーで属性の値・型を確認する | `CombinedExpression`のまま残る | 採用 |

## コードリーディングで見つけた境界

修正前の処理では、最初の`save()`で在庫を原子的に減算し、同じモデルインスタンスに更新者を代入してから通常の`save()`を呼んでいました。

```python
item.available_units = F("available_units") - quantity
item.save(update_fields=["available_units"])

item.last_reserved_by = reserved_by
item.save()
```

`F("available_units") - quantity`は、Python上の整数を作る式ではありません。DjangoがDBへ送るSQL式を表すオブジェクトです。Django公式は、`F()`がDBレベルで操作するSQL式を生成すると説明しています。[1]

通常の`save()`は、`update_fields`を指定しないため、更新者だけでなくモデルが保持している`available_units`も保存対象にします。ここで属性が数値ではなく減算式のままであれば、同じ式が二度目の`UPDATE`へ含まれるはずです。

## ログ・SQL・DB再読込の実測

次の補助スクリプトを実行しました。

```bash
python scripts/observe_reservation.py
```

修正前に得た出力です。

```text
INFO catalog.views 在庫引当を保存しました item_id=1 available_units_type=CombinedExpression
HTTP status: 200
HTTP body: {'id': 1, 'status': 'reserved'}
DB after reload: available_units=6, last_reserved_by='operator-42'
Captured UPDATE statements:
UPDATE "catalog_inventoryitem" SET "available_units" = ("catalog_inventoryitem"."available_units" - 2) WHERE "catalog_inventoryitem"."id" = 1
UPDATE "catalog_inventoryitem" SET "sku" = 'CHAIR-RED', "available_units" = ("catalog_inventoryitem"."available_units" - 2), "last_reserved_by" = 'operator-42' WHERE "catalog_inventoryitem"."id" = 1
```

最初の`UPDATE`は10から2を引いて8にします。二度目の`UPDATE`にも同じ`available_units - 2`が含まれるため、DB上の8からさらに2を引いて6にします。HTTP応答の作成は二度目の保存後でも、レスポンス本文が在庫数を含まないため、API境界だけの検証では問題を検出できませんでした。

## デバッガーによる確認

一度目の`save()`の直後、二度目の保存の前で停止しました。実行したコマンドは次です。

```bash
python -m pdb \
  -c 'break /absolute/path/catalog/views.py:44' \
  -c continue \
  scripts/observe_reservation.py
```

停止位置で、モデル属性を評価しました。

```text
(Pdb) p item.available_units
<CombinedExpression: F(available_units) - Value(2)>
(Pdb) p type(item.available_units)
<class 'django.db.models.expressions.CombinedExpression'>
```

この観測により、DBが誤って二重更新したのではなく、同じPythonオブジェクトが先の減算式を保持したまま次の通常保存へ渡されたことを確認できました。

## 根本原因

根本原因は、Django 5.2系でモデルフィールドへ代入した`F()`式が、`save()`後にも同一モデルインスタンス上に残ることと、そのインスタンスを`update_fields`なしで再保存したことの組み合わせです。

Django 6.0の公式ドキュメントには、従来は`F()`オブジェクトが保存後にDBから更新されず、後続の保存ごとに評価・永続化され得たことが明記されています。Django 6.0では対応DBに限り、`save()`後に`F()`代入をDB値へ更新する仕様へ変わりました。[1] 本ラボはDjango 5.2.17を対象とするため、その新しい挙動を前提にできません。

## 最小修正

一度目の保存直後に、次の通常保存で使う`available_units`だけをDBから再読込します。

```python
item.available_units = F("available_units") - quantity
item.save(update_fields=["available_units"])
item.refresh_from_db(fields=["available_units"])

item.last_reserved_by = reserved_by
item.save()
```

`refresh_from_db()`はモデルのフィールドを現在のDB値で更新するメソッドです。[2] ここでは引当のSQL式を捨てて実値8へ戻すため、二度目の通常保存には減算式が残りません。`F()`式による原子的な減算は維持されます。

なお、二度目の保存を`item.save(update_fields=["last_reserved_by"])`に限定することも、この最小例では二重減算を避けます。ただし、その回避は後続の通常保存が追加された場合に再発しやすいものです。本件では、同じインスタンスを使い続ける前に式の属性を実値へ戻す修正を選びました。

修正後に同じ観測スクリプトを実行すると、最終状態は8となり、二度目のSQLには減算式ではなく読み戻した数値8が入ります。

```text
DB after reload: available_units=8, last_reserved_by='operator-42'
UPDATE "catalog_inventoryitem" SET "available_units" = ("catalog_inventoryitem"."available_units" - 2) WHERE "catalog_inventoryitem"."id" = 5
UPDATE "catalog_inventoryitem" SET "sku" = 'CHAIR-RED', "available_units" = 8, "last_reserved_by" = 'operator-42' WHERE "catalog_inventoryitem"."id" = 5
```

## 回帰確認

修正後は、最初に失敗した同じテストと、連続引当のテストを実行しました。

```bash
python -m pytest -q
```

実測結果は次のとおりです。

```text
2 passed in 0.37s
```

| テスト | 守る契約 |
| --- | --- |
| `test_reservation_decrements_inventory_only_once_and_records_operator` | 1回のHTTP引当で在庫が1回だけ減り、更新者も保存される。 |
| `test_follow_up_reservation_uses_the_reloaded_inventory_value` | 連続する引当で、各リクエストの数量だけが1回ずつ減る。 |

## 適用範囲と制約

このラボは、同一Djangoモデルインスタンスに`F()`式を代入し、保存後に通常の`save()`を行う経路を扱います。`QuerySet.update()`だけを使う一括更新、Django 6.0以降で対応DBの`RETURNING`を利用する保存、別インスタンスを取得して更新する経路は同じ条件ではありません。

また、`F()`式は競合更新による取りこぼしを避けるために有用です。[1] 本件の修正は`F()`をPythonの加減算へ置き換えるものではありません。保存後に残る式オブジェクトを認識し、後続の保存との境界を明示することが目的です。

## Git履歴

| コミット | 内容 |
| --- | --- |
| `e4bc672` | 不具合を含むDjango在庫引当APIの初期実装。 |
| `85ba391` | 期待値8に対して実際値6で失敗する再現テスト。 |
| `main`の修正済みコミット | `refresh_from_db()`、回帰テスト、README、観測スクリプト、調査記録。 |

## References

[1] [Django documentation — Query Expressions](https://docs.djangoproject.com/en/6.0/ref/models/expressions/)

[2] [Django documentation — Model instance reference: Refreshing objects from database](https://docs.djangoproject.com/en/6.0/ref/models/instances/#refreshing-objects-from-database)
