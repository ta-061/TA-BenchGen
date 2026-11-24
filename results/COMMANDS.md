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

公開版は、次の1コマンドで全フェーズを順に実行します。

```sh
python3 src/main.py -p <プロジェクト> --prompt-version experiments/e12_general_sink_screening
```

今回も全フェーズを最初から最後まで続けて実行し、これを独立に3回行いました。1回分（15個のTAを並列に処理）のコマンドは次のとおりです。[実行スクリプト](tee-flow-inspector-gpt52/scripts/run-batch.sh) · [各フェーズを順に起動する処理](tee-flow-inspector-gpt52/scripts/batch.py)

```sh
./results/tee-flow-inspector-gpt52/scripts/run-batch.sh run-01
```

公開版との違いは、候補フローを生成するフェーズ4で、エントリポイントとシンクにGP 1.1互換名（`__GP11_` で始まる名前）を追加したことです。互換の設定でビルドされるTAでは関数名が変わり、公開版の指定では候補がほとんど生成されないためです。互換名を使わないTA（T31）は公開版の指定のままです。[候補生成のスクリプト](tee-flow-inspector-gpt52/scripts/phase4.py)

```sh
# 公開版
--sources TA_InvokeCommandEntryPoint,TA_OpenSessionEntryPoint

# 今回
--sources TA_InvokeCommandEntryPoint,TA_OpenSessionEntryPoint,__GP11_TA_InvokeCommandEntryPoint,__GP11_TA_OpenSessionEntryPoint
```

そのほかのプログラム、引数、プロンプト、規則は公開版と同じです。コンパイル情報（`compile_commands.json`）はあらかじめ用意したものを渡しました。[入力を用意するスクリプト](tee-flow-inspector-gpt52/scripts/stage_input.py)

モデルの設定は次のとおりです。[設定ファイル](tee-flow-inspector-gpt52/llm_config.json) · [要求と応答を記録するスクリプト](tee-flow-inspector-gpt52/scripts/invoke.py)

| 項目 | 値 |
| --- | --- |
| API | OpenAI Responses API |
| モデル | `gpt-5.2-2025-12-11` |
| temperature | 0.7 |
| reasoning effort | `none` |
| 出力上限 | 16,384トークン（上限で打ち切られた応答は32,768で再試行） |

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
