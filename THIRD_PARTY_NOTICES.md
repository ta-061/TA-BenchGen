# 第三者のコードとライセンス

このリポジトリのうち、TA-BenchGenの著者が作成した部分は [MIT License](LICENSE) で公開します。ベンチマークには、OP-TEE関連の公開リポジトリから取得したTAのソースと、それに不備を加えた版が含まれます。これらには取得元のライセンスが適用されます。

## 取得元とライセンス

| 対象 | 取得元 | ライセンス | ライセンス文 |
| --- | --- | --- | --- |
| `aes`、`hotp`、`secure_storage` | [optee_examples 4.4.0](https://github.com/linaro-swg/optee_examples/tree/378dc0db2d5dd279f58a3b6cb3f78ffd6b165035) | BSD 2-Clause | [LICENSE.optee_examples](benchmark/normal/LICENSE.optee_examples) |
| `sha`、`ecdsa`、`sign_verify` | [optee_examples 4.11.0](https://github.com/linaro-swg/optee_examples/tree/71e8f3f320eef46a9369700bf30b91d67427d535) | BSD 2-Clause | [LICENSE.optee_examples](benchmark/normal/LICENSE.optee_examples) |
| `gatekeeper` | [kmgk の Gatekeeper TA](https://github.com/linaro-swg/kmgk/tree/b5a86e5ef8fb02381a4d2555f64dc976614e72e3/gatekeeper/ta) | Apache License 2.0 | [LICENSE.kmgk](benchmark/normal/LICENSE.kmgk) |
| `avb` | [optee_os 4.4.0 の AVB TA](https://github.com/OP-TEE/optee_os/tree/8f645256efc0dc66bd5c118778b0b50c44469ae1/ta/avb) | BSD 2-Clause | [avb/LICENSE](benchmark/normal/avb/LICENSE) |
| `pkcs11` | [optee_os の PKCS#11 TA](https://github.com/OP-TEE/optee_os/tree/d75c42ff2847b090d5b1f11c49067cd41fcc2734/ta/pkcs11) | BSD 2-Clause | [pkcs11/ta/LICENSE](benchmark/normal/pkcs11/ta/LICENSE) |
| `results/diting-codeql-semgrep/optee-conf.h` | optee_os のビルドで生成される設定ヘッダ | BSD 2-Clause | 上のoptee_osと同じ |

`shared_record` と `examples/secure_kv` はTA-BenchGenの著者が作成したもので、MIT Licenseです。各ファイルにある著作権表示とライセンス表記は、取得元のまま残しています。[正常TAごとの出典](benchmark/normal/UPSTREAM.md)

## 変更を加えたファイル

次の場所には、上の取得元のソースに設計不備を加えた版があります。変更はTA-BenchGenがLLMの出力をもとに加えたもので、取得元の作者によるものではありません。変更の全内容は各ケースの `changes.diff` で確認できます。

| 場所 | 内容 |
| --- | --- |
| `benchmark/defective/case_*/source/`、`benchmark/rejected/case_*/source/` | 正常TAに不備を加えた不備TA。もとにした正常TAは各ケースの `labels.json` の `normal.path` |
| `generation-records/*/runs/*/request_*/attempt_*/source/` | 生成の各試行で作られた不備TA。もとにした正常TAは `state.json` の各要求の `ta` |

Apache License 2.0の `gatekeeper` をもとにした版は次のとおりです。これらのフォルダ内の `ta/gatekeeper_ta.c` を変更しています。ソースファイルそのものに変更の注記を書き加えると、ラベルの行番号と照合用のハッシュが変わるため、この文書と各ケースの `changes.diff` で変更を示しています。

| 場所 | 変更の記録 |
| --- | --- |
| `benchmark/defective/case_427eec3671c74536/` | [changes.diff](benchmark/defective/case_427eec3671c74536/changes.diff) |
| `benchmark/defective/case_684c4bfe44b04d86/` | [changes.diff](benchmark/defective/case_684c4bfe44b04d86/changes.diff) |
| `benchmark/defective/case_b9e19bc717204a6f/` | [changes.diff](benchmark/defective/case_b9e19bc717204a6f/changes.diff) |
| `benchmark/defective/case_edc7a9e855a140d7/` | [changes.diff](benchmark/defective/case_edc7a9e855a140d7/changes.diff) |
| `generation-records/initial-18-requests_2026-11-20/` の要求3・8・16の各試行 | 各試行の `candidate.json` の `changes` |
| `generation-records/additional-2-requests_2026-11-23/` の要求1・2の各試行 | 各試行の `candidate.json` の `changes` |

## 検出器

検出器の本体はこのリポジトリに含めていません。測定では各配布元から取得して使いました。

| 検出器 | 配布元 | このリポジトリにあるもの |
| --- | --- | --- |
| DITING | [CharlieMCY/PartitioningE-in-TEE](https://github.com/CharlieMCY/PartitioningE-in-TEE/tree/cb72e8861809e70b7b820b0ece54d71f8ff93cd8) | 出力と、型名の条件に加えた変更の差分 [diting-gp11-typename.patch](results/diting-codeql-semgrep/diting-gp11-typename.patch)。差分には、変更箇所の前後にあるDITINGのクエリの行が含まれる |
| CodeQL | [GitHub CodeQL bundle 2.23.0](https://github.com/github/codeql-action/releases/tag/codeql-bundle-v2.23.0) | 出力のみ |
| Semgrep CE | [semgrep 1.164.0](https://pypi.org/project/semgrep/1.164.0/) | 出力のみ |
| TEE Flow Inspector | [ta-061/tee-bad-partitioning-llm-artifact](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/tree/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7)（MIT License） | 出力と、測定用のスクリプト |
