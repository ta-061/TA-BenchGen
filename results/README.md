# 検出器の測定結果

不備TA 16個に含まれる19件の不備について、4つの検出器の報告をラベル位置と照合しました。ラベルは影響行19か所、保護行14か所です。[各ツールに渡したコマンド](COMMANDS.md) · [不備とラベルの一覧](../benchmark/README.md) · [IDとケースの対応](cases.json)

| 手法 | 検出数 | 位置一致（保護行） | 位置一致（影響行） | IVW（保護行） | IVW（影響行） | UDO（保護行） | UDO（影響行） | DUS（保護行） | DUS（影響行） | ORDER（保護行） | ORDER（影響行） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DITING（GP 1.1互換） | 76 | 0/14 | 1/19 | 0/9 | 1/9 | — | 0/3 | 0/1 | 0/2 | 0/4 | 0/5 |
| 標準CodeQL | 4 | 0/14 | 0/19 | 0/9 | 0/9 | — | 0/3 | 0/1 | 0/2 | 0/4 | 0/5 |
| Semgrep CE | 0 | 0/14 | 0/19 | 0/9 | 0/9 | — | 0/3 | 0/1 | 0/2 | 0/4 | 0/5 |
| TEE Flow Inspector＋GPT-5.2 | 421 | 1/14 | 10/19 | 1/9 | 2/9 | — | 3/3 | 0/1 | 1/2 | 0/4 | 1/5 |

表の読み方は次のとおりです。[同じ表（Markdown）](summary/summary.md) · [分類・役割別の全集計（CSV）](summary/by-class.csv)

- **検出数**は、不備TA 16個に対する報告の総数です。
- **位置一致**は、報告がラベルと同じTA・同じファイルにあり、行範囲が重なったラベル位置の数です。分母はラベル位置の数です。
- **IVW・UDO・DUSの列**は、位置に加えて報告の分類もラベルと一致した数です。標準CodeQLとSemgrepには対応する分類がないため、位置一致の数を載せています。
- **ORDERの列**は位置一致の数です。どの検出器にもORDERに対応する報告分類がありません。TEE Flow Inspectorが重なった1か所の報告分類はDUSでした。
- **UDOの保護行**は「—」です。UDOの3件には保護行のラベルがありません。

TEE Flow Inspectorは、シンクの特定から報告の生成までの全段階を3回、それぞれ最初から実行しました。**同じファイル・同じ行が2回以上報告された位置を検出1件**と数え、分類も2回以上で一致したものを採用しています。PKCS#11のT33は費用の都合で1回だけ測定し、その1回の報告をそのまま使っています。T33を除く15個の検出数は192件です。

## ラベル位置に重なった報告

DITINGが重なったのは1か所、TEE Flow Inspectorが重なったのは11か所です。[全ラベル位置の照合（CSV）](summary/locations.csv) · [重なった報告の一覧（CSV）](summary/matches.csv)

| 不備 | 分類 | 役割 | ラベル位置 | 手法 | 報告分類 | 報告した回 |
| --- | --- | --- | --- | --- | --- | --- |
| T18/D1 | IVW | 影響行 | `ta/ecdsa_ta.c:293` | DITING | IVW | — |
| T18/D1 | IVW | 影響行 | `ta/ecdsa_ta.c:293` | TEE Flow Inspector | IVW | 3/3 |
| T19/D1 | UDO | 影響行 | `ta/sign_verify_ta.c:245–246` | TEE Flow Inspector | UDO | 3/3 |
| T21/D1 | IVW | 影響行 | `ta/gatekeeper_ta.c:214` | TEE Flow Inspector | DUS | 3/3（うち1回はIVW） |
| T24/D1 | IVW | 影響行 | `ta/gatekeeper_ta.c:543–544` | TEE Flow Inspector | UDO | 2/3 |
| T27/D1 | IVW | 影響行 | `ta/sha_ta.c:365–366` | TEE Flow Inspector | DUS | 3/3 |
| T30/D1 | IVW | 保護行 | `ta/sha_ta.c:83` | TEE Flow Inspector | IVW | 2/3 |
| T33/D1 | ORDER | 影響行 | `ta/src/pkcs11_token.c:1207` | TEE Flow Inspector | DUS | 1回のみ測定 |
| T34/D1 | IVW | 影響行 | `ta/sign_verify_ta.c:240` | TEE Flow Inspector | IVW | 3/3 |
| T34/D2 | UDO | 影響行 | `ta/sign_verify_ta.c:245` | TEE Flow Inspector | UDO | 3/3 |
| T35/D1 | UDO | 影響行 | `ta/ecdsa_ta.c:297` | TEE Flow Inspector | UDO | 3/3 |
| T36/D1 | DUS | 影響行 | `ta/gatekeeper_ta.c:672` | TEE Flow Inspector | DUS | 3/3 |

IVWの影響行は5か所で位置が重なりましたが、T21・T24・T27の3か所は報告の分類がラベルと異なるため、IVWの列には2か所だけを数えています。

## 報告数の内訳

| 手法 | 報告の総数 | IVW | UDO | DUS | 分類なし |
| --- | ---: | ---: | ---: | ---: | ---: |
| DITING（GP 1.1互換） | 76 | 10 | 66 | 0 | — |
| 標準CodeQL | 4 | — | — | — | 4 |
| Semgrep CE | 0 | — | — | — | 0 |
| TEE Flow Inspector＋GPT-5.2 | 421 | 106 | 11 | 290 | 14 |

TEE Flow Inspectorの「分類なし」は、3回の分類がそろわなかった位置と、T33で3分類以外の規則が主分類になった報告です。421件のうち229件はT33、130件はgatekeeperを正常対照とする4個（T21・T24・T28・T36）の報告です。[TA・手法ごとの報告数（CSV）](summary/reports.csv)

## 3回の測定の間の違い

T33を除く15個のTAについて、1回ごとの結果を比べました。ラベル位置は影響行17か所、保護行13か所です。シンクの特定からやり直しているため、選ばれるシンクと候補の数も回ごとに少し変わります。[ラベル位置ごとの3回の結果（CSV）](summary/tee-flow-runs.csv) · [回ごとのシンク数・候補数・報告数・トークン数（CSV）](tee-flow-inspector-gpt52/runs.csv)

| 測定 | シンク | 候補 | 報告数 | 位置一致（影響行） | 位置一致（保護行） |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1回目 | 566 | 373 | 195 | 9/17 | 0/13 |
| 2回目 | 568 | 367 | 207 | 8/17 | 1/13 |
| 3回目 | 569 | 375 | 192 | 10/17 | 1/13 |
| 2回以上で一致（採用した値） | — | — | 192 | 9/17 | 1/13 |

30か所のラベル位置のうち、3回とも報告が重なったのは8か所、2回が2か所、1回だけが1か所、0回が19か所でした。1回だけ重なった1か所（T22の影響行）は検出に数えていません。

## 測定条件

| 手法 | 条件 |
| --- | --- |
| DITING | 公開版 `cb72e886` の型名条件に `__GP11_TEE_Param` を追加（4ファイル6行）。CodeQL CLI 2.23.0、`cpp-all` 5.5.0 |
| 標準CodeQL | DITINGと同じデータベース、`cpp-security-extended.qls`（`cpp-queries` 1.4.7） |
| Semgrep CE | 1.164.0、C用の2規則 |
| TEE Flow Inspector | 公開版 `e06f0c6`、プロンプト `e12_general_sink_screening`。候補生成でエントリポイントとシンクのGP 1.1互換名を追加。シンクの特定とフローの判定はどちらも `gpt-5.2-2025-12-11`（temperature 0.7、reasoning effort `none`） |

静的解析の3手法はKali Linux（x86-64）で2026年11月24日に実行しました。TAはDebian clang 18.1.8で `aarch64-none-elf` 向けにコンパイルしています。[静的解析の環境とハッシュ](diting-codeql-semgrep/environment.json) · [DITINGへの変更](diting-codeql-semgrep/diting-gp11-typename.patch) · [GPT-5.2の設定](tee-flow-inspector-gpt52/llm_config.json)

TEE Flow Inspectorの3回は互いに独立です。関数の分類、シンクの特定、候補の生成、フローの判定、報告の生成を回ごとに最初から実行し、他の回の出力や応答は使っていません。関数の分類はLLMを使わない処理で、3回とも同じ結果でした。

T33だけは条件が異なります。シンクは以前の測定でQwen/Qwen3.8-27Bが特定したものを使い、候補484件をGPT-5.2で1回判定しました。[T33の記録](tee-flow-inspector-gpt52/pkcs11-T33/)

OpenAI APIの標準単価で換算した費用は、T33を除く15個で1回あたり約17ドル、T33の1回が約26ドルです。2回目のT24は、APIの残高不足で中断した試行を破棄し、最初からやり直しました。中断した試行は `attempt-01` として記録に残しています。

## フォルダの構成

| 場所 | 内容 |
| --- | --- |
| [summary/](summary/) | 照合結果のCSVと上の表。`labels.csv` が評価に使ったラベル位置 |
| [diting-codeql-semgrep/cases/Txx/](diting-codeql-semgrep/cases/) | DITINGの出力 `diting.txt` とクエリごとの表、標準CodeQLの `codeql.sarif.gz`、Semgrepの `semgrep.json`、実引数 `commands.json` |
| [tee-flow-inspector-gpt52/run-NN/cases/Txx/](tee-flow-inspector-gpt52/) | 回ごとのシンク `ta_sinks.json`、互換名を追加したシンク、候補 `ta_candidate_flows.json`、報告 `ta_vulnerabilities.json`、判定漏れの検査 `coverage.json`、API利用の記録、実引数 |
| [tee-flow-inspector-gpt52/pkcs11-T33/](tee-flow-inspector-gpt52/pkcs11-T33/) | 1回だけ測定したT33の記録 |
| [score.py](score.py) · [check.py](check.py) | 集計と、入力・記録の整合性検査 |

モデルの会話ログとHTMLの報告は容量が大きいため、Gitでは管理していません。

## 集計と検査をやり直す

リポジトリのルートで実行します。どちらも保存済みの記録を読むだけで、解析器やAPIは呼びません。

```sh
uv run python results/score.py    # summary/ を作り直す
uv run python results/check.py    # 入力と記録の整合性を検査する
```

`check.py` は次の点を確かめます。

- 解析に渡したソースが、ベンチマークのソースと同じであること。
- 静的解析とTEE Flow Inspectorが同じ入力を使っていること。
- ラベル位置がコードの行を指していること。
- 3回がそれぞれ自分でシンクを特定して候補を作り、その候補をすべて判定していること。
- 応答がすべて指定のモデルから返り、反復の間で共有されていないこと。
- 静的解析の各段階が成功していること。

TEE Flow Inspectorの報告にあるファイルのパスは、絶対パスでない場合、TAの `ta/` ディレクトリからの相対パスとして扱いました。この扱いで位置が決まらなかった報告は13件で、検出数に含めていません。
