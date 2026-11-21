# 本番実験の手順と記録

対象は `config/requests.production.yaml`。目標は18ケース（単体15件・複合3件）、上限は54試行。改修中の試行は開発記録として扱い、本番の実績は本番の実行ID単位で集計する。要求の内訳と選定理由は [README](../README.md#本番用の収集要求) にある。

コマンドはすべてLinux amd64のリポジトリ直下で、同じ端末から実行する（`TA_BENCH_IMAGE` を引き継ぐため）。

## 1. 環境を作り直す

Python環境は `uv.lock` から作る。

```sh
uv sync --locked --extra dev
uv run pytest -q
```

実行イメージはキャッシュを使わずに3段階で作る。以前のイメージは比較用に別名で残す。

```sh
for t in 4.4.0 4.4.0-events 4.4.0-rpmb; do
  docker tag ta-bench-runtime:$t ta-bench-runtime:$t-old-$(date +%Y%m%d)
done

mkdir -p work
docker build --no-cache --platform linux/amd64 -f docker/Dockerfile -t ta-bench-runtime:4.4.0 . > work/build-base.log 2>&1; echo "exit=$?"
docker build --no-cache --pull=false -f docker/Dockerfile.runtime -t ta-bench-runtime:4.4.0-events . > work/build-events.log 2>&1; echo "exit=$?"
docker build --no-cache --pull=false -f docker/Dockerfile.rpmb -t ta-bench-runtime:4.4.0-rpmb . > work/build-rpmb.log 2>&1; echo "exit=$?"

export TA_BENCH_IMAGE=$(docker image inspect --format '{{.Id}}' ta-bench-runtime:4.4.0-rpmb)
echo "$TA_BENCH_IMAGE"
docker image inspect ta-bench-runtime:4.4.0-rpmb --format '{{json .Config.Labels}}'
```

- 3つの `exit=` がすべて `0` であることを確認する。3つのビルドは独立して実行されるため、前の段が失敗すると、後の段は古いタグの上に作られる。1つでも失敗したら、その後のイメージは使わない。
- ラベルに `runner_version` 4.3.1以上と `shared_memory_events_v1 output_reference_v1 rpmb_storage_v1` が含まれることを確認する。
- 配布パッケージの取得内容が変わるため、作り直したイメージのIDは以前と一致しない。実験ではタグではなくこのIDを記録する。

## 2. 実行前に確認する

```sh
ta_bench_check=$(mktemp -d work/qemu-acceptance.XXXXXXXX)
TA_BENCH_TEST_IMAGE="$TA_BENCH_IMAGE" uv run pytest -v -m qemu \
  --basetemp "$ta_bench_check/cases" --junitxml "$ta_bench_check/pytest.xml"
```

`benchmark/defective/` が空であることを確認する。以前のケースが残っていると、生成時に同じTAの既存ケースとしてAIに渡され、重複も拒否されるため、本番の結果に影響する。以前のケースは `work/archive/` に移す。

```sh
ls benchmark/defective | wc -l   # 0
```

## 3. 実験条件を残す

開始時に、入力とコードの版を記録する。

```sh
record=$(mktemp -d work/experiment-record.XXXXXXXX)
git rev-parse HEAD > "$record/commit.txt"
git diff --binary HEAD > "$record/tracked.patch"
cp --parents config/requests.production.yaml config/classes.yaml uv.lock "$record/"
sha256sum config/requests.production.yaml config/classes.yaml uv.lock > "$record/inputs.sha256"
echo "$TA_BENCH_IMAGE" > "$record/image.txt"
{ uv run python --version; uv --version; docker version --format 'Docker {{.Server.Version}}'; } > "$record/versions.txt"
```

## 4. 本番を実行する

作業先は実行ごとに新しくする。通常入力は作業先の `normal-inputs/` に蓄積され、後の候補のR1にも使われるため、既存の作業先を使うと以前の実験の通常入力を引き継ぐ。機械合格したケースは標準の保存先 `benchmark/defective/` に入る。

```sh
uv run ta-bench generate --request config/requests.production.yaml \
  --work-dir work/production-$(date +%Y%m%d)
```

`attempt 1/3` の3は要求ごとの試行上限。合格するとその要求を終えて次へ進み、3回とも不合格なら未達として記録する。終了時に集計がJSONで表示され、未達があると終了コードは2になる。中断した場合は、表示された実行IDで再開する。

```sh
uv run ta-bench generate --resume run_... --work-dir work/production-YYYYMMDD
```

## 5. 終了後に確認・集計する

保存されたケースを同じイメージで再実行し、判定が再現することを確認する。`exit=0` なら全件が再び機械合格した。

```sh
uv run ta-bench review --dir benchmark/ --reverify; echo "exit=$?"
```

今回の実行IDの最終 `state.json` を記録先に保管する。モデル設定、実行イメージ、正常TAと分類定義のハッシュを後から照合できる。本番の試行数・保存数・未達数はこのファイルから集計する。

```sh
cp work/production-YYYYMMDD/runs/run_.../state.json "$record/state.json"
jq '.run_id as $id | .requests | {
  run_id: $id,
  attempts: (map(.attempts | length) | add),
  saved: (map(.saved | length) | add),
  unmet: (map(.count - (.saved | length)) | add)
}' "$record/state.json"
```

機械合格したケースは `unreviewed` のまま保存される。評価に使う前に、レビュー画面で不備ごとに分類・位置・挙動を確認して承認する。

```sh
uv run ta-bench review
```

## 実施記録

### 2026-11-19（実行中）

| 項目 | 値 |
| --- | --- |
| 実行ID | `run_9eae03fff4bf4eaa`（開始 2026-11-19 10:44 JST） |
| 作業先 | `work/production-20261119/` |
| コード | `85eff29`（`src/` は未変更。文書のみ未コミットの変更あり） |
| 実行イメージ | `sha256:e1b5023b7180eab9e5e158b7289699a503fecfcfd3a21481fac2293b755ead1e`（runner 4.3.1、RPMB対応、2026-11-19 に `--no-cache` で3段階とも再構築） |
| 生成モデル | `claude-sonnet-5-5`（`config/models.yaml` の登録 `claude`） |
| 環境 | Python 3.12.13、uv 0.13.5、Docker Engine 29.8.1、Kali Linux amd64 |
| 開始時の状態 | `benchmark/defective/` は空。作業先は新規で、通常入力の蓄積なし |
| 以前のケース | 2026-11-18の実行（`run_b11f1e9d6c1c418b`、17件保存）は `work/archive/defective-20261119-091603/` に退避。本番の集計には含めない |
| 結果 | 未記入（終了後に保存数・未達数・再検証結果を記入） |
