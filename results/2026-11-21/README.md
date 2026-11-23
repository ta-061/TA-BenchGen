# 2026-11-21 の静的解析

TA-BenchGenの `4fc3ae9` に収録した正常対照16個と不備TA19個を測定しました。表の値は各ツールが返した警告の延べ件数です。TAごとの件数、対応する正常対照、解析時間も確認できます。[TA別集計](cases.csv)

| 区分 | TA（個） | DITING | 標準CodeQL | Semgrep CE |
| --- | ---: | ---: | ---: | ---: |
| 正常対照 | 16 | 37 | 2 | 0 |
| 不備TA・生成分（全件承認） | 13 | 9 | 2 | 0 |
| 不備TA・生成分（一部承認） | 1 | 0 | 2 | 0 |
| 不備TA・生成分（却下） | 4 | 0 | 2 | 0 |
| 不備TA・PKCS#11比較ケース | 1 | 11 | 0 | 0 |
| **合計** | **35** | **57** | **8** | **0** |

全件承認の不備TA13個には15件の不備があり、対応する正常対照は8個です。公開ラベルが指定するファイルと行範囲に警告が重なった不備は、DITING 0件、標準CodeQL 0件、Semgrep 0件でした。DITINGが扱う分類（UDO・IVW・DUS）の12件のうち、位置と分類がともに一致した不備は0件です。別集計のPKCS#11比較ケースでも、2件の不備の指定位置に重なった警告は3ツールとも0件でした。[検出位置ごとの照合](locations.csv)

導入に使った配布版、Macの構成、3ツールを起動したコマンド、T07を再実行する手順をまとめました。[インストール・実行環境・実行コマンド](REPRODUCE.md)

## 測定条件と解析範囲

- 各ツールの入力は、ベンチマークの `ta/`・`host/`・`include/` から入力ID別に複製したCソースとヘッダです。全35個で延べ232ファイルです。ラベル・差分・実行時の検証記録は解析入力の外に置き、位置照合に公開ラベルを使用しました。[入力ごとのパスとSHA-256](inputs.json) · [ベンチマークの説明](../../benchmark/README.md)
- **DITING** は公開版の6本のクエリと後処理で、UDO 57件、IVW 0件、DUS 0件を報告しました。7本目の `memflow.ql` は補助出力として別に記録しました。公開の後処理と同じコマンド・引数の対応条件を通るデータフローが1行以上あったTAは0個です。ホストソースを同梱しないTAは10個で、UDOの判定はこの対応付けと独立しています。[DITINGの固定リビジョン](https://github.com/CharlieMCY/PartitioningE-in-TEE/tree/cb72e8861809e70b7b820b0ece54d71f8ff93cd8)
- **標準CodeQL** はCLI 2.23.0、`cpp-security-extended.qls`（`cpp-queries` 1.4.7、`cpp-all` 5.5.0）です。入力ごとにTAと付属ホストのCソースをオブジェクトまでコンパイルし、DITINGと同じデータベースを使用しました。TA側74本、ホスト側39本のすべてについて、抽出成功の診断と、データベース内のソースがベンチマークとバイト単位で一致することを確認しました。[CodeQL Bundle](https://github.com/github/codeql-action/releases/tag/codeql-bundle-v2.23.0) · [出力の検算記録](verification.json)
- **Semgrep CE** は1.164.0で、`gets` と乱数デバイスからの読み出しを調べるC用の2規則を固定しました。走査対象は延べ232ファイルで、35個中27個が全ファイルを診断なしで完了しました。残り8個から計14件の `PartialParsing` が返りました。該当するファイル・範囲は各JSONの `errors` にあります。[gets規則](https://semgrep.dev/playground/r/YDTvRlQ/c.lang.security.insecure-use-gets-fn.insecure-use-gets-fn) · [乱数デバイス規則](https://semgrep.dev/playground/r/jQTzvry/c.lang.security.random-fd-exhaustion.random-fd-exhaustion)

## 出力と実行コマンド

ツール別のディレクトリとログはRelease用アーカイブに収録しました。展開先は `results/2026-11-21/` です。[原出力の展開手順](../README.md#raw-output)

| 保存先 | 内容 |
| --- | --- |
| [cases.csv](cases.csv) · [summary.json](summary.json) | 入力別の結果と区分別の合計。`normal_id` は対応する正常対照、`*_seconds` は経過秒数 |
| `diting/` | 入力ID別の標準出力。3分類の件数と報告位置 |
| `codeql/` | 入力ID別のSARIF（gzip圧縮）。`runs[].results` が報告、`invocations` が実行診断 |
| `semgrep/` | 入力ID別のJSON。`results` は報告、`paths.scanned` は走査ファイル |
| [commands.jsonl](commands.jsonl) | 実引数、作業ディレクトリ、UTC開始時刻、経過秒数、終了コード。DITING内部の6回の呼び出しと各Cファイルのコンパイル引数を含む |
| `logs/` | 入力IDごとのログ（tar.gz）。アーカイブ内の `logs/` に各段階の実行ログ、`out/` にDITINGの7本のクエリの出力 |
| [environment.json](environment.json) · [build-config.txt](build-config.txt) | 測定環境、ツールとヘッダの版・ハッシュ、TA用のビルド設定 |

たとえばPKCS#11の不備TAは `T33`、対応する正常対照は `T09` です。次のコマンドをこの測定ディレクトリで実行すると、不備TAのコマンドと出力を確認できます。

```sh
jq -c 'select(.id == "T33")' commands.jsonl
cat diting/T33.txt
gzip -dc codeql/T33.sarif.gz | jq '.runs[].results'
jq '{results, errors}' semgrep/T33.json
tar -tzf logs/T33.tar.gz
```

コマンド記録の `${WORK}` は一時作業ディレクトリ、`${PYTHON}` は測定に使ったPythonです。補助ログでは個人のホームディレクトリ配下のインストール先を環境変数名に置き換えました。各ツールの主出力105ファイルは、圧縮を戻したバイト列を元の出力と照合しました。

経過時間には共有クエリキャッシュの利用も含まれます。計測は入力4個までを並列実行し、CodeQLを使う各段階に2スレッド・2,048 MBを指定しました。`database_seconds` は共有データベースの作成時間、`diting_seconds` は6本のクエリと後処理の合計、`memflow_seconds` は補助クエリの時間です。`compile-plan` 行にはコンパイル引数を記録しています。TAにはLLVM 20.1.8とarm64用開発キット、ホストにはApple Clangとoptee_clientの公開ヘッダを使用しました。[OP-TEE OSのリビジョン](https://github.com/OP-TEE/optee_os/tree/496fea3c81a4375e36b41423346499a85c89122e) · [クライアントヘッダ](https://github.com/OP-TEE/optee_client/tree/8533e0e6329840ee96cf81b6453f257204227e6c/public)

位置照合は、全件承認の生成ケースとPKCS#11の比較ケースを区別して記録しました。各ツールの主報告が同じファイルの指定行範囲に重なれば、その報告を1件として数えます。`diting_same_class` は分類も一致した件数で、DITINGに対応する分類がない `ORDER` では空欄です。同じ不備の複数位置に報告が重なった場合、冒頭の不備件数では1件にまとめています。

22:45（日本時間）の停止時点で3ツールが完了していた27個の記録を引き継ぎ、23:19に残り8個を再開しました。停止前に保存したツール出力86ファイルのSHA-256は、完了後にも一致しました。再開時にCodeQLのバンドル実体を `CODEQL_DIST` で指定し、C/C++抽出器またはクエリパックを読み込めなかった段階を再実行しました。表の件数と時間には、最終集計に使った実行を計上しています。[停止時の記録](checkpoint.json) · `logs/attempts.tar.gz`
