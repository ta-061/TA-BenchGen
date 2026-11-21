# 論文誌用TAベンチマーク

| 由来 | 収録した正常対照 | 不備TA | ラベル上の不備 |
| --- | ---: | ---: | ---: |
| 2026-11-20の生成実行 | 15 | 18 | 21 |
| 既存のPKCS#11主比較 | 1 | 1 | 2 |
| 合計 | 16 | 19 | 23 |

## 2026-11-20の生成ケース

生成器の `benchmark/` をこのフォルダに複製した。18要求に対する24試行のうち18個の不備TAが機械検証を通過し、すべての保存ケースIDが実行記録と一致する。収録した正常対照15個のうち9個が、これらのケースの比較に使われた。 [コピー元](../ta-benchmark-generator/benchmark/) · [実行記録 `run_5c4927afa8984855`](../ta-benchmark-generator/work/production-20261120/runs/run_5c4927afa8984855/state.json)

保存時のケース状態は `approved` が13個、`unreviewed` が5個。`approved` の13個には承認の詳細・照合用ハッシュが省略されており、現行の生成器のスキーマ検査ではレビュー詳細不足として扱われる。収録数は保存ケースの数である。 [生成器のレビュー仕様](../ta-benchmark-generator/README.md#データ再検証ブラインド出力)

## PKCS#11の主比較

| 役割 | 既存の識別子 | 収録先 |
| --- | --- | --- |
| 正常対照 | P00 / T05 / PKCS11-F | [normal/pkcs11/](normal/pkcs11/) |
| 複合不備TA | P03 / T06 / PKCS11-V | [defective/case_e264a169df23d680/](defective/case_e264a169df23d680/) |

生成ケースと同じ配置で、不備TAの `source/`、正常対照からの `changes.diff`、`labels.json`、`verification.json` を収録した。旧ラベルの位置を引き継ぎ、C1（I01）とC2（I02）を `ORDER` の D1・D2 に対応付けた。元ラベルの著者確認は2026-11-08付の記録にあり、形式変換後のレビュー状態は `unreviewed` とした。 [不備TAのソース](defective/case_e264a169df23d680/source/) · [差分](defective/case_e264a169df23d680/changes.diff) · [ラベル](defective/case_e264a169df23d680/labels.json) · [著者確認](../03_experiments_2026-09-29/参考資料/著者確認と差分証拠.md#現行taデータセットの著者確認)

`verification.json` は、P00とP03それぞれの8シナリオ、計16観測を保存済みのQEMU制御比較から転記した。P01・P02は原因確認用の補助対照で、比較結果の概要と出典を検証記録に残した。PKCS#11の検証記録は `pkcs11-controlled-1` 形式で、保存済みの比較結果を参照するためのもの。生成器の自動再検証はR1–R3の保存形式を使う。 [検証記録](defective/case_e264a169df23d680/verification.json) · [4条件の比較記録](../03_experiments_2026-09-29/pkcs11_pair/controlled/README.md)
