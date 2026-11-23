# TAの再実行コマンド

測定コミット `4fc3ae9` を含む `TA-BenchGen/` の直下で、実行したいTAのIDを1個渡す。たとえばECDSAの不備TAは次の1行で再実行できる。`results/` にいる場合は `./run.sh T18` でよい。[run.sh](run.sh)

```sh
./results/run.sh T18
```

対応する正常対照 `T05` と不備TA `T18` を順に実行するには、同じファイルを繰り返し呼ぶ。ほかのTAは一覧の `id` と `normal_id` で選べる。[TAと正常対照の対応一覧](2026-11-21/cases.csv)

```sh
for ta in T05 T18; do
  ./results/run.sh "$ta"
done
```

| 実行するマシン | 初回だけ実行するコマンド | 1回の `run.sh` で得られる結果 |
| --- | --- | --- |
| Mac（Apple Silicon、Python 3.11.10） | `./results/2026-11-21/replay/setup.sh` | DITING公開版、DITING 1.1互換型対応版、標準CodeQL、Semgrep |
| Kali（Docker、Clang 18、測定用の推論API） | `TA_LLM_BASE_URL=http://vllm.example:8000/v1 ./results/llm-e12-qwen/replay/setup.sh`（自分の推論先を指定） | TEE Flow Inspector＋Qwenのe12評価1回 |

どちらのマシンもBash・Git・`jq` を使う。`run.sh` は指定したIDの測定時の入力を復元する。毎回、先頭の `Output:` に新しい保存先を表示する。Macの原出力はその下の `static/jobs/<ID>/` と `gp11/jobs/<ID>/` に、Kaliの原出力とDockerの起動コマンドは `llm/` にある。

**測定当日**はPythonのバッチが各TAに同じ手順を適用した。上記の `run.sh` はその手順を後から1個ずつ再実行するための入口である。測定当日のコマンドと引数は元の記録で確認できる。[静的解析](2026-11-21/commands.jsonl) · [DITING互換版](diting-gp11/commands.jsonl) · [LLM](llm-e12-qwen/commands.jsonl)

<details>
<summary>原版READMEとの対応、測定当日の実引数、保存結果との照合を読む</summary>

測定時の入力はコミット `4fc3ae9` の35個のTAである．ここではECDSAの不備TA `T18` を例に，入力，実引数，原出力をたどる．`T18` の正常対照は `T05` である．採用した不備TA 15個と対応する正常対照9個を同じ測定記録から特定できる．論文本文の表7では，そのうち不備TA 15個の報告を保護位置・効果位置と照合している．[測定時の入力台帳](2026-11-21/inputs.json) · [対象の選択SQL](replay/paper_cohort.sql) · [本文表7と同条件の最終集計](outputs/label-comparison/paper-roles.csv)

[当日の実引数を表示](#records) ／ [固定入力を復元](#inputs) ／ [Macの静的解析](#static) ／ [DITING互換版](#gp11) ／ [KaliのLLM測定](#e12) ／ [論文の表を検算](#tables)

## 原版と今回の測定条件

| 手法 | 原版の入口 | 今回の実行と、その理由 |
| --- | --- | --- |
| DITING 公開版 | 例題ディレクトリで `codeql database create tee_example --language=c-cpp --command=make --overwrite`，続いて `python ../../real_world_analysis.py`．原版はLinaro GCCのARM向けクロスコンパイラを案内する． | TA-BenchGenの各入力を同じ条件で抽出するため，MacでTA側をLLVM Clang（`aarch64-none-elf`），付属ホスト側をApple Clangでオブジェクトまでコンパイルした．CLIは2.23.0，指定は `--language=cpp`．原版の7本のQLと後処理は固定コミットとSHA-256が一致する．依存指定 `cpp-all: "*"` は `5.5.0` に固定した．[原版README](https://github.com/CharlieMCY/PartitioningE-in-TEE/blob/cb72e8861809e70b7b820b0ece54d71f8ff93cd8/README.md#usage) · [原版パック](https://github.com/CharlieMCY/PartitioningE-in-TEE/blob/cb72e8861809e70b7b820b0ece54d71f8ff93cd8/query/qlpack.yml) · [実測版とハッシュ](2026-11-21/environment.json) |
| DITING 1.1互換型対応版 | 上と同じ後処理とクエリ群を基点とする追加実験． | OP-TEEの互換型 `__GP11_TEE_Param` も認識できるよう4本のQLの計6行を変更し，公開版測定で作成した各DBの複製を解析した．公開版と互換版の報告は別々に保存した．[全差分](diting-gp11/rules.patch) · [互換版ハッシュ](diting-gp11/environment.json) |
| 標準CodeQL | CodeQL CLIの `codeql database analyze` にDBとクエリスイートを渡す． | DITINGと同じ抽出済みDBに `cpp-security-extended.qls`（`cpp-queries` 1.4.7）を適用し，SARIFを保存した．一般のC/C++向けルールによる比較条件である．[CLI公式資料](https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-cli-manual/database-analyze) · [実引数](2026-11-21/commands.jsonl) |
| Semgrep CE | `semgrep scan --config <規則> <対象>` でソースを走査する． | 同じソースにCE 1.164.0と固定したC用2規則（`gets`・乱数デバイスの読み出し）を適用した．規則リビジョンは `YDTvRlQ` と `jQTzvry`．JSONには警告と構文解析診断が別々にある．[CLI公式資料](https://semgrep.dev/docs/cli-reference) · [規則ファイルのハッシュ](2026-11-21/environment.json) |
| TEE Flow Inspector＋Qwen | 原版の再測定例はDevContainer内の `python3 src/main.py -p benchmark/partitioningE/bad-partitioning --prompt-version experiments/e12_general_sink_screening`．例示モデルはOpenAIのGPT-5 mini．原版の `scripts/generate_paper_tables.py --check` は公開済み集計の検算である． | TA-BenchGenの入力を与え，固定版の `process_project` と同じe12プロンプトを使った．新規の読み取り専用入力には保存したコンパイル引数を渡し，クリーンアップとビルドを置き換えた．KaliのDockerからローカルのQwen3.8-27Bを呼び，各TAにつき1回を測定条件とした．[原版README](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/blob/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7/README.md#rerun-llm-analysis) · [入口の変更](llm-e12-qwen/replay/bootstrap.py) · [推論設定](llm-e12-qwen/profile.json) |

TA-BenchGen自身の `ta-bench generate`・`review` は，入力となるベンチマークの生成・レビューに使う．今回の測定では，固定コミットから台帳にあるソースだけを取り出し，解析後に位置ラベルと照合した．[TA-BenchGenのREADME](../README.md) · [集計と位置照合](README.md)

<a id="records"></a>

## 1．当日のコマンドを見る

**以下はすべて `TA-BenchGen/` 直下から始める．** `results/` にいる場合は最初に `cd ..` を実行する． 実引数の表示にはBashと `jq` を使う．解析ツールやGPUは不要である．`TA=T18` を変えれば，ほかの入力の引数も表示できる．

```bash
TA=T18
jq --arg ta "$TA" '.[$ta] | {source, gp_1_1, files}' results/2026-11-21/inputs.json
for log in results/{2026-11-21,diting-gp11}/commands.jsonl; do
  jq -r --arg ta "$TA" 'select(.id == $ta) |
    [.stage, .cwd, (.argv | @sh), (.exit_code // "計画")] | @tsv' "$log"
done
jq -r --arg ta "$TA" 'select(.id == $ta) |
  [.utc, .attempt, (.argv | @sh)] | @tsv' results/llm-e12-qwen/commands.jsonl
```

`argv` は引数配列，`cwd` は作業ディレクトリ．`@sh` は引数の境界を表示するための引用で，ログ内の `${WORK}` などは測定機のパスを表す記号である．静的解析の498行には113本のCファイルの `compile-plan` も含まれる．この113行はコンパイラに渡した引数の計画で，各コンパイルの個別終了コードを保存した行ではない．DB作成の終了コードと抽出されたソースの検査結果は別に確認できる．中断・再試行があった入力は最終採用分を記録している．[抽出結果の検算](2026-11-21/verification.json) · [再開記録](2026-11-21/checkpoint.json) · [先行試行を含む原出力の展開](README.md#raw-output)

**公開版DITINGの照合．** 7本のQLと後処理を，公開リポジトリの測定コミットとファイル単位で照合する．下の例は隣接する `PartitioningE-in-TEE` にコミットがあればそれを使い，手元にない場合はGitHubから一時領域に取得する．作業ツリーに互換版の変更があっても，`git archive` は指定コミットの内容を返す．`qlpack.yml` は依存を固定したため，下の8ファイルの比較から外し，4節で測定設定のハッシュを確認する．

```bash
(
  set -euo pipefail
  original=$(mktemp -d)
  meta=results/2026-11-21/environment.json
  rev=$(jq -er .diting.revision "$meta")
  upstream=../PartitioningE-in-TEE
  if ! git -C "$upstream" cat-file -e "$rev^{commit}" 2>/dev/null; then
    upstream="$original/upstream"
    git init -q "$upstream"
    git -C "$upstream" fetch -q --depth=1 https://github.com/CharlieMCY/PartitioningE-in-TEE.git "$rev"
  fi
  git -C "$upstream" archive "$rev" \
    query real_world_analysis.py | tar -xf - -C "$original"
  jq -r '.diting.files_sha256 | to_entries[] | select(.key != "qlpack.yml") |
    "\(.value)  \(if .key == "real_world_analysis.py" then .key else "query/"+.key end)"' \
    "$meta" | (cd "$original" && shasum -a 256 -c -)
)
```

<a id="inputs"></a>

## 2．測定時の入力を復元する（Mac・Kali共通）

以下の再実行例では同じBashセッションを使う．Macはこの節から3・4節へ，Kaliはこの節から5節へ進む．`git archive` で測定時のツリーを一時領域に復元し，解析入力には台帳記載のファイルだけをコピーする．これにより，現在は整理・移動されているTAにも当時のIDを使える．

```bash
set -euo pipefail
REPO=$(pwd -P)
BASE="$REPO/results/2026-11-21"
TA=T18
REV=$(jq -r .git_commit "$BASE/environment.json")
test "$(git rev-parse "$REV:benchmark")" = "$(jq -r .benchmark_tree "$BASE/environment.json")"
WORK=$(mktemp -d)
WORK=$(cd "$WORK" && pwd -P)
git -C "$REPO" archive "$REV" benchmark | tar -xf - -C "$WORK"
SRC="$WORK/sources/$TA"
JOB="$WORK/jobs/$TA"
mkdir -p "$SRC" "$JOB/out" "$JOB/objects"
SOURCE=$(jq -er --arg ta "$TA" '.[$ta].source' "$BASE/inputs.json")
while IFS= read -r file; do
  mkdir -p "$SRC/$(dirname "$file")"
  cp "$WORK/benchmark/$SOURCE/$file" "$SRC/$file"
done < <(jq -r --arg ta "$TA" '.[$ta].files | keys[]' "$BASE/inputs.json")
jq -r --arg ta "$TA" '.[$ta].files | to_entries[] | "\(.value)  \(.key)"' \
  "$BASE/inputs.json" > "$WORK/input.sha256"
(cd "$SRC" && if command -v sha256sum >/dev/null; then
  sha256sum -c "$WORK/input.sha256"
else
  shasum -a 256 -c "$WORK/input.sha256"
fi)
printf '作業領域 %s\n' "$WORK"
```

<a id="static"></a>

## 3．Macで公開版DITING・標準CodeQL・Semgrepを実行する

測定機はApple SiliconのMacで，CodeQLのmacOS x86-64バンドルはRosetta経由で動作した．導入済みの各ツールの版とハッシュは記録されている．初回インストールの端末入力は保存されていないため，次の `setup.sh` は同じ配布物を用意する再構成手順である．Pythonは3.11.10を指定する．[導入用シェル](2026-11-21/replay/setup.sh) · [環境と配布元](2026-11-21/REPRODUCE.md#導入方法)

```bash
PYTHON=$(command -v "${TA_PYTHON:-python3.11}")
test "$("$PYTHON" --version)" = 'Python 3.11.10'
TA_PYTHON="$PYTHON" ./results/2026-11-21/replay/setup.sh
```

当日の `deps/` と `query/` の配置を新しい `WORK` 内に作る．キャッシュもここに作成する．当日の所要時間には既存の共有キャッシュが影響する．

```bash
TOOLS=${TA_MEASURE_TOOLS:-"${XDG_DATA_HOME:-$HOME/.local/share}/ta-benchgen-static/2026-11-21"}
mkdir -p "$WORK/deps/query-cache" "$WORK/bin" "$WORK/query"
for part in codeql llvm devkit client diting; do
  ln -s "$TOOLS/$part" "$WORK/deps/$part"
done
ln -s "$TOOLS/venv/bin" "$WORK/deps/sem-bin"
ln -s "$TOOLS/semgrep-c.yaml" "$WORK/deps/rules.yaml"
cp "$BASE/build-config.txt" "$WORK/deps/conf.h"
printf '#undef CFG_TEE_TA_LOG_LEVEL\n#define CFG_TEE_TA_LOG_LEVEL 4\n' > "$WORK/deps/log-level.h"
cp "$TOOLS/diting/query/"*.ql "$WORK/query/"
printf 'name: getting-started/tee-bad-partitioning\nversion: 0.0.0\ndependencies:\n  codeql/cpp-all: 5.5.0\n' > "$WORK/query/qlpack.yml"
cp "$BASE/replay/compile.py" "$WORK/compile.py"
cp "$BASE/replay/trace-codeql.py" "$WORK/bin/codeql"
chmod u+x "$WORK/bin/codeql"
CLI="$WORK/deps/codeql/codeql"
export CODEQL_DIST
CODEQL_DIST=$(cd "$WORK/deps/codeql" && pwd -P)
limits=("--common-caches=$WORK/deps/query-cache" --threads=2 --ram=2048)
```

**Semgrep．** 作業ディレクトリは台帳から復元した `SRC`．指定した2規則で走査し，`results` と `errors` の両方を保存する．

```bash
(
  cd "$SRC"
  unset SEMGREP_APP_TOKEN
  export PATH="$WORK/deps/sem-bin:$PATH" SEMGREP_SETTINGS_FILE="$JOB/semgrep-settings.yml"
  export SEMGREP_SEND_METRICS=off SEMGREP_ENABLE_VERSION_CHECK=0
  "$WORK/deps/sem-bin/semgrep" scan --config "$WORK/deps/rules.yaml" \
    --metrics=off --disable-version-check --oss-only --no-git-ignore --no-rewrite-rule-ids \
    --jobs=2 --json --output "$JOB/semgrep.json" .
)
```

**CodeQLのDB作成．** `compile.py` の仕事は `compile.json` の各引数配列を順に実行することだけである．下の `jq` で当日のコンパイラ引数を復元・表示してからDBを作る．T18ではTA側の `ta/ecdsa_ta.c` は `--target=aarch64-none-elf` と `-D__OPTEE_CORE_API_COMPAT_1_1=1` 付きで，ホスト側の `host/main.c` は `/usr/bin/clang` でそれぞれ `-c` コンパイルされる．[ビルド用ドライバ](2026-11-21/replay/compile.py) · [全TAのコンパイル引数](2026-11-21/commands.jsonl)

```bash
jq -s --arg ta "$TA" --arg work "$WORK" \
  '[.[] | select(.id == $ta and .stage == "compile-plan") |
    .argv | map(split("${WORK}") | join($work))]' "$BASE/commands.jsonl" > "$JOB/compile.json"
jq -r '.[] | @sh' "$JOB/compile.json"
(
  cd "$SRC"
  "$CLI" database create "$JOB/tee_example" --language=cpp --source-root "$SRC" \
    --command "\"$PYTHON\" \"$WORK/compile.py\" \"$JOB/compile.json\"" "${limits[@]}"
)
```

**DITINGの公開版と補助クエリ．** 後処理は `JOB` から起動する．後処理自身が `host`，`switch`，`arrayaccess`，`ifstmt`，`dataflow`，`memory` の6本を順に呼ぶ．PATH上の `codeql` は実行ファイルへキャッシュ・スレッド数・メモリの指定を加え，各呼び出しと終了コードを記録する．7本目の `memflow` は別コマンドで，その結果は3分類の警告数に加算しない．[原版の後処理](https://github.com/CharlieMCY/PartitioningE-in-TEE/blob/cb72e8861809e70b7b820b0ece54d71f8ff93cd8/real_world_analysis.py) · [記録用ラッパー](2026-11-21/replay/trace-codeql.py)

```bash
(
  cd "$JOB"
  export PATH="$WORK/bin:$PATH" DITING_CLI="$CLI" DITING_CACHE="$WORK/deps/query-cache"
  export DITING_TRACE="$JOB/query-calls.jsonl"
  "$PYTHON" "$WORK/deps/diting/real_world_analysis.py" > diting.txt
  "$CLI" query run "$WORK/query/memflow.ql" --database "$JOB/tee_example" \
    "${limits[@]}" > out/memflow.out
)
jq -r '[.argv[3], .exit_code] | @tsv' "$JOB/query-calls.jsonl"
```

**標準CodeQL．** 同じ `tee_example` を解析し，結果をSARIFで出力する．当日の保存版はこのSARIFをgzip圧縮したものである．

```bash
SUITE="$WORK/deps/codeql/qlpacks/codeql/cpp-queries/1.4.7/codeql-suites/cpp-security-extended.qls"
(cd "$SRC" && "$CLI" database analyze "$JOB/tee_example" "$SUITE" \
  --format=sarif-latest --output "$JOB/codeql.sarif" "${limits[@]}")
```

<a id="gp11"></a>

## 4．MacでDITINGの互換型対応版を実行する

3節で作ったDBと公開版クエリを別のディレクトリにコピーし，保存したパッチをコピー側だけに適用する．変更は `dataflow.ql`・`arrayaccess.ql`・`memflow.ql` の各1行と `memory.ql` の3行である．下のハッシュ検査は，変更後の全QL，依存指定と後処理を測定記録と比較する．[当日の280レコード](diting-gp11/commands.jsonl) · [DB複製と検査の実装](diting-gp11/run.py)

```bash
GP="$WORK/gp11"
GJOB="$GP/jobs/$TA"
mkdir -p "$GJOB/out"
cp -R "$WORK/query" "$GP/query"
cp -R "$JOB/tee_example" "$GJOB/tee_example"
cp "$WORK/deps/diting/real_world_analysis.py" "$GP/"
(cd "$GP" && git apply --check "$REPO/results/diting-gp11/rules.patch" &&
  git apply "$REPO/results/diting-gp11/rules.patch")
jq -r '.sha256 | to_entries[] |
  "\(.value)  \(if .key == "real_world_analysis.py" then .key else "query/"+.key end)"' \
  "$REPO/results/diting-gp11/environment.json" | (cd "$GP" && shasum -a 256 -c -)
(
  cd "$GJOB"
  export PATH="$WORK/bin:$PATH" DITING_CLI="$CLI" DITING_CACHE="$WORK/deps/query-cache"
  export DITING_TRACE="$GJOB/queries.jsonl"
  "$PYTHON" "$GP/real_world_analysis.py" > diting.txt
  codeql query run ../../query/memflow.ql --database=tee_example > out/memflow.out
)
```

再実行と保存済み出力は次のように比較できる．DITINGの位置文字列からは作業領域の絶対パスの違いだけを取り除く．CodeQLは規則・メッセージ・位置，Semgrepは報告・診断・走査ファイルを比較する．

```bash
diting_lines() { sed -E 's@file://[^[:space:],]*\/sources/@file://sources/@g' "$1"; }
diff -u <(diting_lines "$BASE/diting/$TA.txt") <(diting_lines "$JOB/diting.txt")
diff -u <(diting_lines "$REPO/results/diting-gp11/diting/$TA.txt") <(diting_lines "$GJOB/diting.txt")
sarif_rows() { jq -S '[.runs[].results[] | {ruleId, message, locations}] | sort'; }
diff -u <(gzip -dc "$BASE/codeql/$TA.sarif.gz" | sarif_rows) <(sarif_rows < "$JOB/codeql.sarif")
semgrep_rows() { jq -S '{results, errors, scanned:(.paths.scanned | sort)}' "$1"; }
diff -u <(semgrep_rows "$BASE/semgrep/$TA.json") <(semgrep_rows "$JOB/semgrep.json")
```

2026年11月23日，上記の手順をT18で再実行した．共通の `run.sh T18` でも別々の出力先に2回実行し，以下の結果を両方で確認した．公開版の警告は0件，互換版は5件（UDO 3，IVW 2）で，両版とも作業パスを除いた警告の内容・位置が保存結果と一致した．標準CodeQLは報告0件，Semgrepは4ファイルを走査して報告0件・診断0件で，上記の比較項目が一致した．[照合した原出力の展開](README.md#raw-output)

<a id="e12"></a>

## 5．KaliでTEE Flow InspectorとQwenを実行する

**測定当日の起動．** Macからの `ssh kali ./ta-bench-e12` がKaliのユーザーサービスに接続し，測定用コンテナ `ta-bench-llm:e12` の `/work` で `python /ops/worker.py` を起動した．T18の起動時には `IISA_LOCAL_PROFILE=/ops/profile.json` を読み，モデル呼び出しの記録先を `/work/calls/T18/attempt-01` に指定した．ワーカーが発行したコマンドを下に示す．PKCS#11のT09を処理している間にT33を先行起動した．バッチがT33に到達した際は先行試行の結果を取り込む設定である．[Dockerの全マウントと起動コマンド](llm-e12-qwen/replay/batch-command.sh) · [TA単位の起動記録](llm-e12-qwen/commands.jsonl) · [T33の先行起動](llm-e12-qwen/parallel-plan.json)

```sh
/usr/local/bin/python /ops/bootstrap.py /workspace /inputs/T18 \
  /results/cases/T18/attempt-01/outputs /support/devkit
```

当日のコンテナではBearを使えないため，`bootstrap.py` は `ensure_ta_db` に準備済みの `ta/compile_commands.json` を返させた．新規入力領域でのクリーンアップを省き，devkit・出力先・e12を指定して原版の `process_project` を呼ぶ．関数の分類は同じPythonプロセス内でlibclangを使う．T18では原版のパーサーが `--target=armv7a-none-eabi` を補ってTA側のCファイル1本を読み，診断エラーは0件だった．[正規化前の引数](llm-e12-qwen/replay/compile-commands.json) · [原版のターゲット指定](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/blob/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7/src/parsing/parse_utils.py#L52-L59) · [入力別のパース結果](llm-e12-qwen/parse.json)

以下はT18について，固定版の呼び出し元と測定環境（`TA_DEV_KIT_DIR=/support/devkit`）から復元した子コマンドである．各子プロセスの作業ディレクトリは `/inputs/T18/ta`．ログのphase 4の `...` とphase 6のスクリプト名の二重表示は表示文に由来する．[原版の子プロセス呼び出し](https://github.com/ta-061/tee-bad-partitioning-llm-artifact/blob/e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7/src/main.py#L354-L432) · [ワーカーの記録ハッシュ](llm-e12-qwen/parallel-plan.json) · [T18の実行ログの展開](README.md#raw-output)

```sh
cd /inputs/T18/ta
P=/usr/local/bin/python
R=/results/cases/T18/attempt-01/outputs/results_1
E12=experiments/e12_general_sink_screening
"$P" /workspace/src/identify_sinks/identify_sinks.py -i "$R/ta_phase12.json" -o "$R/ta_sinks.json" \
  --llm-only --prompt-version "$E12"
"$P" /workspace/src/identify_flows/generate_candidate_flows.py --compile-db /inputs/T18/ta/compile_commands.json \
  --sinks "$R/ta_sinks.json" --phase12 "$R/ta_phase12.json" \
  --sources TA_InvokeCommandEntryPoint,TA_OpenSessionEntryPoint --output "$R/ta_candidate_flows.json" --devkit /support/devkit
"$P" /workspace/src/analyze_vulnerabilities/taint_analyzer.py --flows "$R/ta_candidate_flows.json" \
  --phase12 "$R/ta_phase12.json" --output "$R/ta_vulnerabilities.json" --prompt-version "$E12"
"$P" /workspace/src/report/generate_report.py --sinks "$R/ta_sinks.json" --flows "$R/ta_candidate_flows.json" \
  --vulnerabilities "$R/ta_vulnerabilities.json" --phase12 "$R/ta_phase12.json" \
  --project-name T18 --output "$R/ta_vulnerability_report.html"
```

**別作業領域での単体再実行．** Kali側で2節を実行してから以下を使う．Docker，Clang 18のリソースヘッダ，保存設定のローカル推論APIへの接続が必要になる．再構成イメージ `:e12-replay` を使い，保存測定の `:e12` と区別する．推論時はプロファイルとフックを使い，`temperature=0.7`，`top_p=0.8`，thinking無効などの条件を適用する．1入力1回であり，原版短報の5回多数決はこの測定の集計に使用しない．[導入用シェル](llm-e12-qwen/replay/setup.sh) · [コンテナの依存関係](llm-e12-qwen/replay/Dockerfile) · [推論パラメータ](llm-e12-qwen/profile.json) · [応答・再試行を記録するフック](llm-e12-qwen/replay/hook/sitecustomize.py)

```bash
LLM="$REPO/results/llm-e12-qwen"
LTOOLS=${TA_LLM_TOOLS:-"${XDG_DATA_HOME:-$HOME/.local/share}/ta-benchgen-e12"}
"$LLM/replay/setup.sh"
jq -e --arg ta "$TA" '.[$ta]' "$LLM/replay/compile-commands.json" > "$SRC/ta/compile_commands.json"
ATTEMPT="cases/$TA/attempt-01/outputs"
mkdir -p "$WORK/e12/work/calls" "$WORK/e12/results/$ATTEMPT"
jq --slurpfile config "$LTOOLS/artifact/src/llm_settings/llm_config.json" '
  .base_url = $config[0].providers.local.base_url' "$LLM/profile.json" > "$WORK/e12/profile.json"
docker run --rm --pull never --init --user "$(id -u):$(id -g)" \
  -v "$LTOOLS/artifact/src:/workspace/src:ro" -v "$LTOOLS/artifact/prompts:/workspace/prompts:ro" \
  -v "$LTOOLS/artifact/rules:/workspace/rules:ro" -v "$LLM/replay:/ops:ro" \
  -v "$LTOOLS/support:/support:ro" -v /usr/lib/llvm-18/lib/clang/18:/support/clang:ro \
  -v "$WORK/sources:/inputs:ro" -v "$WORK/e12/work:/work" -v "$WORK/e12/results:/results" \
  -v "$WORK/e12/profile.json:/settings/profile.json:ro" -w /work \
  -e PYTHONPATH=/ops/hook:/workspace/src -e IISA_LOCAL_PROFILE=/settings/profile.json \
  -e IISA_LOCAL_PRIVATE=/work/calls -e TA_DEV_KIT_DIR=/support/devkit \
  ta-bench-llm:e12-replay /usr/local/bin/python /ops/bootstrap.py /workspace "/inputs/$TA" \
  "/results/$ATTEMPT" /support/devkit > "$WORK/e12/run.log" 2>&1
jq '{total_vulnerability_lines}' "$WORK/e12/results/$ATTEMPT/results_1/ta_vulnerabilities.json"
```

単体再実行の `run.log` とJSONは `$WORK/e12/` にできる．当日のバッチでは別に完了検査を行った．T18の保存記録では終了コード0，受理されたモデル呼び出し17回，候補フロー0件，指摘0件だった．共通の `run.sh` ではT05・T07・T18の入力ハッシュとコンテナ内の解析コマンドを当日の記録と照合した．この確認はDocker起動直前までで，モデル推論の再測定は含まない．当日の結果は次のコマンドで確認できる．[T18の完了記録](llm-e12-qwen/cases/T18/attempt-01/run.json) · [全TAの状態](llm-e12-qwen/cases.csv)

```bash
jq '{id, attempt, exit_code, model, prompt, flows, findings, accepted_calls}' \
  results/llm-e12-qwen/cases/T18/attempt-01/run.json
jq '{passed, expected_flow_count, recorded_flow_count}' \
  results/llm-e12-qwen/cases/T18/attempt-01/coverage.json
jq '{updated_utc, counts, current, also_running}' results/llm-e12-qwen/status.json
```

<a id="tables"></a>

## 6．保存した結果から比較表を再生成する

[原出力を展開](README.md#raw-output)し、PyYAMLを含むTA-BenchGenのPython環境で次を実行すると、全35個の原出力からSQLite・手法別CSV・TA別CSVを再生成できる。Excelも出力する場合は、`@oai/artifact-tool` を含むCodexのNodeランタイムを用意し、`--data-only` を外す。[比較表の生成スクリプト](replay/build_label_report.py)

```bash
python3 results/replay/build_label_report.py --data-only
```

次の2つのCSVは、同じSQLiteを読み取り専用で開いて出力する。1つ目は本文表7と同じ採用条件で、不備TA 15個について保護位置と効果位置を別々に数える。11月23日の最終集計にはTEE Flow Inspectorの15個すべての出力を含む。[最終集計](outputs/label-comparison/paper-roles.csv) · [保護位置・効果位置の集計SQL](replay/detector_roles.sql)

```bash
db=results/outputs/label-comparison/benchmark-results.db
sqlite3 -readonly -csv -header -cmd '.read results/replay/paper_cohort.sql' \
  -cmd '.read results/replay/detector_roles.sql' "$db" \
  'SELECT r.* FROM paper_detector_summary r JOIN method USING (method_id) ORDER BY sort_order' \
  > results/outputs/label-comparison/paper-roles.csv
```

2つ目はTEE Flow Inspectorの報告を、公開時または人手承認時の各ラベル位置と照合した結果である。現行の比較に使う人手承認位置は `scope = 'current'` かつ `is_approved = 1` で選べる。[LLMの位置別CSV](llm-e12-qwen/locations.csv)

```bash
db=results/outputs/label-comparison/benchmark-results.db
sqlite3 -readonly -csv -header "$db" \
  "SELECT r.ta_id AS id, t.scope, t.review, r.defect_id AS defect, r.class_id AS class,
          r.decision, r.role, r.path, r.first_line, r.last_line, r.is_public, r.is_approved,
          r.hits, r.same AS same_class
   FROM v_target_result r JOIN ta t USING (ta_id)
   WHERE r.method_id = 'TFI-Qwen'
   ORDER BY id, defect, r.role, r.path, r.first_line, r.last_line" \
  > results/llm-e12-qwen/locations.csv
```

不備TAと対応する正常対照の計24個について，両群への報告数と不備単位の位置・分類一致を調べる場合は，次の集計を使う．[24個の選択と照合条件](replay/paper_cohort.sql) · [SQLiteの構成](README.md)

```bash
sqlite3 -readonly -header -column -cmd '.read results/replay/paper_cohort.sql' \
  results/outputs/label-comparison/benchmark-results.db \
  'SELECT method_id, tas_with_output, control_reports, defective_reports,
          location_matches, observed_labels, location_class_matches, comparable_labels
   FROM paper_method_summary ORDER BY method_id'
```

<a id="pinned-replay"></a>

## 付録．既存の再実行ドライバに測定時の35個を渡す

静的解析用の `run.py` は隣接する `benchmark/` を列挙した後，入力台帳全体が当日と一致するかを確認する．LLM用の `run-case.py` は台帳にある当日の相対パスを読む．2節で復元した35個のTAの全232ファイルについて，SHA-256が静的解析とLLMの両方の入力台帳に一致することを確認した．`$WORK/benchmark` の横にドライバと設定を配置すれば，現在のベンチマークを切り替えずに，旧正常対照や移動したケースも再実行できる．以下は2節に続けて使う．[静的解析ドライバ](2026-11-21/replay/run.py) · [LLM単体ドライバ](llm-e12-qwen/replay/run-case.py)

```bash
for dataset in 2026-11-21 llm-e12-qwen; do
  base="$WORK/results/$dataset"
  mkdir -p "$base"
  cp -R "$REPO/results/$dataset/replay" "$base/"
  cp "$REPO/results/$dataset/inputs.json" "$base/"
done
cp "$BASE/environment.json" "$BASE/build-config.txt" "$WORK/results/2026-11-21/"
cp "$REPO/results/llm-e12-qwen/profile.json" "$WORK/results/llm-e12-qwen/"
```

Macでは3節の導入後に次を実行する．`T07` を `all` に置き換えると35個を処理する．`--work` に指定する出力先は新規または空のディレクトリを使う．

```bash
"${TA_PYTHON:-python3.11}" "$WORK/results/2026-11-21/replay/run.py" T07 --work "$WORK/static-replay"
```

Kaliでは5節の導入後に次を実行する．今回のコンテナ起動引数は `$WORK/llm-replay/command.txt` にも出力される．

```bash
python3 "$WORK/results/llm-e12-qwen/replay/run-case.py" T07 --work "$WORK/llm-replay"
```

</details>
