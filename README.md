# TA-BenchGen

TA-BenchGen（Trusted Application Benchmark Generator）は、OP-TEEのTrusted Application（TA）を対象に、設計不備の検出手法を評価するためのベンチマークを作るツールです。正常対照に設計不備を導入して不備TAを作り、両版に同じ入力を与えて戻り値や出力の差を記録します。不備の分類と検出位置は、人がソースと観測結果を照合して確認します。

同梱のソース、差分、位置ラベル、検証記録はGitHub上で直接参照できます。[ベンチマークの構成と読み方](benchmark/README.md)

## レビュー画面を開く

Python 3.11以上と [uv](https://docs.astral.sh/uv/) を用意し、リポジトリのルートで実行します。保存済みケースの閲覧はPython環境だけで利用できます。

```sh
uv sync --locked
uv run ta-bench review --dir benchmark
```

ブラウザで `http://127.0.0.1:8765` を開きます。レビューに対応するケースでは、左右に並んだソースから検出位置に移動し、不備ごとに分類・位置・挙動を確認して承認できます。画面右上で日本語と英語を切り替えられます。

検出器に渡すソースだけを書き出すには、`ta-bench review --export-blind` に新しい出力先を指定します。既定の対象は、全不備の承認を照合できるケースです。正解との対応表は `work/blind-mappings/` に保存されます。

## ケースを生成する

生成にはDockerとOP-TEE/QEMUの実行イメージが必要です。イメージをビルドして `TA_BENCH_IMAGE` を設定します。[実行イメージの準備](docker/README.md)

| 指定するもの | `ta-bench generate` のオプション |
| --- | --- |
| 正常対照と不備の内訳 | `--ta` と `--defects`。複数の要求は `--request` でまとめて指定できます。[要求ファイルの例](config/requests.example.yaml) |
| 手書きの候補 | `--candidate` で候補JSONを指定します。[候補の形式](docs/candidate-format.md) |
| モデルによる候補生成 | `--use` で登録名を選びます。モデルと接続先は [config/models.yaml](config/models.yaml)、APIキーは登録に対応する環境変数に設定します。 |

Linux amd64上で検証を通過したケースは `benchmark/defective/`、試行のログは `work/` に保存されます。コマンドの全オプションはヘルプで確認できます。

```sh
uv run ta-bench generate --help
uv run ta-bench review --help
```

## 開発用テスト

QEMUを使わないテスト一式は、Cコンパイラを備えたLinux amd64環境で実行します。レビュー画面のテストだけを実行する場合は `uv run pytest tests/test_review.py` を使えます。

```sh
uv sync --locked --extra dev
uv run pytest -m 'not qemu'
```

QEMU統合テスト用の実行イメージは `TA_BENCH_TEST_IMAGE` で指定します。
