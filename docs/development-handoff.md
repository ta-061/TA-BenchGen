# TA Benchmark Generator

TA 設計不備ベンチマーク生成ツールの作り直し用リポジトリです。
2026-11-14時点で、仕様v4の生成・検証・保存・レビューとDocker/QEMU実行環境を実装しています。
セットアップと操作方法は [README](../README.md)、実測を含む到達状況は [開発状況](development-status.md) を参照してください。
既存の `ai_generator` は自動移植しません。

## 開発場所

- Mac: `/Users/yoshinagatatsuya/Documents/tee-bad-partitioning-research/ta-benchmark-generator`
- Kali: `/home/matsulab/tatuya/study/ta-benchmark-generator`
- 共通 Git remote: `https://github.com/ta-061/ta-benchmark-generator.git` (private)

Kali の `study` 直下には既存研究があるため、本リポジトリだけを子フォルダに分離しています。
Git はファイルの常時自動同期ではありません。コミットして push した変更だけをもう一方で取得できます。

## 引継ぎ

片方で作業を終えるとき:

```sh
git status --short
# 変更内容を確認し、必要なファイルだけを指定する
git add <変更したファイル>
git commit -m "Describe the change"
git push
```

もう一方で作業を始めるとき:

```sh
git status --short
# 未コミット変更があれば先に保存・整理する
git pull --ff-only
```

同時に開発する場合は作業別ブランチを使ってください。

```sh
git switch -c work/<作業名>
git push -u origin HEAD
```

別の端末でその作業を引き継ぐ場合は `git fetch origin` の後、対象ブランチに切り替えます。
強制 push、`git reset --hard`、自動削除同期は使用しません。
`.venv`、API キー、認証情報、生成中の結果は共有しません。
環境構築方法や依存関係を変更した場合は、リポジトリ直下の README と `uv.lock` を更新してください。

## Kali で切断後も端末作業を保持する

Mac からの既存 SSH 接続:

```sh
ssh kali
cd /home/matsulab/tatuya/study/ta-benchmark-generator
tmux new-session -A -s ta-benchmark -c /home/matsulab/tatuya/study/ta-benchmark-generator
```

上の tmux 内で、本人の既存 Codex 設定を利用する場合:

```sh
CODEX_HOME=/home/matsulab/.codex-tatu codex
```

`Ctrl-b` の後に `d` で切り離せます。Kali が稼働していれば tmux 内のプロセスは SSH 切断後も残ります。
これは新しい開発を自動開始する設定ではありません。指示を与えた処理だけが動きます。

## スマホからの指示と制限

GitHub 同期とスマホからの AI 操作は別です。
Kali の既存 Codex remote-control プロセスは確認済みですが、この Dot の利用可能な環境一覧には Kali が表示されていません。
そのため、この Dot から Mac オフライン時に Kali を操作できる状態とはまだ確認できていません。
Kali がスマホ側の同じアカウントの接続先として表示されるか、利用許可されているかを確認する必要があります。
Mac 経由 SSH だけでは、Mac オフライン後の新しい指示は届きません。

2026-11-13 初期設定: 両端末の clone と Git 同期のみ。開発ジョブは起動していません。
