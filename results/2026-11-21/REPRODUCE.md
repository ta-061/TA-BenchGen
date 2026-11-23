# DITING・CodeQL・Semgrep の導入と実行

2026年11月21日に、TA-BenchGen `4fc3ae9` の正常対照16個と不備TA19個をMac上で測定した。DITINGと標準CodeQLは、TAごとに作成した同じC/C++データベースを使った。Semgrepは同じ入力ディレクトリのソースを直接走査した。[入力とSHA-256](inputs.json) · [測定結果](README.md)

## 実行環境

| 項目 | 測定に使った構成 |
| --- | --- |
| Mac | Apple M4、メモリ24 GiB、macOS 27.2（Darwin 27.2.0）、arm64。CodeQLはmacOS x86-64用バンドルをRosettaで実行 |
| Python | pyenvのPython 3.11.10。DITINGの後処理と測定スクリプトに使用。Semgrepは同じPythonで作った専用のvenvにpipで導入 |
| TAのコンパイル | LLVM 20.1.8（macOS ARM64配布版）、ターゲット `aarch64-none-elf`。OP-TEEのarm64開発キットのヘッダ196本と保存済みの設定ヘッダを使用。`CFG_TEE_TA_LOG_LEVEL` は4 |
| ホストのコンパイル | Xcodeの `/usr/bin/clang`（Apple clang 21.0.0、`clang-2100.4.1.1`）とoptee_clientの公開ヘッダ5本 |
| 並列数 | TAを最大4個並列で測定。CodeQLは呼び出しごとに2スレッド・2,048 MBを指定。Semgrepは2ジョブ。CodeQLのクエリキャッシュはTA間で共有 |

ヘッダの出典はoptee_os `496fea3` とoptee_client `8533e0e`。TA側74本とホスト側39本のCファイルをオブジェクトまでコンパイルしてCodeQLに抽出させた。TAごとの `-I`、強制インクルード、GP API 1.1互換指定は実行記録の `compile-plan` にある。[測定環境とハッシュ](environment.json) · [使用した設定ヘッダ](build-config.txt) · [optee_os](https://github.com/OP-TEE/optee_os/tree/496fea3c81a4375e36b41423346499a85c89122e) · [optee_client](https://github.com/OP-TEE/optee_client/tree/8533e0e6329840ee96cf81b6453f257204227e6c/public)

## 導入方法

測定当日は以前に展開したCodeQL・LLVM・DITINGと、既設のSemgrep仮想環境を再利用した。元の導入時に入力したシェルコマンド全文は保存されていない。以下は配布元、実体のバージョン、ファイルのハッシュ、venvのインストール記録から同じ解析ツールを用意する手順である。

| ツール | 取得したものと使い方 |
| --- | --- |
| DITING | `CharlieMCY/PartitioningE-in-TEE` の `cb72e8861809e70b7b820b0ece54d71f8ff93cd8` から `query/*.ql` と `real_world_analysis.py` を取得。7本のクエリと後処理は公開版と同一。作業ディレクトリの `qlpack.yml` で依存を `codeql/cpp-all: 5.5.0` に固定。[DITINGのソース](https://github.com/CharlieMCY/PartitioningE-in-TEE/tree/cb72e8861809e70b7b820b0ece54d71f8ff93cd8) |
| CodeQL | GitHub公式の `codeql-bundle-osx64.tar.gz`（2.23.0）を展開。DITINGには同梱の `cpp-all` 5.5.0、標準解析には `cpp-queries` 1.4.7 の `cpp-security-extended.qls` を使用。[公式バンドル](https://github.com/github/codeql-action/releases/tag/codeql-bundle-v2.23.0) |
| LLVM | `LLVM-20.1.8-macOS-ARM64.tar.xz` を展開し、同梱の `bin/clang` をTA用に指定。[LLVM公式配布](https://github.com/llvm/llvm-project/releases/tag/llvmorg-20.1.8) |
| Semgrep CE | Python 3.11.10のvenvに `semgrep==1.164.0` を導入。Registryの `jQTzvry` と `YDTvRlQ` からC用の2規則を復元し、測定時のYAMLのSHA-256と照合する。[配布版](https://pypi.org/project/semgrep/1.164.0/) · [仮想環境の依存バージョン](replay/semgrep-constraints.txt) · [規則の取得処理](replay/fetch-rules.py) |

Apple SiliconのMacでRosetta、Xcodeのコマンドラインツール、Git、Python 3.11.10を用意する。以下はすべて **TA-BenchGenのルート** で実行する。初回のセットアップはアーカイブのSHA-256を検査し、依存ツールを既定では `~/.local/share/ta-benchgen-static/2026-11-21/` に置く。保存先は `TA_MEASURE_TOOLS` で指定できる。[導入時に実行する全コマンド](replay/setup.sh)

```sh
./results/2026-11-21/replay/setup.sh
```

## 再実行

`TA-BenchGen/` 直下で1個のTAのIDを指定します。下の例の `T07` は測定後に整理された正常対照 `normal/hello_world` です。スクリプトが測定時の入力を復元します。[共通の実行手順](../COMMANDS.md)

```sh
./results/run.sh T07
```

最初に表示される `Output:` の下の `static/jobs/T07/` に、DITINGの `diting.txt`、標準CodeQLの `codeql.sarif`、Semgrepの `semgrep.json` ができます。互換型対応版は `gp11/jobs/T07/diting.txt` に保存します。元の静的解析ドライバで35個すべてを測定する場合は、固定入力を用意して `all` を指定します。所要時間はキャッシュの有無で変わり、既存のキャッシュは `QUERY_CACHE` で指定できます。[35個の再実行手順](../COMMANDS.md#pinned-replay) · [測定時のドライバ](replay/measure.py) · [コンパイル処理](replay/compile.py)

測定当日の作業領域は `/private/tmp/tabenchgen-static-4fc3ae9`。バッチ全体の呼び出しを、保存したドライバと実行設定から書き直すと次の形になる。これは当日の構成を説明する表記で、上の再実行コマンドが必要な変数と新しい出力先を設定する。

```sh
"$PYTHON" measure.py "$WORK" --jobs 4
```

| 測定時の変数 | 指定した実体 |
| --- | --- |
| `BENCHMARK_DIR` | TA-BenchGenの `benchmark/` |
| `CODEQL_DIST`、`LLVM_DIST` | 公式バンドルを展開した `codeql/` と `llvm-20.1.8/`。再開時は `CODEQL_DIST` にシンボリックリンクの参照先の絶対パスを明示 |
| `DITING_ROOT` | 公開版を配置した `published/`。直下に `real_world_analysis.py` と `query/` |
| `SEM_BIN`、`SEMGREP_CONFIG` | 測定用venvの `evaluation-env/bin/` と固定した `semgrep-c.yaml` |
| `TA_DEV_KIT_DIR`、`TA_CONF`、`TEEC_INCLUDE` | `export-ta_arm64/`、生成済みの `optee-conf.h`、optee_clientの `public/` |
| `QUERY_CACHE` | 事前に作成された共有CodeQLキャッシュ。各ツールへは `$WORK/deps/query-cache` として渡した |

## ツールに渡した実行コマンド

以下はT07について、測定記録の絶対パスを変数にまとめたもの。`WORK` は共通スクリプトの `Output:` の下の `static/` で、`sources/T07` はラベルを取り除いた入力、`jobs/T07` はこのTA専用の出力先である。元の498レコードには全35個の実引数がある。各起動の作業ディレクトリ・終了コードと、Cファイル単位のコンパイル引数を確認できる。[元のコマンド記録](commands.jsonl)

```bash
# WORK に表示された作業ディレクトリを設定したシェルでの表記
SRC="$WORK/sources/T07"
JOB="$WORK/jobs/T07"
CLI="$WORK/deps/codeql/codeql"
PYTHON=$(command -v python3.11)
export CODEQL_DIST=$(cd "$WORK/deps/codeql" && pwd -P)
limits=("--common-caches=$WORK/deps/query-cache" --threads=2 --ram=2048)
```

### 共有データベースの作成

```bash
(cd "$SRC" && "$CLI" database create "$JOB/tee_example" --language=cpp --source-root "$SRC" \
  --command "\"$PYTHON\" \"$WORK/compile.py\" \"$JOB/compile.json\"" "${limits[@]}")
```

### DITING

後処理は `jobs/T07/` から起動する。公開スクリプトはそこから `../../query/` と `tee_example` を参照し、`out/` に各クエリの結果を書く。PATH上の記録用ラッパーがCodeQLに共通のキャッシュ、スレッド数、メモリ指定を渡す。[記録用ラッパー](replay/trace-codeql.py)

```bash
(cd "$JOB" && PATH="$WORK/bin:$PATH" DITING_CLI="$CLI" \
  DITING_CACHE="$WORK/deps/query-cache" DITING_TRACE="$JOB/query-calls.jsonl" \
  "$PYTHON" "$WORK/deps/diting/real_world_analysis.py" > diting.txt)
```

これが `host`、`switch`、`arrayaccess`、`ifstmt`、`dataflow`、`memory` の順に6本のクエリを実行し、UDO・IVW・DUSを集計する。`memflow.ql` の補助出力は別に取得した。

```bash
(cd "$JOB" && "$CLI" query run "$WORK/query/memflow.ql" --database "$JOB/tee_example" \
  "${limits[@]}" > out/memflow.out)
```

### 標準CodeQL

```bash
SUITE="$WORK/deps/codeql/qlpacks/codeql/cpp-queries/1.4.7/codeql-suites/cpp-security-extended.qls"
(cd "$SRC" && "$CLI" database analyze "$JOB/tee_example" "$SUITE" \
  --format=sarif-latest --output "$JOB/codeql.sarif" "${limits[@]}")
```

### Semgrep CE

```bash
(cd "$SRC" && "$WORK/deps/sem-bin/semgrep" scan --config "$WORK/deps/rules.yaml" \
  --metrics=off --disable-version-check --oss-only --no-git-ignore --no-rewrite-rule-ids \
  --jobs=2 --json --output "$JOB/semgrep.json" .)
```

全体の実行順は各TAでSemgrep、DB作成、DITING、補助クエリ、標準CodeQL。公開結果ではSARIFをgzip圧縮し、DITINGのクエリ別出力と各段階のログをTAごとにtar.gzにまとめた。[原出力の展開](../README.md#raw-output) · [ツール別の保存先](README.md#出力と実行コマンド)

## 手順の検証

T07・T11・T13を公開結果とは別の作業領域で再実行した。DITINGは作業領域の絶対パスを除いて標準出力が一致し、標準CodeQLは規則・メッセージ・報告位置、Semgrepは警告・診断・走査ファイルが一致した。T11ではDITINGの1件、T13では標準CodeQLの2件を再確認した。CodeQLとLLVMは展開済みの同一版を使い、セットアップに記載したアーカイブ名とSHA-256を公式配布情報と照合した。
