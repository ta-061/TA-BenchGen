# 各ツールに渡したコマンド

不備TA 16個に対して、DITING（GP 1.1互換の型名に対応させたもの）、標準CodeQL、Semgrep CE、TEE Flow Inspector＋GPT-5.2を実行しました。この文書は、**各ツールの配布元が示す実行手順**と、**今回実際に渡したコマンド**を並べて示します。例にはT18（ECDSAのIVW、`defective/case_19b7f03571ec46b1`）を使います。[IDとケースの対応](cases.json) · [測定結果](README.md)

測定では16個を並列に処理するためにスクリプトを使いましたが、各ツールに渡る引数は以下のコマンドと同じです。TAごとの実引数は記録から確認できます。

| ツール | TAごとの実引数の記録 | 一括実行に使ったスクリプト |
| --- | --- | --- |
| DITING・標準CodeQL・Semgrep | `diting-codeql-semgrep/cases/Txx/commands.json` | [diting-codeql-semgrep/scripts/run.py](diting-codeql-semgrep/scripts/run.py) |
| TEE Flow Inspector | `tee-flow-inspector-gpt52/run-NN/cases/Txx/attempt-NN/phase-commands.jsonl`、候補生成は同じ場所の `outputs/results_1/phase4-command.json` | [run-batch.sh](tee-flow-inspector-gpt52/scripts/run-batch.sh) · [batch.py](tee-flow-inspector-gpt52/scripts/batch.py) |

記録中の `${WORK}` は測定用の作業ディレクトリ、`${TOOLS}` はツールの導入先、`${PYTHON}` はPython 3.11の実行ファイルです。

## 配布元の手順との違い

| ツール | 配布元の手順 | 今回変えた点 | 変えていない点 |
| --- | --- | --- | --- |
| DITING | `codeql database create tee_example --language=c-cpp --command=make --overwrite` の後に `python ../../real_world_analysis.py` | ①型名の条件に `__GP11_TEE_Param` を追加（4ファイル6行）。②`make` の代わりに、TAとホストのCファイルを1本ずつコンパイルするコマンドを指定。③CodeQLにキャッシュ・スレッド数・メモリ上限を指定 | 7本のクエリの他の行、後処理の `real_world_analysis.py`、作業ディレクトリの構成（`../../query/` と `tee_example`） |
| 標準CodeQL | `codeql database analyze` に同梱の `cpp-security-extended.qls` を指定 | なし（DITINGと同じデータベースを使用） | 同梱スイートとクエリ |
| Semgrep CE | `semgrep scan --config <規則>` | 規則をC用の2本に固定 | 規則の内容 |
| TEE Flow Inspector | `python3 src/main.py -p <プロジェクト> --prompt-version experiments/e12_general_sink_screening`。内部でフェーズ1〜6を順に実行 | ①フェーズ4の `--sources` にエントリポイントのGP 1.1互換名2つを追加。②フェーズ4に渡すシンク一覧に、同じシンクの互換名を追加。③モデルをGPT-5.2に設定。④6つのフェーズを `main.py` からではなく1つずつ起動 | 各フェーズのプログラム、プロンプト、規則、フェーズ3・5・6の引数 |

配布元の手順の出典は、DITINGが [PartitioningE-in-TEE のREADME](https://github.com/CharlieMCY/PartitioningE-in-TEE/tree/cb72e8861809e70b7b820b0ece54d71f8ff93cd8#usage)、TEE Flow Inspectorが [公開版のREADME](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/tree/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7) と [main.py のフェーズ呼び出し](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/blob/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7/src/main.py#L375-L405) です。

## DITING

### 型名の変更

OP-TEEのサンプルTAの多くは `CFG_TA_OPTEE_CORE_API_COMPAT_1_1=y` でビルドされ、引数の型名が `TEE_Param` から `__GP11_TEE_Param` に置き換わります。公開版のクエリは `TEE_Param` だけを入力として扱うため、次の形の変更を `arrayaccess.ql`・`dataflow.ql`・`memflow.ql` に各1行、`memory.ql` に3行加えました。[差分の全文](diting-codeql-semgrep/diting-gp11-typename.patch) · [変更後の各ファイルのSHA-256](diting-codeql-semgrep/environment.json)

```diff
-            arrayExpr.getType().toString() = "TEE_Param" and
+            arrayExpr.getType().toString() = ["TEE_Param", "__GP11_TEE_Param"] and
```

公開版 `cb72e886` のクローンに同じ変更を適用するコマンドです。

```sh
git -C PartitioningE-in-TEE apply "$PWD/results/diting-codeql-semgrep/diting-gp11-typename.patch"
```

### データベースの作成

配布元の手順は `--command=make` でTAをビルドします。今回は、OP-TEEのビルド環境全体を用意する代わりに、TAとホストのCファイルを1本ずつ `clang -c` でコンパイルするコマンドを `--command` に渡しました。CodeQLはこのコンパイルを監視してソースを抽出します。

```sh
cd "$WORK/sources/T18"
codeql database create "$WORK/jobs/T18/tee_example" --language=cpp --source-root "$WORK/sources/T18" \
  --command "python3.11 $WORK/compile.py $WORK/jobs/T18/compile.json" \
  --common-caches="$WORK/cache" --threads=2 --ram=2048
```

`compile.json` に並ぶコマンドは次の2種類です。TA側は開発キットのヘッダと設定ヘッダを使い、GP 1.1互換のTAには `-D__OPTEE_CORE_API_COMPAT_1_1=1` を付けます。[コンパイルを順に実行するスクリプト](diting-codeql-semgrep/scripts/compile.py) · [設定ヘッダ](diting-codeql-semgrep/optee-conf.h)

```sh
# TA側（ta/ 以下のCファイルごと）
/usr/lib/llvm-18/bin/clang --target=aarch64-none-elf -ffreestanding -fno-builtin \
  -include "$WORK/deps/conf.h" -include "$WORK/deps/log-level.h" -D__OPTEE_CORE_API_COMPAT_1_1=1 \
  -I "$WORK/sources/T18/ta/include" -I "$WORK/sources/T18/ta" -I "$WORK/deps/devkit/include" \
  -c ta/ecdsa_ta.c -o "$WORK/jobs/T18/objects/0.o"

# ホスト側（host/ 以下のCファイルごと）
/usr/bin/clang -I "$WORK/sources/T18/ta/include" -I "$WORK/deps/client" \
  -c host/main.c -o "$WORK/jobs/T18/objects/1.o"
```

`$WORK/sources/T18` は、ベンチマークの `source/` から `ta/`・`host/`・`include/` の `.c`・`.h`・`.s`・`.S` だけを複製したものです。ラベルや差分のファイルは解析対象に入りません。

### 解析

配布元と同じく、データベースのあるディレクトリで後処理スクリプトを起動します。スクリプトは `../../query/` のクエリを順に実行し、UDO・IVW・DUSの警告を標準出力に書きます。

```sh
cd "$WORK/jobs/T18"
python3.11 "$WORK/real_world_analysis.py" > diting.txt
```

スクリプトが内部で実行するCodeQLのコマンドは次の6本です。`--common-caches` 以降の3つは、PATH上に置いた記録用ラッパーが付け加えます。[記録用ラッパー](diting-codeql-semgrep/scripts/trace-codeql.py)

```sh
codeql query run ..//..//query//host.ql        --database=tee_example --common-caches="$WORK/cache" --threads=2 --ram=2048
codeql query run ..//..//query//switch.ql      --database=tee_example --common-caches="$WORK/cache" --threads=2 --ram=2048
codeql query run ..//..//query//arrayaccess.ql --database=tee_example --common-caches="$WORK/cache" --threads=2 --ram=2048
codeql query run ..//..//query//ifstmt.ql      --database=tee_example --common-caches="$WORK/cache" --threads=2 --ram=2048
codeql query run ..//..//query//dataflow.ql    --database=tee_example --common-caches="$WORK/cache" --threads=2 --ram=2048
codeql query run ..//..//query//memory.ql      --database=tee_example --common-caches="$WORK/cache" --threads=2 --ram=2048
```

後処理が使わない `memflow.ql` の出力も、参考として別に取得しました。警告の集計には使っていません。

```sh
codeql query run "$WORK/query/memflow.ql" --database "$WORK/jobs/T18/tee_example" \
  --common-caches="$WORK/cache" --threads=2 --ram=2048 > out/memflow.out
```

T18の出力は次のとおりです。IVWの1件目（293行目）がラベルの効果行に重なります。[T18の出力](diting-codeql-semgrep/cases/T18/diting.txt) · [クエリごとの表](diting-codeql-semgrep/cases/T18/diting-queries/)

```text
Unencrypted Data Output: 3
['file://${WORK}/sources/T18/ta/ecdsa_ta.c:288:20:288:23', 'file://${WORK}/sources/T18/ta/ecdsa_ta.c:294:19:294:22', 'file://${WORK}/sources/T18/ta/ecdsa_ta.c:133:20:133:23']
Input Validation Weakness: 2
['callto__GP11_TEE_MemMovefile://${WORK}/sources/T18/ta/ecdsa_ta.c:293:2:293:12', 'callto__GP11_TEE_MemMovefile://${WORK}/sources/T18/ta/ecdsa_ta.c:130:4:130:14']
Shared Memory Overwrite: 0
[]
```

## 標準CodeQL

DITINGと同じデータベースに、CodeQL同梱のセキュリティ用スイートを適用しました。

```sh
cd "$WORK/sources/T18"
codeql database analyze "$WORK/jobs/T18/tee_example" \
  "$TOOLS/codeql/qlpacks/codeql/cpp-queries/1.4.7/codeql-suites/cpp-security-extended.qls" \
  --format=sarif-latest --output "$WORK/jobs/T18/codeql.sarif" \
  --common-caches="$WORK/cache" --threads=2 --ram=2048
```

## Semgrep CE

同じソースの複製を直接走査しました。規則はSemgrep RegistryのC用2本（`random-fd-exhaustion`、`insecure-use-gets-fn`）です。[規則の取得](diting-codeql-semgrep/scripts/fetch-rules.py)

```sh
cd "$WORK/sources/T18"
semgrep scan --config "$WORK/deps/rules.yaml" --metrics=off --disable-version-check --oss-only \
  --no-git-ignore --no-rewrite-rule-ids --jobs=2 --json --output "$WORK/jobs/T18/semgrep.json" .
```

T33では解析エンジンが1回強制終了したため、同じコマンドをもう1回実行しました。両方の実行を `commands.json` に記録しています。

## TEE Flow Inspector＋GPT-5.2

公開版の `main.py` は、次の6段階を1回の起動で順に実行します。今回は同じプログラムを段階ごとに起動し、**全段階を3回、それぞれ最初から**実行しました。ある回の出力や応答を別の回が使うことはありません。パスは測定用コンテナ内のもので、`$OUT` はそのTA・その回の出力先（`/results/cases/T18/attempt-01/outputs/results_1`）です。

| フェーズ | 内容 | プログラム | 今回の実行 |
| --- | --- | --- | --- |
| 1・2 | 関数の分類 | `classify/classifier.py` の `classify_functions` | 公開版のまま（LLMは使わない） |
| 3 | シンクの特定（LLM） | `identify_sinks/identify_sinks.py` | 引数は公開版と同じ。モデルはGPT-5.2 |
| 4 | 候補フローの生成 | `identify_flows/generate_candidate_flows.py` | `--sources` と `--sinks` に互換名を追加 |
| 5 | フローの判定（LLM） | `analyze_vulnerabilities/taint_analyzer.py` | 引数は公開版と同じ。モデルはGPT-5.2 |
| 6 | 報告の生成 | `report/generate_report.py` | 公開版と同じ |

`main.py` をそのまま使わなかった理由は2つあります。フェーズ4の引数が `main.py` の中に固定されていて互換名を渡せないことと、`main.py` がビルドツールbearでコンパイル情報を作る前提になっていて、測定環境にはbearがないことです。コンパイル情報はあらかじめ用意した `compile_commands.json` を渡しました。各項目は次の形です。[入力を用意するスクリプト](tee-flow-inspector-gpt52/scripts/stage_input.py)

```sh
clang -ffreestanding -fno-builtin -include/support/conf.h -include/support/log-level.h \
  -D__OPTEE_CORE_API_COMPAT_1_1=1 -I/inputs/T18/ta -I/inputs/T18/ta/include \
  -I/support/devkit/include -I/support/clang/include -c /inputs/T18/ta/ecdsa_ta.c
```

### フェーズ1・2

`main.py` が呼ぶのと同じ関数で、利用者定義の関数と外部宣言の一覧 `ta_phase12.json` を作ります。LLMを使わないため、3回とも同じ内容になりました。[呼び出しスクリプト](tee-flow-inspector-gpt52/scripts/phase12.py)

```sh
python /eval/phase12.py /inputs/T18/ta $OUT/ta_phase12.json
```

### フェーズ3

TAが呼ぶ外部関数ごとに、シンクになり得るかをLLMに判定させます。引数は公開版の `main.py` が渡すものと同じです。

```sh
python src/identify_sinks/identify_sinks.py -i $OUT/ta_phase12.json -o $OUT/ta_sinks.json \
  --llm-only --prompt-version experiments/e12_general_sink_screening
```

### フェーズ4

公開版は `--sources` にエントリポイント名を2つだけ指定します。GP 1.1互換でビルドされるTAでは、これらの関数名が `__GP11_` で始まる名前に置き換わるため、公開版の指定では候補がほとんど生成されません。今回は互換名を追加しました。[候補生成のスクリプト](tee-flow-inspector-gpt52/scripts/phase4.py)

```sh
# 公開版
python src/identify_flows/generate_candidate_flows.py --compile-db compile_commands.json \
  --sinks $OUT/ta_sinks.json --phase12 $OUT/ta_phase12.json \
  --sources TA_InvokeCommandEntryPoint,TA_OpenSessionEntryPoint \
  --output $OUT/ta_candidate_flows.json --devkit /support/devkit

# 今回（GP 1.1互換のTA）
python src/identify_flows/generate_candidate_flows.py --compile-db compile_commands.json \
  --sinks $OUT/ta_sinks_gp11.json --phase12 $OUT/ta_phase12.json \
  --sources TA_InvokeCommandEntryPoint,TA_OpenSessionEntryPoint,__GP11_TA_InvokeCommandEntryPoint,__GP11_TA_OpenSessionEntryPoint \
  --output $OUT/ta_candidate_flows.json --devkit /support/devkit
```

`ta_sinks_gp11.json` は、フェーズ3で選ばれたシンクのうち、OP-TEEの `tee_api_compat.h` に `#define 名前 __GP11_名前` の定義がある行を複製し、関数名だけを互換名にしたものです。引数番号と規則IDは元の行と同じです。互換名を使わないTA（T31）には公開版の指定をそのまま使いました。

### フェーズ5・6

フェーズ4で得た候補を1件ずつ判定し、最後に報告をまとめます。引数は公開版の `main.py` が渡すものと同じです。

```sh
python src/analyze_vulnerabilities/taint_analyzer.py --flows $OUT/ta_candidate_flows.json \
  --phase12 $OUT/ta_phase12.json --output $OUT/ta_vulnerabilities.json \
  --prompt-version experiments/e12_general_sink_screening

python src/report/generate_report.py --sinks $OUT/ta_sinks_gp11.json --flows $OUT/ta_candidate_flows.json \
  --vulnerabilities $OUT/ta_vulnerabilities.json --phase12 $OUT/ta_phase12.json \
  --project-name T18 --output $OUT/ta_vulnerability_report.html
```

### LLMの呼び出しの記録

測定では、フェーズ3の `identify_sinks.py` とフェーズ5の `taint_analyzer.py` を記録用のスクリプト経由で起動しました。このスクリプトはOpenAI APIの要求と応答を記録し、想定外のモデルや設定の要求を止めます。プログラムに渡る引数は変えません。記録上のコマンドは `python /eval/invoke.py T18 <記録先> <作業領域> <上の引数>` の形になっています。[記録用スクリプト](tee-flow-inspector-gpt52/scripts/invoke.py)

モデルの設定は次のとおりです。[設定ファイル](tee-flow-inspector-gpt52/llm_config.json)

| 項目 | 値 |
| --- | --- |
| API | OpenAI Responses API |
| モデル | `gpt-5.2-2025-12-11` |
| temperature | 0.7 |
| reasoning effort | `none` |
| 出力上限 | 16,384トークン（上限で打ち切られた応答は32,768で再試行） |

### 3回の実行

1回分は、15個のTAを並列に処理します。3回は別々の作業領域で同時に実行しました。1回分を実行するコマンドです。

```sh
./results/tee-flow-inspector-gpt52/scripts/run-batch.sh run-02
```

### PKCS#11のT33

T33は候補が484件あり費用が大きいため、1回だけ測定しました。この1個だけ、シンクは以前の測定でQwen/Qwen3.8-27Bが特定したものを使い、フェーズ4（公開版の引数のまま。T33は互換名を使わない）以降をGPT-5.2で実行しています。[T33の記録](tee-flow-inspector-gpt52/pkcs11-T33/)

## 集計

保存した報告とベンチマークのラベルを照合します。解析器は実行しません。

```sh
uv run python results/score.py
```

報告とラベル位置が同じTA・同じファイルにあり、行範囲が重なれば「位置一致」と数えます。DITINGとTEE Flow Inspectorでは、報告の分類がラベルの分類と同じ場合を「位置・分類一致」とします。ORDERには対応する報告分類がないため、位置一致だけを数えます。[集計スクリプト](score.py) · [出力](summary/)

## 実行環境と導入

| 項目 | 静的解析 | TEE Flow Inspector |
| --- | --- | --- |
| ホスト | Kali GNU/Linux Rolling、x86-64 | 同左、Docker上 |
| 主なツール | CodeQL CLI 2.23.0（`cpp-all` 5.5.0、`cpp-queries` 1.4.7）、Semgrep 1.164.0、Python 3.11 | 公開版 `e06f0c6`、Python 3.12、libclang 18、OpenAI Python SDK 1.109.1 |
| TAのコンパイル | Debian clang 18.1.8（`--target=aarch64-none-elf`） | 同じ版のclangのヘッダ |
| OP-TEEのヘッダ | optee_os `496fea3` の196本、optee_client `8533e0e` の5本 | 同じ開発キットのヘッダ |

静的解析のツールは次の手順で導入しました。`$TOOLS` は任意のディレクトリです。

```sh
curl -fL -o codeql.tar.gz https://github.com/github/codeql-action/releases/download/codeql-bundle-v2.23.0/codeql-bundle-linux64.tar.gz
mkdir -p "$TOOLS/codeql" && tar -xf codeql.tar.gz -C "$TOOLS/codeql" --strip-components=1
uv venv --python 3.11 "$TOOLS/venv"
uv pip install --python "$TOOLS/venv/bin/python" -c results/diting-codeql-semgrep/scripts/semgrep-constraints.txt 'semgrep==1.164.0'
python3.11 results/diting-codeql-semgrep/scripts/headers.py "$TOOLS"
python3.11 results/diting-codeql-semgrep/scripts/fetch-rules.py "$TOOLS/semgrep-c.yaml"
git clone https://github.com/CharlieMCY/PartitioningE-in-TEE.git ../PartitioningE-in-TEE
git -C ../PartitioningE-in-TEE checkout cb72e8861809e70b7b820b0ece54d71f8ff93cd8
```

16個をまとめて実行するコマンドです。IDを付けると、そのTAだけを実行します。

```sh
TA_MEASURE_TOOLS="$TOOLS" python3.11 results/diting-codeql-semgrep/scripts/run.py "$WORK"        # 全16個
TA_MEASURE_TOOLS="$TOOLS" python3.11 results/diting-codeql-semgrep/scripts/run.py "$WORK" T18    # 1個
```
