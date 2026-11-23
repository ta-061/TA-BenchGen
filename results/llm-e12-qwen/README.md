# TEE Flow Inspector のローカルLLM測定

Kali上でTEE Flow Inspectorの公開版 `e06f0c6`、プロンプト `experiments/e12_general_sink_screening`、ローカルモデル `Qwen/Qwen3.8-27B` を使い、正常対照16個と不備TA 19個を各1回測定しました。2026年11月23日7時42分（日本時間）に全35個が完了し、すべての試行で候補フロー数と応答記録の完了検査を通過しました。[測定対象版](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/tree/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7) · [最終状態](status.json) · [TA別の件数と出力先](cases.csv)

## 測定結果

| 対象 | TA（個） | 候補フロー | 受理したモデル応答 | 報告数 | 報告のあったTA（報告数） |
| --- | ---: | ---: | ---: | ---: | --- |
| 現行の正常対照 | 10 | 525 | 2,131 | 366 | T03 avb（3）、T09 PKCS#11（363） |
| 現行の不備TA | 15 | 502 | 2,176 | 238 | T26 avb（7）、T33 PKCS#11（231） |
| **現行の合計** | **25** | **1,027** | **4,307** | **604** | **4個** |
| 旧正常対照 | 6 | 17 | 103 | 9 | T16 storage（9） |
| 人手却下の不備TA | 4 | 0 | 62 | 0 | 0個 |
| **測定全体** | **35** | **1,044** | **4,472** | **613** | **5個** |

報告数は各TAの `ta_vulnerabilities.json` にある統合後の指摘数です。現行25個の604件のうち594件がPKCS#11の正常対照と不備TAに集中しました。現行25個を報告の主分類で数えると、DUSが516件、IVWが79件、UDOが9件です。[TA別のHTML・JSONの展開](../README.md#raw-output) · [他手法との比較（Excel）](../outputs/label-comparison/TA別検知結果.xlsx)

### 正解ラベルとの照合

人手承認済みの不備16件のうち、報告がラベル位置に重なったのはT26/D1の1件です。論文で採用した18件にはPKCS#11の未レビューのORDER 2件も含み、T33/D1が加わって位置一致は2件です。いずれも効果位置で、保護位置を持つ不備14件では位置一致は0件でした。[ラベル位置別の照合（CSV）](locations.csv) · [他手法と同じ条件での集計（CSV）](../outputs/label-comparison/paper-roles.csv)

| 不備TA・ラベル | ラベル分類 | 一致した効果位置 | 報告ID | 報告の主分類 |
| --- | --- | --- | --- | --- |
| T26 avb・D1（人手承認） | ORDER | `ta/entry.c:166` | `VULN-0005` | IVW |
| T33 PKCS#11・D1（未レビュー） | ORDER | `ta/src/pkcs11_token.c:1207` | `VULN-0085` | DUS |

TEE Flow Inspectorの主分類を対応付けられる承認済みの不備はIVW・UDO・DUSの13件で、位置と主分類がともに一致した不備は0件です。ORDERは分類一致の集計対象外です。各報告IDは、展開後の `cases/T26/attempt-01/outputs/results_1/ta_vulnerabilities.json` およびT33の同名ファイルで確認できます。

## 実行環境とインストール

Macは結果の収集に使い、ソース解析はKaliのDockerコンテナ、LLM推論は別ホストの既設vLLMで実行しています。

| 項目 | 測定に使った構成 |
| --- | --- |
| 解析ホスト | Kali GNU/Linux Rolling 2026.3、x86-64、Linux `6.19.11+kali-amd64`、Intel Core i7-13700F、Docker Engine 29.8.1 |
| コンテナ | `ta-bench-llm:e12`（測定時のイメージID `sha256:ac4feb4da4d5951890f8308a62a825722edb96f65d8aa6a29631b576121dafb4`）。Debian 13、linux/amd64、Python 3.12.15。`python:3.12-slim` のベースイメージをダイジェストで固定 |
| ソース解析 | Pythonパッケージ `libclang==18.1.1`。Kali側のClang 18.1.8のリソースヘッダをマウントし、公開版のパーサーが `--target=armv7a-none-eabi` でTA側のCファイル74本を処理。各コンパイル単位の正規化前のコンパイル引数はTA別に保存 |
| LLM | `Qwen/Qwen3.8-27B`、vLLM `0.18.2rc1.dev73+gdb7a17ecc`。GPU 0のOpenAI互換APIを使用。コンテキスト98,304トークン、各TAの同時リクエストは1、thinking無効。TAごとに1回測定 |

測定記録では内部サーバーのホスト名を `vllm.example` と表記しました。`parallel-plan.json` の `profile_sha256` は測定時の設定に、`public_profile_sha256` は公開した `profile.json` に対応します。

測定用コンテナには固定リビジョンの公開実装をマウントし、ローカルプロバイダーの設定ファイルを加えました。Dockerのレイヤー履歴で確認したPythonパッケージの導入コマンドは次のとおりです。vLLMとモデルは起動済みのサービスを使用し、サーバー側の初回インストール操作はこの測定では記録していません。[Dockerfile](replay/Dockerfile) · [コンテナ内の全Pythonパッケージ](replay/python-packages.txt) · [推論設定](profile.json) · [プロバイダー設定](replay/llm_config.json)

```sh
python -m pip install --no-cache-dir libclang==18.1.1 openai==1.109.1 requests==2.32.5 tiktoken==0.12.0 tabulate==0.9.0 PyYAML==6.0.3
```

## 測定時の実行コマンド

PKCS#11の正常対照T09と不備TA T33は一部の時間帯に同じGPUで並行実行しました。T33の実際の開始は11月22日17時15分、T09の完了は23日0時46分、T33の完了は23日7時42分（いずれも日本時間）です。同時推論は各TA最大1件、2個の合計で最大2件でした。T33の `commands.jsonl` の時刻は通常バッチがこのTAを選択した時刻で、先行実行の時刻と引数は `parallel-run.json` に記録されています。[並行実行の設定と開始コマンド](parallel-plan.json) · [T09の実行記録](cases/T09/attempt-01/run.json) · [T33の先行実行記録](cases/T33/attempt-01/parallel-run.json)

測定時にはKaliのsystemdユーザーサービスからDockerを起動しました。コンテナの `/work` でバッチ処理がTAを1個ずつ選び、たとえばT07では次を実行しました。[当日のDocker起動コマンドとマウント](replay/batch-command.sh) · [通常バッチの実引数と時刻](commands.jsonl)

```sh
/usr/local/bin/python /ops/bootstrap.py /workspace /inputs/T07 \
  /results/cases/T07/attempt-01/outputs /support/devkit
```

`/inputs/T07` は正解ラベルを除いたソース一式、`/support/devkit` はOP-TEEのヘッダです。起動スクリプトは保存済みの `compile_commands.json` を渡し、公開版の `process_project` を呼び出します。公開版が起動した各段階のコマンドもTA別のログに残っています。[起動スクリプト](replay/bootstrap.py) · [全35個分のコンパイル引数](replay/compile-commands.json) · [TA別ログの展開](../README.md#raw-output)

## 別の作業ディレクトリで1個を再実行

KaliでDockerと `/usr/lib/llvm-18/lib/clang/18/include` を使用します。ヘッダのパッケージは `clang-18` と `libclang-common-18-dev`（測定機では両方とも `1:18.1.8-20+b3`）です。1行目のURLにコンテナから接続できる自分のvLLMの推論先を指定し、リポジトリ直下で実行します。セットアップは接続先を保存します。[共通の実行手順](../COMMANDS.md)

```sh
TA_LLM_BASE_URL=http://vllm.example:8000/v1 ./results/llm-e12-qwen/replay/setup.sh
./results/run.sh T07
```

セットアップは公開リビジョンの取得、推論設定とOP-TEEヘッダの配置、測定時のPython依存バージョンを固定した再実行用イメージ `ta-bench-llm:e12-replay` のビルドを行います。既定の導入先は `~/.local/share/ta-benchgen-e12/` で、`TA_LLM_TOOLS` でも指定できます。再実行すると、最初に表示される `Output:` の下の `llm/command.txt` にDockerの実引数、`llm/run.log` にログ、`llm/results/cases/T07/attempt-01/outputs/results_1/` にJSONとHTMLが保存されます。[導入コマンドの全文](replay/setup.sh) · [1個のTAを起動する処理](replay/run-case.py)

再実行用イメージをKaliでビルドしてT11を実行し、元の記録と同じ候補フロー0件・指摘0行と、HTMLの生成を確認しました。T11はモデル呼び出しが0回の入力です。推論が発生する入力の測定例は、T07のコマンドと実行ログを参照できます。

## 記録の見方

各TAの完了検査をGitに、JSON・HTML・実行ログをRelease用のアーカイブに収録しました。下の表のパスは `results/llm-e12-qwen/` からの相対パスです。[原出力の展開手順](../README.md#raw-output)

| 記録 | 内容 |
| --- | --- |
| [cases.csv](cases.csv) | TAごとの状態、試行回数、解析フロー数、指摘行数、受理したモデル応答数、出力先 |
| [locations.csv](locations.csv) | 全35個に含まれるラベル位置39か所の照合。1行が1か所で、`hits` は位置に重なった報告数、`same_class` はそのうち主分類も一致した件数。分類対応のないORDERは空欄。`is_public` と `is_approved` は公開位置・人手承認位置を示す |
| [commands.jsonl](commands.jsonl) | 通常バッチが各TAを選択した時刻と実際の引数。T33の先行実行時刻は [parallel-run.json](cases/T33/attempt-01/parallel-run.json) に記録 |
| `cases/Txx/attempt-XX/` | `run.log` に各段階の実行記録、`coverage.json` に完了検査、`outputs/results_1/` にツールが生成したJSON・HTML |
| [inputs.json](inputs.json) | T01〜T35とベンチマークの対応、入力ファイルのハッシュ |
| [profile.json](profile.json)・[preflight.json](preflight.json)・[parse.json](parse.json) | モデル・推論設定、接続確認、TA側のCファイル74本の構文解析結果 |

`cases.csv` の `completed` は出力と応答記録の検査が済んだ試行です。T11とT31は審査対象の外部APIと候補フローがともに0件で正常終了したため、`api_calls` は0です。`findings` はツールが報告した指摘行数です。
