# 生成の実行記録

ベンチマークの不備TAを生成したときの、要求・試行ごとの記録です。論文で報告した「20要求・28試行、うち9試行が検査または機械検証を通過せず、19個の不備TAが通過」は、この2回の実行の合計です。[生成したケースとレビュー結果](../benchmark/README.md)

| フォルダ | 実行ID | 要求 | 試行 | 通過 | 不通過 | 要求ファイル |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| [initial-18-requests_2026-11-20/](initial-18-requests_2026-11-20/) | `run_5c4927afa8984855` | 18 | 24 | 18 | 6 | [requests.production.yaml](../config/requests.production.yaml) |
| [additional-2-requests_2026-11-23/](additional-2-requests_2026-11-23/) | `run_63563ae7bbd14532` | 2 | 4 | 1 | 3 | [requests.dus-additional.yaml](../config/requests.dus-additional.yaml) |
| **合計** | | **20** | **28** | **19** | **9** | |

追加の2要求は、初回でDUSの採用が1件だったために出したものです。分類の定義、モデル、要求ごとの試行上限、レビューの採用基準は初回と同じです。

## フォルダの中身

各実行の `runs/<実行ID>/state.json` に、要求ごとの試行の結果と保存したケースのIDがあります。試行ごとのフォルダは `request_<要求番号>/attempt_<試行番号>/` です。

| ファイル | 内容 |
| --- | --- |
| `api-request.json`、`api-response.json` | LLMに送った要求と、返ってきた応答 |
| `candidate.json` | LLMが出した候補（変更、呼出し列、ラベル案） |
| `plan.json`、`plan-digest.json` | 候補から組み立てた実行計画と、そのハッシュ |
| `source/` | 変更を適用した不備TAのソース |
| `verification.json`、`result.json` | 正常TAと不備TAの観測結果と、機械検証の判定 |
| `failed-semantic.json` | 機械検証を通過しなかった試行の観測結果 |

`normal-inputs/` は、同じ正常TAを使う後続のケースへ引き継ぐ通常入力です。

`state.json` にあるパスは、実行した端末でのリポジトリの場所を `${REPO}` に置き換えてあります。QEMUでのビルド生成物と実行ログは容量が大きいため、ここには含めていません。
