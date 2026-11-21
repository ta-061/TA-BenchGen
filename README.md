# TA Benchmark Generator

OP-TEEの正常TAに小さな設計不備を挿入し、同じ入力に対する**実測の挙動差**を検証する研究用ツールです。コマンドは `ta-bench generate` と `ta-bench review` の2種類です。分類・検出位置・差の意味は、人がレビュー画面で確認します。

仕様書は [docs/spec-v4.md](docs/spec-v4.md)、開発端末間の引継ぎは [docs/development-handoff.md](docs/development-handoff.md) にあります。
実測した最小構成の到達状況と検証証跡は [docs/development-status.md](docs/development-status.md) にまとめています。
本番実験の環境の作り直し・実行・集計の手順と実施記録は [docs/production-record.md](docs/production-record.md) にあります。

## セットアップ

Python 3.11以上、[uv](https://docs.astral.sh/uv/)、Docker Engineが必要です。公開用の検証結果はLinux amd64上で作成します。

```sh
uv sync --extra dev
uv run ta-bench --help
uv run pytest -q
```

Python依存は `uv.lock` に固定しています。以降のコマンドはリポジトリ直下で実行してください。仮想環境を有効化した場合は `uv run` を省略できます。

## OP-TEE実行イメージ

```sh
docker build --platform linux/amd64 -f docker/Dockerfile -t ta-bench-runtime:4.4.0 .
export TA_BENCH_IMAGE=$(docker image inspect --format '{{.Id}}' ta-bench-runtime:4.4.0)
```

初回はOP-TEE、QEMU、Linux、ツールチェーンのダウンロードとビルドに時間とディスク容量が必要です。ベースイメージのダイジェストとOP-TEEマニフェストのコミットをDockerfileに固定しています。公開レジストリへの配布はまだ行っていません。イメージを配布する場合は `registry/repository@sha256:...` も指定できます。`verification.json` に使用した不変イメージ識別子を記録します。

以前の `ta-bench-runtime:4.4.0` を構築済みなら、共通実行器だけを更新できます。
呼出し途中の共有入力変更には、この更新後のイメージが必要です。

```sh
docker build --pull=false -f docker/Dockerfile.runtime -t ta-bench-runtime:4.4.0-events .
export TA_BENCH_IMAGE=$(docker image inspect --format '{{.Id}}' ta-bench-runtime:4.4.0-events)
```

本番要求に含めたAVBのrollback indexには、RPMBストレージを有効にした追加イメージが必要です。上の共通実行器の更新後に構築します。

```sh
docker build --pull=false -f docker/Dockerfile.rpmb -t ta-bench-runtime:4.4.0-rpmb .
export TA_BENCH_IMAGE=$(docker image inspect --format '{{.Id}}' ta-bench-runtime:4.4.0-rpmb)
```

本番実験では、この3段階をキャッシュを使わずに続けて構築します（[手順](docs/production-record.md#1-環境を作り直す)）。

このイメージはQEMU内のRPMBエミュレータを使用し、入力列ごとに保存状態を初期化します。同じ入力列内での保護状態の更新を検証するもので、実機の耐リプレイ性や再起動をまたぐ永続性の評価には使いません。

ビルド・実行コンテナはネットワークなし、read-onlyルート、capabilityなし、秘密情報なしで起動します。CPU・メモリ・実行時間を制限し、毎回新しいQEMUと初期rootfsを使用します。ホスト上でTAを直接実行する代替経路はありません。詳細は [docker/README.md](docker/README.md) を参照してください。

macやarm64での開発実行には `--development` が必要です。その結果は `work/` にのみ保存し、`benchmark/defective/` には保存しません。Apple Silicon上のツールチェーン構築は実機未検証です。

## 最初の1ケース（AI API不要）

最小サンプル `benchmark/normal/secure_kv/` と手書き候補を同梱しています。候補は範囲検査の境界を1文字変更し、正常入力と境界入力でR1〜R3を確認します。候補JSONは検証前の入力であり、合格済みのベンチマークではありません。

```sh
uv run ta-bench generate \
  --ta benchmark/normal/secure_kv --defects IVW=1 --count 1 \
  --max-attempts 1 --candidate examples/secure_kv_ivw.json
uv run ta-bench review --dir benchmark/
```

レビュー画面は日本語と英語を切り替えられます。右上の「English」/「日本語」を押すと切り替わり、選択はブラウザに記憶されます（URLに `?lang=en` または `?lang=ja` を付けても同じです）。分類の定義は、英語表示では `config/classes.yaml` の `description`、日本語表示ではその直前のコメント行を表示します。AIが書いた変更理由や整合性の警告は、保存されたままの文面で表示します。

`http://127.0.0.1:8765` を開くと、ケース一覧、差分、編集帰属、検出位置、入力と観測を確認できます（複数の不備を含むケースでは、不備ごとに戻した結果も）。評価者名を入力し、不備ごとに分類・位置・挙動を確認して「この不備を承認」を押します。保留・却下も不備単位です。却下には理由を記入します。チェックは変更時に保存されます。必要な評価者数は不備ごとに数え、`--required-reviewers 2` で変更できます。評価者名はローカルの自己申告です。

正解ラベルの範囲を直すには、対象の不備で「正解位置を編集」を開き、影響操作と保護操作のそれぞれについて不備版のファイル・関数・開始行・終了行を指定して「正解位置を保存」を押します。影響操作は必須です。保護操作が不備版にない場合は、その欄をすべて空にします。1行だけなら終了行を空欄にできます。修正後の範囲はケース内の `labels.json` に入り、`label_history.json` には不備ID、評価者、日時、変更前後の位置、入力したコメントが残ります。「人が修正した位置」から履歴を開けます。修正した不備は再確認の対象になります。別の不備の承認は引き継ぎます。

ケースを開くと、変更したファイルの正常版が左、不備版が右に並びます。矢印で前後の変更に移動でき、確認項目の検出位置や編集の行番号を押すと、該当ファイルのその行が表示されます。

既定では、起動したPC自身からしか開けません。同じLAN内の他のPCから開くには、待ち受けアドレスを指定して起動し、表示された `http://<このPCのIPアドレス>:8765` を開きます。

```sh
uv run ta-bench review --dir benchmark/ --host 0.0.0.0
```

特定のネットワークだけに公開する場合は、`0.0.0.0` の代わりに、このPCのそのネットワーク側のIPアドレスを指定します。接続を受け付けるのはプライベートアドレス（`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、リンクローカル）の端末だけで、URLはホスト名ではなくIPアドレスで指定します。認証も暗号化もないため、同じネットワークの誰でも閲覧とレビューの保存ができます。信頼できるネットワークでだけ使用してください。それ以外では既定のまま起動し、`ssh -L 8765:127.0.0.1:8765 <このPC>` で転送して手元の `http://127.0.0.1:8765` を開きます。

## QEMUを使う統合検証

通常の `uv run pytest -q` では、実イメージが必要なテストをスキップします。イメージを用意した後、次の手順で実測を含む検証を実行できます。`TA_BENCH_TEST_IMAGE` もタグではなく不変のダイジェストを指定します。

```sh
mkdir -p work
ta_bench_check=$(mktemp -d work/qemu-acceptance.XXXXXXXX)
TA_BENCH_TEST_IMAGE="$TA_BENCH_IMAGE" uv run pytest -v -m qemu \
  --basetemp "$ta_bench_check/cases" --junitxml "$ta_bench_check/pytest.xml"
```

正常TAのビルド・呼出し、R1〜R3、4要素の保存、レビュー画面の保存操作、同じ結果での再検証、承認失効、ブラインド出力を確認します。Makefile変更はビルド前に、通常機能を壊す変更はR1で失敗することも確認します。ログ、実測値、失敗候補は今回専用の `work/` 配下に残ります。

共有入力を呼出し途中で変更するDUS候補の保存・再検証・ブラインド出力も、対応イメージで確認します。QEMUを繰り返し起動するため、完了まで数分かかります。pytestはテスト終了まで結果を表示しないため、最初のテスト名のまま待つことがあります。`Ctrl-C`で中断した場合、その実行の合否は未確認です。最後の合否とスキップ理由まで確認してください。

レビューの自動操作は、テスト用の独立したデータセットに対して行います。研究用ケースの分類・位置・挙動について、人が承認したことにはしません。

## AIによる候補生成

使うモデルは [config/models.yaml](config/models.yaml) に登録し、先頭の `use:` で選びます。OpenAI、Claude、ローカルLLMの3つを登録例として同梱しています。

```yaml
use: openai            # ここに書いた登録名を使う

models:
  openai:
    api_url: https://api.openai.com/v1/chat/completions
    model: ""          # 使用するモデルIDを記入
    api_key_env: OPENAI_API_KEY
  local:
    api_url: http://127.0.0.1:11434/v1/chat/completions
    model: ""          # サーバー側のモデル名を記入
    api_key_env: null  # キー不要
```

```sh
export OPENAI_API_KEY='ご自身のAPIキー'
uv run ta-bench generate --ta benchmark/normal/secure_kv --defects IVW=1 --count 1
uv run ta-bench generate --request config/requests.example.yaml
uv run ta-bench generate --resume run_0123456789abcdef
```

最初の確認は `secure_kv` に `IVW=1`、目標1ケースを指定します。このTAは値の保存・読出しだけを行い、出力を暗号化などで保護する処理を持たないため、UDOの生成対象には適していません。`IVW=1,UDO=1` は「IVWとUDOを両方含む1ケース」を要求する指定で、片方を生成できない場合は組合せ全体が `unsupported` になり得ます。個数を減らしても、必要な機能のない分類を生成できるようにはなりません。

`unsupported` は生成モデルが返せる申告であり、生成不能の機械的な証明ではありません。ツールはその理由を記録して該当要求を停止します。要求を変える場合は新しい実行を開始してください。複数ケースには重複しない差分などが必要なので、小さなTAに `--count 3` を指定しても3件の生成は保証されません。複数分類を試す際は、それぞれの分類に必要な処理が正常TAにあることを確認します。

実行時だけ別の登録を使う場合は `--use 登録名`（または `TA_BENCH_USE`）を指定します。`--model` と `--api-url` は、選んだ登録のモデルIDとURLだけを上書きします。`TA_BENCH_MODEL` と `TA_BENCH_API_URL` は、登録の該当項目が空欄のときだけ使われます。登録ファイルの場所は `--models` で変更できます。

```sh
uv run ta-bench generate --use claude --ta benchmark/normal/secure_kv --defects IVW=1
uv run ta-bench generate --use local --model 'ローカルのモデル名' --ta benchmark/normal/secure_kv --defects IVW=1
```

APIキーは登録ファイルに書きません。`api_key_env` にはキーを入れた変数の名前を書き、値は環境変数から読みます。ファイルに置きたい場合は `config/api_keys.example.yaml` を `config/api_keys.local.yaml` として複製し、値を記入してください。このファイルはGit管理外で、同名の環境変数があればそちらを優先します。キーは `work/` にも検証コンテナにも渡しません。`.env` の自動読込みは行いません。

接続先はOpenAI互換のChat Completions APIです。`api_url` には `/v1/chat/completions` まで含むURLを書きます。HTTPSが必須で、`http://` は `localhost` / `127.0.0.1` / `::1` のローカルLLMに限り使えます。正常TAのソースは接続先へ送信されます。API仕様は [公式リファレンス](https://developers.openai.com/api/reference/resources/chat) を参照しています。

登録ごとに `json_mode`、`max_tokens`、`temperature`、`headers_env`、`connect_timeout`、`read_timeout` を指定できます。項目の説明は `config/models.yaml` の末尾にあります。生成プロンプトの本文は `src/ta_bench/providers/prompts/candidate.txt` です。実行機能ごとの入力の書き方は同じフォルダの `<機能名>.txt` に分けてあり、依頼した分類が `classes.yaml` の `required_features` でその機能を挙げているときだけ追加で送ります。モデル名・真偽値・数値・URLの形式を生成開始前に検査し、不正な設定ではAPIへ送信しません。

Claudeを使う場合は登録 `claude` を選び、`ANTHROPIC_API_KEY` を設定します（未設定なら `OPENAI_API_KEY` を使う動作は、`api_key_env` を省略した登録でのみ有効です）。ワークスペースに紐づかない個人キー・サービスアカウントキーは、ワークスペースIDを省略するとHTTP 400になります。[Claude ConsoleのWorkspaces](https://platform.claude.com/settings/workspaces) のID欄を確認し、`export ANTHROPIC_WORKSPACE_ID='実際のワークスペースID'` を設定してください。キー自体がワークスペースに紐づいている場合は省略できます。[公式の認証仕様](https://platform.claude.com/docs/en/manage-claude/authentication#select-a-workspace) を参照しています。キーやワークスペースIDのみを修正した場合は `--resume` で再取得します。

Anthropic公式の互換APIは `response_format: json_object` を受け付けないため、登録 `claude` では `json_mode: false` とし、プロンプトでJSONのみを要求します。出力上限は16,384トークンで、取得後のJSON・候補・ソース検査は同じです。[Anthropic公式の互換API仕様](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk) を参照しています。

HTTP 401・403などの認証・権限エラーや、400・404・422などの要求エラーでは、その実行全体を直ちに停止し、理由を `work/` に保存します。ClaudeモデルにOpenAI公式の接続先を組み合わせた設定も送信前に停止します。設定を修正してから再実行してください。`--resume` は初回に解決したモデル名・接続先・生成オプション・認証情報の参照先を引き継ぎ、試行上限も増えません。登録ファイルやモデル選択用の環境変数を変更しても、再開する実行の設定は変わりません。APIキー・追加ヘッダの値は、元の参照先の環境変数またはローカルキーファイルから再取得します。接続先やモデルの変更が必要な場合、または上限に達した場合は、新しい実行として開始してください。

APIが返すJSONエラーから、ワークスペース指定、残高・支出上限、モデルへのアクセス、JSON出力形式、出力トークン上限に関する既知の問題を判別し、対処方法を表示します。エラー本文や認証ヘッダーをそのまま表示・保存せず、判別できない場合はHTTPステータスに応じた一般的な案内を表示します。

HTTP 200でも `finish_reason: content_filter` や `message.refusal` があればAPI側のフィルター・拒否として停止し、自動再試行しません。この停止はその要求だけに適用し、要求に `provider_declined` を記録して次の要求へ進みます。空の返答や `finish_reason: length` による途中終了も停止します。候補JSONとして読み込む前に判定するため、途中までの出力を候補として採用しません。応答は `api-response.json` に残します。終了理由に問題がなく、文章がJSONとして不正な場合は、形式の修正を次の試行に指示して上限内で再試行します。

`content_filter` は生成API側で出力が止まったことを示し、TAのビルドやQEMUの判定結果ではありません。本文が空なら、ツール側には検証する候補が届いていません。応答に詳細がない場合、具体的なフィルター理由は特定できません。同じ要求の試行上限を増やす対応ではなく、提供元に用途と応答を確認します。

API生成と検証環境を切り分けるには、同梱の手書き候補を独立したデータセットで試せます。既存ケースとの重複を避けるため、毎回新しい確認用フォルダを使います。

```sh
ta_bench_manual=$(mktemp -d work/manual-check.XXXXXXXX)
mkdir -p "$ta_bench_manual/benchmark/normal"
cp -R benchmark/normal/secure_kv "$ta_bench_manual/benchmark/normal/"
uv run ta-bench generate \
  --ta "$ta_bench_manual/benchmark/normal/secure_kv" --defects IVW=1 --count 1 \
  --max-attempts 1 --candidate examples/secure_kv_ivw.json \
  --benchmark "$ta_bench_manual/benchmark" --work-dir "$ta_bench_manual/work" \
  --image "$TA_BENCH_IMAGE"
uv run ta-bench review --dir "$ta_bench_manual/benchmark" --work-dir "$ta_bench_manual/work"
```

この経路はAI APIを呼ばず、手書き候補のビルド・R1〜R3・保存を確認します。成功しても、AIによる候補生成の成功を意味しません。

`--defects` は1ケースの内訳、`--count` は合格候補の目標数です。`--max-attempts` は要求1件全体の上限（既定は目標数×3）です。未達を偽の合格で補いません。終了時に要求数・保存数・未達数・各失敗理由をJSONで表示します。未達時の終了コードは2、中断時は130です。中断した試行も上限に数え、再開は残りの件数・試行数から行います。候補ファイル・モデル・イメージ・リソース制限などは初回設定を引き継ぎます（APIキーは保存せず、環境変数から再取得）。

通常入力は正常版ソースハッシュごとに `work/normal-inputs/` に蓄積し、後の候補にも適用します。通常入力の蓄積を含む入力列全体を初回実行前にハッシュで固定します。正常版ソースや分類定義が変わった実行は再開できません。

### 本番用の収集要求

[config/requests.production.yaml](config/requests.production.yaml) は、**正常TAと不備内訳の各組合せを1件ずつ、単体15件と複合3件、合計18ケース**の収集を目標にします。要求ファイルはこの1つで、モデルやイメージは実行時に指定します。実行手順と実施記録は [docs/production-record.md](docs/production-record.md) にあります。本番の集計には本番の実行IDの記録だけを使い、要求を選ぶための開発中の試行は含めません。

同じ組合せに多数の変種を求めると、似た差分の繰り返しや分類に合わない候補が増えるため、まず各組合せから1件を収集してレビューします。追加は、別の原因・箇所の不備を作れると確認した組合せか、新しい正常TAを対象にします。これは初回収集の配分であり、各TAで作れる不備の総数を1つと見積もったものではありません。

各要求の試行上限は既定値と同じ3回、合計54回です。DUSを含む要求は `shared_memory_events_v1`、`inserts` を使う入力は `output_reference_v1` に対応する実行イメージが必要です。これらの機能がない古いイメージではAPIを呼ぶ前に `unsupported` になります。AVBはRPMBの実装も必要なため、本番要求全体には上記の `Dockerfile.rpmb` で構築したイメージを使用します。

| 正常TA | 構成 | 1ケースの不備内訳 | 目標件数 | 最大試行数 |
| --- | --- | --- | --- | --- |
| shared_record | 単体 | DUS × 1 | 1 | 3 |
| secure_storage | 単体 | DUS × 1 | 1 | 3 |
| gatekeeper | 単体 | ORDER × 1 | 1 | 3 |
| avb | 単体 | ORDER × 1 | 1 | 3 |
| sign_verify | 単体 | IVW × 1 | 1 | 3 |
| ecdsa | 単体 | IVW × 1 | 1 | 3 |
| sha | 単体 | IVW × 1 | 1 | 3 |
| gatekeeper | 単体 | IVW × 1 | 1 | 3 |
| hotp | 単体 | IVW × 1 | 1 | 3 |
| secure_storage | 単体 | IVW × 1 | 1 | 3 |
| aes | 単体 | UDO × 1 | 1 | 3 |
| sha | 単体 | UDO × 1 | 1 | 3 |
| ecdsa | 単体 | UDO × 1 | 1 | 3 |
| sign_verify | 単体 | UDO × 1 | 1 | 3 |
| hotp | 単体 | UDO × 1 | 1 | 3 |
| gatekeeper | 複合 | IVW × 1 ＋ ORDER × 1 | 1 | 3 |
| sign_verify | 複合 | IVW × 1 ＋ UDO × 1 | 1 | 3 |
| sha | 複合 | IVW × 1 ＋ UDO × 1 | 1 | 3 |
| **合計** | **単体15件・複合3件** | **不備21個** | **18** | **54** |

分類別の不備数は、単体・複合を合わせてIVW 9個、UDO 7個、DUS 2個、ORDER 3個です。要求に含む正常TAは9種類で、DUSは2種類（shared_record、secure_storage）、ORDERも2種類（gatekeeper、avb）です。AVBでは保存済みrollback indexに基づく更新許可を扱います。これは初回収集の目標数で、生成済み・人による承認済み件数や、論文の最終評価に十分な数を示すものではありません。同じTAの単体と複合を、独立した実装2種類としては数えません。
同梱TAの再検証と外部TAの出典・導入条件は、[追加TAの調査記録](docs/development-status.md#2026-11-16追補-本番要求の分布と追加taの調査)にまとめています。
AVBの取り込みと、ORDERの実装元を増やすために調べた他の候補は、[2026-11-17の追補](docs/development-status.md#2026-11-17追補-orderの実装元を2種類にするavbの取り込み)にあります。
複合では各不備に個別の発火入力を要求し、その不備の編集を戻すと対応する発火入力が
正常版の観測へ戻ることを検証します。切り分けできない候補は保存しません。

#### 要求の選定（開発記録）

2026-11-15の試行で生成不能と回答された組合せを外し、追加した正常TAの組合せを入れています。外した組合せは次のとおりです。いずれもモデルが理由付きで「生成不能」と回答しました。これは当時の生成結果であり、生成不能の証明ではありません。

- hotp・aes・acipher・shared_record の ORDER: 試行記録や認可などの保護処理がない。
- aes の IVW: 長さは後続のAPIが検査するため、範囲外アクセスに至らない。
- 上記を含む複合（aes の IVW+UDO・IVW+ORDER・UDO+ORDER、shared_record の DUS+ORDER）。

secure_storage の DUS も当時のモデルが「同期点がない」と回答して外していましたが、2026-11-16に手書き候補とAI生成（2回目の試行）の両方で機械合格を確認したため、単体の要求として戻しました。secure_storage の IVW+DUS の複合は未確認のため、含めていません。

開発中の機械合格・再検証・フィルター停止の記録は [開発状況](docs/development-status.md) にあります。gatekeeper/ORDER の再検証では、通常入力の登録ハンドルに含まれる乱数の揺れによる不合格が見つかっており、対策は未着手です（[R4削除後の検証記録](docs/development-status.md#2026-11-15追補-r4編集ごとの必要性の削除)）。

#### 実行と停止条件

RPMB対応イメージを `TA_BENCH_IMAGE` に設定し、`benchmark/defective/` が空であることを確認してから、新しい作業先を指定して実行します。機械合格したケースは標準の保存先 `benchmark/defective/` に入ります。作業先を新しくするのは、通常入力の蓄積（`normal-inputs/`）を以前の実験から引き継がないためです。

```sh
uv run ta-bench generate --request config/requests.production.yaml \
  --work-dir work/production-YYYYMMDD
uv run ta-bench generate --resume run_... --work-dir work/production-YYYYMMDD   # 中断した場合
uv run ta-bench review --dir benchmark/ --reverify                               # 終了後の再現確認
```

機械合格候補は `unreviewed` で保存され、`count` はその実行で新たに保存する機械合格件数を指定します。既存データセットの総数や承認済み件数を指定するものではありません。同じ正常TAの同じ場所への同じ差分などの重複は拒否し（別のTAや別の場所への同じ形の編集は別ケースです）、TAと分類の組合せによる生成不能や、上限までに目標件数へ達しない場合は未達として記録します。正常TAと不備原因の多様性を確認し、同じTA由来の変種が学習・調整・評価にまたがらないように分割します。

要求ファイルの変更は新規実行に適用します。`--resume` は開始時に保存した要求を引き継ぐため、以前の実行を再開すると旧設定の件数・試行上限が使われます。

`unsupported` と、API側のフィルター・拒否（`content_filter`、`message.refusal`）では該当要求を停止し、次の要求へ進みます。同じ正常TAで保存済みのケースの差分は、依頼のたびに `existing` としてAIに渡します。AIの回答は、分類に当てはまるコードがない場合の `{"unsupported": "理由"}` と、コードはあるが入れられる不備がすべて保存済みの場合の `{"exhausted": "理由"}` に分かれます。`exhausted` の場合は要求にそのまま記録して次の要求へ進みます（結果の `exhausted` に要求数が出ます）。保存済みのケースを渡していないのに `exhausted` と答えた場合は、不正な回答として再試行します。フィルターで停止した要求は、保存済みの件数が目標に届いていなくても再試行しません。停止した要求の数は結果の `provider_declined` に出ます。認証・課金・モデル指定の誤りや出力の途中終了（`finish_reason: length`）など、ほかの再試行しないAPIエラーでは、残る要求も含めて実行全体を停止します。これらの停止条件に該当すれば、試行上限に達する前に終了します。保存数・未達数・理由を確認し、未達を生成不能や正常ケースとして扱わないでください。

検証ログと状態は指定した作業先に、機械合格候補は `benchmark/defective/` に保存します。再開でも同じ作業先を指定し、`run_...` は実行時に表示されたIDに置き換えます。

テスト入力などを手動で補正する場合は、元のAPI応答と補正内容を保存し、自動生成のみの結果と区別して記録します。機械合格候補は `unreviewed` のまま保存されます。本番の評価に使う正解データは、人手で分類・位置・挙動を確認して承認してください。

## 正常TAの追加・分類設定

`benchmark/normal/<名前>/` にTAフォルダを置き、`--ta` で指定します。同梱の `secure_kv` のほか、OP-TEE公式サンプル10種（4.4.0の `hello_world`、`random`、`aes`、`acipher`、`hotp`、`secure_storage` と、4.11.0の `sha`、`ecdsa`、`sign_verify`、`ecdh`）、kmgkの `gatekeeper`、optee_test 4.4.0の `storage`、optee_os 4.4.0の `avb` を置いています。上流のファイル内容は変更していません。出典とコマンド一覧は [benchmark/normal/UPSTREAM.md](benchmark/normal/UPSTREAM.md) にあります。マニフェストは不要です。別の場所のTAも指定できますが、ケースの `normal.path` が絶対パスになり、配布時の移植性が下がります。

現在のビルド規約は `ta/Makefile` がOP-TEEの `TA_DEV_KIT_DIR`、`CROSS_COMPILE`、`O` を受け取れることです。ヘッダから一意のUUIDを取得します。UUIDが複数ある場合は、`#define TA_UUID` が指す1つを使います。入力はセッション開始・コマンド呼出し・終了の列で、パラメータはvalue、temporary memref、実共有メモリの `shared_memref_*` です。入力バッファには、同じ列の前の呼出しの出力を `inserts` で複写できます（`output_reference_v1`）。セッション開始パラメータには未対応です。検証用の `shared_record` も同梱しています。

分類名・説明・対応状態は `config/classes.yaml` で変更します。ユーザー提供の論文草稿「実行順序の設計不備 ORDER の定義と OP-TEE TA の証拠付きベンチマーク」（Nov. 2026、第3.3–3.4節、表2・4）に基づき、IVW・UDO・DUS・ORDERを定義しています。分類名に依存せず、AIが入力列の `events` で「停止位置・到達回数・変更対象・期待値・変更後の入力」を指定できます。正常版・欠陥版・編集を戻した版に同じ操作を行います。DUSでは検証と使用の間に共有入力を変更します。どの分類もTAとの組合せによって生成できない場合があります。

分類に必要な機能は `required_features`、追加条件は `witness_conditions` で選びます。既存の条件は `normal_error_at_witness` と `shared_memory_changed` です。既存の操作と条件で表現できる新分類は設定で追加でき、未知の観測・操作には実行器の拡張が必要です。任意Pythonやシェルを設定から実行する仕組みはありません。分類の意味と同期点の妥当性は人の確認事項です。

候補JSONと入力列の詳細は [docs/candidate-format.md](docs/candidate-format.md) を参照してください。

## ソース構成

```text
src/ta_bench/
├── cli.py          コマンドの引数と振り分け
├── errors.py       例外の定義
├── common/         正規化JSON、ソースのハッシュ、ロック、分類定義の読込み
├── candidate/      候補の静的検査（許可パス、入力列、差分と編集、Cの字句走査）
├── providers/      候補の取得元（手書きファイル、API、モデル登録、プロンプト）
├── runtime/        Docker/QEMUでのビルド・実行、UUID検出、観測の形式検査
├── verification/   R1〜R3の判定と不備の切り分け、保存済みケースの再検証
├── dataset/        ケースのスキーマ、原子的な保存、整合性検査、重複検査
├── generation/     生成要求、通常入力の蓄積、1候補の処理、実行全体の進行
├── review/         レビュー画面、ブラインド出力
└── invoke/         QEMU内で動く共通クライアント（C）
```

## データ・再検証・ブラインド出力

機械検証に通ったケースだけが次の4要素で原子的に保存されます。

```text
benchmark/defective/case_<乱数>/
├── source/
├── labels.json
├── changes.diff
└── verification.json
```

`work/` には試行状態、失敗理由、API応答、固定した入力列、ビルドとQEMUのログを残します。配布対象ではありません。正常版を変更せず、実験ごとに別名のフォルダとして追加してください。

再試行時には、直前の試行の失敗段階と理由、提案した不備（ID・分類・理由・位置ラベル）、ソース変更（`changes` 形式の場合。最大16件、各1000文字まで）をAIへ返します。実測まで進んだ場合は、加えて失敗したテストの入力列と出所（候補自身／蓄積通常入力）、返却コード、出力長、value値、比較から除いた変動項目をAIへ返します。両版が同じエラーになったR2不合格でも実測値を返します。バッファの内容は先頭32バイトに制限し、切詰めと元の長さを明記します。観測行は準備処理の最初のエラーや発火ステップを優先して最大12行とし、完全な入力・実測値は試行先の `plan.json` と `failed-semantic.json` に残します。

```sh
uv run ta-bench review --dir benchmark/ --reverify
uv run ta-bench review --dir benchmark/ --export-blind ./evaluation-input --approved-only
```

`--reverify` は保存した入力列を再実行して終了します。観測・判定が同じなら日時だけ更新され、承認は維持されます。以前の結果は `work/reverify/` に残ります。通常のレビュー起動ではAPIもQEMUも実行しません。

個別の承認は両版のソース、差分、観測結果、その不備のラベルと修正履歴に結び付きます。`labels.json` の `review.per_defect` に不備ごとの判断を保存します。全件を承認するとケースも `approved` になり、一部の承認は `partially_approved` として一覧に件数を表示します。既定のブラインド出力は全不備を承認したケースが対象です。承認時のソースや観測結果が変わった場合は `stale` と表示されます。

ブラインド出力は別のランダムIDの下に、既定ではTA側のソースだけを複製します。`--include-host` でhostソースも含められます。正解との対応表は `work/blind-mappings/` に置き、出力先には置きません。未承認候補まで出す場合のみ `--include-unreviewed` を明示します。検出器には1ケースずつ独立したセッションで渡し、照合粒度と生成／検出モデルの関係を評価前に決めてください。

## 検証範囲

- R1: 通常入力の観測一致。過去の通常入力も再実行。
- R2: 発火ステップ以降の観測差。正常版は異常終了しない。
- R3: 両版を2回実行。同じ版の2回で一致しなかった項目（戻り値、出力の長さ、各バッファの中身など）は、正常版・不備版のどちらで起きても比較から除き、残りの項目をすべて比較する。バッファは中身が1バイトでも違えば中身全体を除く（乱数は1バイト単位では偶然一致するため）。除いた項目は `variable_items` に記録し、レビュー画面に表示する。差が除いた項目の中にしかない場合は `unknown`。
- 不備の切り分け: 複数の不備を含むケースでは、不備を1つずつ戻して再ビルド・再実行し、その不備の発火観測が正常版へ戻ることを確認。

編集を1つずつ戻す確認（以前のR4）は行いません。不要な変更が混ざっていないかは機械では確認しないため、レビューで差分を見て判断します。

静的検査では全ファイル比較、許可パス、編集の一意帰属、実在行・関数、露骨なラベル漏洩、差分・位置の重複を確認します。関数範囲の検査はCソースの字句走査であり、完全なCコンパイラ解析ではありません。条件付きコンパイルや複雑なマクロの意味は人のレビューが必要です。

テストの疑似runnerは判定・保存・レビューのロジック確認専用です。実測結果として公開する経路はDocker/QEMUのみです。機械合格は分類の正しさ、未試験入力での安全性、正常版の無欠陥性、不備原因の多様性を保証しません。
