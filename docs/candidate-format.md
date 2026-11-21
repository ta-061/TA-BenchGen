# 候補JSONの形式

`ta-bench generate --candidate` は、ソースの変更、不備のラベル、比較に使う入力列を記述したJSONを読み込みます。モデルが返す候補も同じ形式です。実行器が観測値と合否を記録します。[同梱の候補例](../examples/)

## ソースの変更

トップレベルに `defects`、`tests` と、`changes` または `files` のいずれかを指定します。変更対象は正常対照の `ta/` 以下にある既存のCソースとヘッダ（`.c`、`.h`）です。

| フィールド | 記述内容 |
| --- | --- |
| `changes` | 各要素にファイルの相対パス `path`、不備ID `defect`、置換前の `old` と置換後の `new` を記述します。`old` は元ファイル内で一意に一致する行を指定します。 |
| `files` | ファイルの相対パスをキー、変更後の全文を値とするオブジェクトです。各不備の `edits` で、その不備に対応する編集IDを指定します。 |

編集ID（`E1`、`E2`、…）は正常対照と不備TAの行差分から決まります。各編集は一つの不備に属します。別々の不備の変更が一つの編集にまとまらないよう、間に元の行を残します。

## 不備のラベル

`defects` の各要素には `id`、`class`、`reason`、`detector_targets`、`witness_test_ids` を指定します。`class` は分類の登録名、`witness_test_ids` はその不備を調べる入力列のIDです。[分類の登録](../config/classes.yaml)

`detector_targets` の各要素には `path`、`function`、`lines`、`role` を指定します。`lines` は不備TA上の開始行と終了行を並べた配列です。影響操作を `effect` として1か所、対応する保護操作が経路上に残る場合は `protection` も1か所指定します。操作を表す最小の行範囲を使います。[保存後のケースの読み方](../benchmark/README.md)

## 入力列

`tests` の各要素には `id`、`purpose`、`targets`、`steps` を指定します。

| `purpose` | 対象と比較箇所 |
| --- | --- |
| `normal` | 通常入力。`targets` は空配列とし、入力列全体の挙動を比較します。 |
| `witness` | 指定した不備に対応する入力。`targets` に不備IDを列挙し、`witness_step` で差を調べる `invoke` の位置を指定します（1始まり）。 |

`steps` はセッションを開く `open`、コマンドを呼ぶ `invoke`、セッションを閉じる `close` の列です。各 `invoke` にセッション名、`command_id`、4個の `params` を指定します。

| パラメータ型 | 値 |
| --- | --- |
| `none` | 値なし |
| `value_input`、`value_output`、`value_inout` | 符号なし32ビット整数 `a` と `b` |
| `memref_input`、`memref_inout`、`shared_memref_input`、`shared_memref_inout` | `data` は16進バイト列。`size` はバイト数で、省略時は入力データ長 |
| `memref_output`、`shared_memref_output` | `size` は出力バッファの容量（バイト） |

同じ入力列の先行ステップの出力を参照する場合は `inserts` を使います。共有入力に対する実行中の操作は `events` で表し、実測した値を検証記録に保存します。利用できる機能は実行イメージに依存します。[実行イメージ](../docker/README.md)
