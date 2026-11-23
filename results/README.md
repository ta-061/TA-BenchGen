# 測定結果と再実行手順

2026年11月23日7時42分（日本時間）にKaliでのTEE Flow Inspector＋Qwenの測定が完了し、測定対象35個すべてについて静的解析4条件とLLMの出力がそろいました。[全手法のTA別比較（Excel）](outputs/label-comparison/TA別検知結果.xlsx) · [LLMの測定結果・実行環境・原出力](llm-e12-qwen/README.md)

TAを1個再実行するには `TA-BenchGen/` 直下で `./results/run.sh T18` を実行します。Macでは静的解析4条件、KaliではLLM評価を実行します。[実行ファイル](run.sh) · [各手法の導入・実行コマンド](COMMANDS.md)

<a id="raw-output"></a>

## 原出力を展開する

SQLite・CSV・Excelはクローン直後から閲覧できます。各TAの原出力を調べる場合やSQLiteを再生成する場合は、論文版のReleaseの添付ファイル `ta-benchgen-raw-results-2026-11.tar.gz` をリポジトリ直下に保存し、次を実行します。測定時の35個の入力を再実行するには、コミット `4fc3ae9` を含むGit履歴を使います。[Releases](https://github.com/ta-061/TA-BenchGen/releases) · [アーカイブのSHA-256](raw-results.sha256)

```sh
shasum -a 256 -c results/raw-results.sha256 && tar -xzf ta-benchgen-raw-results-2026-11.tar.gz
```

展開先は `results/2026-11-21/{diting,codeql,semgrep,logs}/`、`results/diting-gp11/{diting,logs}/`、`results/llm-e12-qwen/cases/Txx/attempt-01/` です。LLMのHTML・JSONは各試行の `outputs/results_1/` にあります。

## 現行ベンチマーク25個の比較

正常対照10個と不備TA 15個を集計しました。「位置一致」は、人手承認済みの不備16件のうち、同じTA・ファイルで報告がラベルの行範囲に重なった不備の件数です。同じ不備への複数の報告は1件と数えます。[手法別集計（CSV）](outputs/label-comparison/method-summary.csv) · [TA・手法別集計（CSV）](outputs/label-comparison/ta-method.csv)

| 手法 | 正常対照の報告 | 不備TAの報告 | 総報告 | 位置一致 | 位置・主分類ともに一致 |
| --- | ---: | ---: | ---: | ---: | ---: |
| DITING 公開版 | 20 | 20 | 40 | 0/16 | 0/13 |
| DITING 1.1互換版 | 42 | 70 | 112 | 1/16 | 1/13 |
| 標準CodeQL | 2 | 4 | 6 | 0/16 | — |
| Semgrep CE | 0 | 0 | 0 | 0/16 | — |
| TEE Flow Inspector＋Qwen | 366 | 238 | 604 | 1/16 | 0/13 |

DITINGの両条件とTEE Flow InspectorではIVW・UDO・DUSの13件について分類を照合できます。標準CodeQLとSemgrepには今回の不備分類への対応付けがないため「—」としました。Semgrepの25個には、一部ファイルで解析上の診断が出た6個も含みます。Excelの「承認範囲内」は位置が一致した**報告数**で、公開位置との一致も別に確認できます。T30のD1には承認時に追加した保護位置を使いました。[集計定義](replay/label_schema.sql) · [レビュー状態](../benchmark/README.md) · [T30のレビュー履歴](../benchmark/defective/case_c4cb059bfbd14ca1/label_history.json)

## 論文で採用した18件の不備との照合

採用した18件は、全件承認の不備TA 13個の15件、一部承認のshaのIVW 1件、PKCS#11の未レビューのORDER 2件です。この不備TA 15個には正常対照9個が対応します。本文表7と同じ条件で不備TAの報告を照合すると、TEE Flow Inspectorは保護位置を持つ14件のうち0件、効果位置を持つ18件のうち2件に一致しました。効果位置で一致したのはavbのT26/D1とPKCS#11のT33/D1です。[全手法の保護位置・効果位置別の最終集計（CSV）](outputs/label-comparison/paper-roles.csv) · [採用条件](replay/paper_cohort.sql) · [LLMの位置別照合（CSV）](llm-e12-qwen/locations.csv)

## SQLiteの構成と集計表

集計元のSQLiteには、測定した全入力を収録する。`ta.ta_id` が測定時の入力ID、`ta.normal_id` が不備TAに対応する正常対照のIDである。入力ファイルのSHA-256、各手法の採用出力のパス、公開時・承認時のラベル位置を同じ入力IDでたどれる。[SQLiteデータベース](outputs/label-comparison/benchmark-results.db) · [テーブル・キー・ビューの定義](replay/label_schema.sql)

| 記録 | 1行の単位 | 主な結合キー |
| --- | --- | --- |
| `ta`、`method` | 1個のTA、1つの解析条件 | `ta_id`、`method_id` |
| `defect` → `label_target` | TA内の不備1件 → その不備のソース位置1か所 | `ta_id, defect_id` |
| `analysis_run` → `report` | TAと手法の組1件 → 原出力の報告1件 | `ta_id, method_id`。報告はさらに `report_ref` で識別 |
| `report_location`、`report_rule` | 1報告のソース位置1か所、または規則1件 | `ta_id, method_id, report_ref` |

報告とラベルの対応は、同じTA・ファイルで開始行と終了行が重なる範囲からSQLで求める。手法に分類対応があるかは `method_class`、元の規則名と分類の対応は `native_rule` にある。未完了の件数と適用外の分類一致には `NULL`、出力があり該当報告が0件なら数値の `0` を使う。

| 知りたいこと | SQLビュー | 含まれる対象 |
| --- | --- | --- |
| 手法ごとの報告数、位置・分類一致数、評価できたラベル数 | `v_method_summary` | 現行のみ、1手法1行 |
| 注入した各不備分類で、何件の承認ラベルに報告が一致したか | `v_class_summary` | 現行のみ、1手法・1注入分類につき1行 |
| 各TAの総報告数と、報告側の分類別内訳 | `v_ta_method`、`v_ta_method_class` | 全入力。`ta` と結合して `scope = 'current'` で現行に限定できる |
| 個々の報告がどの不備・位置に重なったか | `v_match` | 一致した報告とラベル位置の組。複数の報告位置が同じラベル位置に重なる場合は1行 |
| ゼロ件も含めて、不備または位置ごとの結果を調べたい | `v_defect_result`、`v_target_result` | 不備・手法の組、または位置・手法の組 |

ExcelとCSVはこのデータベースから出力する。従来のCSVは1行が1個のTAと1手法の組で、`within_approved` と `within_public` は範囲内の報告数、`same_*` は位置・分類が一致した報告数、`labels_hit_*` と `labels_same_*` は一致した別個の不備ID数を示す。[TA・手法別の全列（CSV）](outputs/label-comparison/ta-method.csv)

原出力を展開し、TA-BenchGenのPython環境（Python 3.11以上、PyYAML）で次を実行すると、SQLite、`ta-method.csv`、`method-summary.csv` を再生成できる。Excelも再生成する場合は `@oai/artifact-tool` を含むCodexのNodeランタイムを用意し、`--data-only` を外す。[再集計スクリプト](replay/build_label_report.py) · [位置別CSVの再生成](COMMANDS.md#tables)

```sh
python3 results/replay/build_label_report.py --data-only
sqlite3 -header -column results/outputs/label-comparison/benchmark-results.db 'SELECT method_id, with_output, total_reports, reports_at_approved, reports_same_approved FROM v_method_summary ORDER BY method_id'
```

## 測定時の対象と原出力

測定開始時の対象は正常対照16個と不備TA 19個です。このうち旧正常対照6個と人手却下の不備TA 4個はSQLite・Excelに参考値として収録しました。TEE Flow Inspectorの全35個の完了記録はTA別に参照できます。[LLMの最終状態](llm-e12-qwen/status.json) · [TA別の完了記録](llm-e12-qwen/cases/)

| ツール | 使用版・実行条件 | 導入と実行手順 | 収集した結果 |
| --- | --- | --- | --- |
| DITING | 公開版 `cb72e886` のクエリとPython後処理をCodeQL CLI 2.23.0で実行 | [Macでの導入](2026-11-21/REPRODUCE.md#導入方法) · [実際の起動コマンド](2026-11-21/REPRODUCE.md#diting) | `2026-11-21/diting/Txx.txt` |
| DITING（OP-TEE 1.1互換型対応） | 上記の公開版の型名条件に `__GP11_TEE_Param` を追加し、同じ35個のTAのデータベースで実行 | [6行の差分](diting-gp11/rules.patch) · [再実行](diting-gp11/README.md#再実行) | [公開版との比較](diting-gp11/README.md) · [TA別の前後比較](diting-gp11/cases.csv) |
| 標準CodeQL | DITINGと共有のC/C++データベース、`cpp-security-extended.qls` | [DBの作成](2026-11-21/REPRODUCE.md#共有データベースの作成) · [解析コマンド](2026-11-21/REPRODUCE.md#標準codeql) | `2026-11-21/codeql/Txx.sarif.gz` |
| Semgrep CE | 専用venvの1.164.0、固定したC用の2規則 | [Macでの導入](2026-11-21/REPRODUCE.md#導入方法) · [走査コマンド](2026-11-21/REPRODUCE.md#semgrep-ce) | `2026-11-21/semgrep/Txx.json` |
| TEE Flow Inspector | 公開版 `e06f0c6` のe12、Kali上のDocker、別ホストのQwen/Qwen3.8-27B | [Kaliの環境と導入](llm-e12-qwen/README.md#実行環境とインストール) · [実際の起動コマンド](llm-e12-qwen/README.md#測定時の実行コマンド) | [TA別の集計](llm-e12-qwen/cases.csv) · [完了記録](llm-e12-qwen/cases/) · [JSON・HTMLの展開](#raw-output) |

静的解析35個の集計、公開ラベルとの位置照合、再試行の扱いは測定日の記録にある。[静的解析の結果](2026-11-21/README.md) · [各TAの実引数とログの索引](2026-11-21/README.md#出力と実行コマンド)
