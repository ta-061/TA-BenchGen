# 上流から取得した正常TAの出典

## optee_examples 4.4.0（6種）

次の6フォルダは、OP-TEE公式サンプル [linaro-swg/optee_examples](https://github.com/linaro-swg/optee_examples) の複製です。内容は上流と同一で、変更していません。

- 取得元: `https://github.com/linaro-swg/optee_examples.git`
- タグ: `4.4.0`（コミット `378dc0db2d5dd279f58a3b6cb3f78ffd6b165035`）
- 実行イメージ内の `optee_examples` と同じコミットです。
- ライセンス: BSD 2-Clause。全文は [LICENSE.optee_examples](LICENSE.optee_examples) にあります。個別のライセンス表記を持つファイルは、その表記に従います。

| フォルダ | UUID | コマンド（ID: パラメータ） |
| --- | --- | --- |
| `hello_world` | `8aaaf200-2450-11e4-abe2-0002a5d5c51b` | 0 加算 / 1 減算: `value_inout` |
| `random` | `b6c53aba-9669-4668-a7f2-205629d00f86` | 0 乱数生成: `memref_output` |
| `aes` | `5dbac793-f574-4871-8ad3-04331ec17f24` | 0 準備: `value_input`×3（方式・鍵長・方向） / 1 鍵設定: `memref_input` / 2 IV設定: `memref_input` / 3 暗号処理: `memref_input`, `memref_output` |
| `acipher` | `a734eed9-d6a1-4244-aa50-7c99719e7b7b` | 0 鍵生成: `value_input`（鍵長ビット） / 1 暗号化: `memref_input`, `memref_output` |
| `hotp` | `484d4143-2d53-4841-3120-4a6f636b6542` | 0 共有鍵登録: `memref_input` / 1 HOTP取得: `value_output` |
| `secure_storage` | `f4e750bb-1437-4fbf-8785-8d3580c34994` | 0 読出し: `memref_input`（ID）, `memref_output` / 1 書込み: `memref_input`（ID）, `memref_input`（データ） / 2 削除: `memref_input`（ID） |

2026-11-14に、6種すべてを実行イメージ（OP-TEE 4.4.0）でビルドし、QEMU上でセッション開始・呼出し・終了が成功することを確認しました。

## optee_examples 4.11.0（4種）

4.4.0 より後に追加された公式サンプルです。内容は上流と同一で、変更していません。

- 取得元: `https://github.com/linaro-swg/optee_examples.git`
- タグ: `4.11.0`（コミット `71e8f3f320eef46a9369700bf30b91d67427d535`）
- ライセンス: BSD 2-Clause（[LICENSE.optee_examples](LICENSE.optee_examples) と同文）。

| フォルダ | UUID | コマンド（ID: パラメータ） |
| --- | --- | --- |
| `sha` | `1dc6a16b-2fba-4aa1-9519-ea8a6c8c16e5` | 0 準備: `value_input`×3（方式・鍵種別・鍵長） / 1 鍵設定: `memref_input` / 2 IV設定: `memref_input` / 3 MAC計算: `memref_input`, `memref_output` / 4 MAC比較: `memref_input`×2 / 5 ハッシュ計算: `memref_input`, `memref_output`, `value_input`（方式） |
| `ecdsa` | `1945e8e7-0278-4bfb-bb99-af1080b2a934` | 0 ハッシュ計算: `memref_input`, `memref_output`, `value_input`（方式） / 1 鍵生成: パラメータなし / 2 署名と検証: `memref_input`（ハッシュ値）, `memref_output`（署名） |
| `sign_verify` | `f066f150-42af-404f-ae32-c8e6cd117e70` | 0 RSA鍵生成・署名・検証: `memref_input`, `memref_output`, `value_input`（方式 0〜9）, `value_input`（鍵長ビット） |
| `ecdh` | `50c82425-94da-4072-a3e0-58ef063767c0` | 0 鍵共有の自己テスト: `value_input`（曲線 0〜3）, なし, なし, `memref_output`（共有秘密） |

2026-11-15に、4種すべてを実行イメージ（OP-TEE 4.4.0）でビルドし、QEMU上でセッション開始・呼出し・終了が成功することを確認しました。上流は4.11.0向けですが、4.4.0の開発キットでそのままビルドできます。

- `ecdsa`・`sign_verify`・`ecdh` は呼出しごとに鍵を生成するため、署名と共有秘密は実行ごとに変わります。
- `ecdh` は自己テストとして共有秘密をそのまま出力します。正常版の仕様であり、UDOの基準にする際は注意が必要です。

## kmgk の Gatekeeper TA

`gatekeeper` は、Android向けGatekeeperのOP-TEE実装 [linaro-swg/kmgk](https://github.com/linaro-swg/kmgk) の `gatekeeper/ta` の複製です。内容は上流と同一で、変更していません。Android側のHAL（C++）は含めていません。

- 取得元: `https://github.com/linaro-swg/kmgk.git`
- コミット: `b5a86e5ef8fb02381a4d2555f64dc976614e72e3`（2024-10-08、`master`）
- ライセンス: Apache License 2.0（各ファイルの表記による。上流にライセンス全文のファイルはないため、全文を [LICENSE.kmgk](LICENSE.kmgk) に置いています）。
- UUID: `4d573443-6a56-4272-ac6f-2425af9ef9bb`
- コマンド: 0 登録 / 1 照合。どちらも `memref_input`（要求）, `memref_output`（応答）。要求と応答の構造は `gatekeeper_ta.c` のコメントにあります。

2026-11-15に、実行イメージ（OP-TEE 4.4.0）でビルドし、QEMU上で登録1回と照合7回を実行しました。誤ったパスワードの照合は5回目まで拒否（戻り値1、応答 `ERROR_INVALID`）、6回目以降は待機要求（戻り値0、応答 `ERROR_RETRY` と残り時間）になりました。

- 照合前に失敗記録を加算し、成功時に消去します。再登録では現在のパスワードを照合します。試行記録と認可を持つ、同梱TAで唯一の例です。
- ヘッダにKeymaster TAのUUIDも定義されています。ツールは `#define TA_UUID` が指す側をこのTAのUUIDとして使います。
- 照合成功時にKeymaster TAを呼び出します。Keymaster TAは実行イメージにないため、呼出しは失敗し、認証トークンのHMACは0のままになります（戻り値は成功）。
- パスワードハンドルは、TAが起動時に乱数で作る鍵で署名され、起動ごとに変わります。照合を成功させるには、登録の応答（8バイト目から58バイト）を照合の要求（16バイト目）へ `inserts` で複写します。2026-11-15に、この方法で正しいパスワードの照合が成功し、誤ったパスワードが拒否されることを確認しました。
- 登録の応答と照合成功の応答は乱数と時刻を含み、実行ごとに変わります。ハンドルを複写した要求も同様です。R3はこれらのステップを比較から除きます。
- 待機要求の応答は残り時間（ミリ秒）を含み、実行ごとに変わります。R3はこのステップを比較から除きます。
- 上流の保守は止まっています。コードを読んだ範囲で、次の点が正常版に残っています。要求バッファのサイズ検査より前に長さフィールドを読む。失敗記録はメモリ上のみで、セッション開始のたびに全消去する。`TEE_MACComputeFinal` の戻り値を確認しない。

## optee_test 4.4.0 の storage TA

`storage` は、OP-TEE公式テストスイート [OP-TEE/optee_test](https://github.com/OP-TEE/optee_test) の試験用TA `ta/storage` の複製です。ファイルの内容は上流と同一で、変更していません。

- 取得元: `https://github.com/OP-TEE/optee_test.git`
- タグ: `4.4.0`（コミット `695231ef8987866663a9ed5afd8f77d1bae3dc08`）。実行イメージ内の `/opt/optee/optee_test` から複製しました。
- ライセンス: BSD 2-Clause（上流の `LICENSE.md` はTAを `LICENSE-BSD` の対象としています。全文は [LICENSE.optee_test](LICENSE.optee_test)）。
- 配置: 上流の `ta/storage/` を `storage/ta/` に、`ta/ta_common.mk` を `storage/ta_common.mk` に、`ta/include/ta_storage.h` を `storage/include/ta_storage.h` に置いています。相対位置は上流と同じで、ビルド定義の書換えは不要です。
- UUID: `b689f2a7-8adf-477a-9f99-32e90c0ad0a2`（ヘッダには `storage2` のUUIDもあり、`#define TA_UUID` が指す側を使います）。
- コマンド: `include/ta_storage.h` の `TA_STORAGE_CMD_*`。主なものは 0 開く / 4 作成 / 14 上書き作成（いずれも `memref_input`（ID）, `value_inout`（a: フラグ、b: 返るハンドル）, `value_input`, 作成系は `memref_input`（初期データ））、2 読出し / 3 書込み（`memref`, `value`（a: ハンドル））。

2026-11-16に、実行イメージ（OP-TEE 4.4.0）でビルドし、QEMU上で次を確認しました。ID `obj1` の作成は成功し、ハンドル `720288` が返りました（2回の実行で同じ値）。作成したハンドルを開いたまま同じIDを開くと `0xffff0003`、存在しないIDを開くと `0xffff0008` でした。

- 読出し・書込みなどは、開く・作成が返したハンドルを `value` で渡します。入力列では、作成が `b` に返したハンドルを `inserts` で後の入力の `a` へ複写します（[候補の書式](../../docs/candidate-format.md) を参照）。
- OSの試験用TAであり、安全な実装の手本として書かれたものではありません。`*_ID_IN_SHM` のコマンド（22〜25）は、IDを私有領域へコピーせず共有メモリから直接渡します。OP-TEEは共有メモリ上のオブジェクトIDを受け付けず、TAを異常終了させます。上流がその動作を試験するための経路で、正常版に含まれます。
- このため、オブジェクトIDの私有コピーをやめる変更（0・4・7・14）は、通常入力でもTAが異常終了し、DUSの不備になりません（2026-11-16のAI生成3回で確認）。DUSにできるのは書込みデータの私有コピー（3）です。手書きの候補で、作成→書込み→先頭へ移動→読出しの入力列により、R1〜R3の合格を確認しました。
- ハンドルはクライアントから渡された値をそのまま使い、所有者の確認はありません。これも正常版の仕様です。

## optee_os 4.4.0 の AVB TA

`avb` は、Android Verified Bootの状態を保存する [OP-TEE/optee_os の `ta/avb`](https://github.com/OP-TEE/optee_os/tree/8f645256efc0dc66bd5c118778b0b50c44469ae1/ta/avb) の複製です。正常版のソース・ビルド定義は変更していません。

- 取得元: `https://github.com/OP-TEE/optee_os.git`
- タグ: `4.4.0`（コミット `8f645256efc0dc66bd5c118778b0b50c44469ae1`）。実行イメージ内の `/opt/optee/optee_os` から取得しました。
- 配置: 上流の `ta/avb/` の6ファイルを `avb/ta/` に、ルートのライセンスを [avb/LICENSE](avb/LICENSE) に置いています。ライセンスはBSD 2-Clauseです。
- UUID: `023f8f1a-292a-432b-8fc4-de8471358067`。
- 正常版のソースダイジェスト（ライセンスを含む）: `sha256:f6c0800539f837e69033c90c0e990f09608bf4d8a0bbf871198bb1a28936a81a`。

| コマンド | ID | パラメータ |
| --- | --- | --- |
| rollback index読出し | 0 | `value_input`（a: slot）, `value_output`（a: 上位32 bit, b: 下位32 bit） |
| rollback index更新 | 1 | `value_input`（a: slot）, `value_input`（a: 上位32 bit, b: 下位32 bit） |
| lock state読出し・更新 | 2・3 | `value_output` / `value_input`（a: lock state） |
| 名前付き永続値読出し・更新 | 4・5 | `memref_input`（名前）, `memref_output` / `memref_input`（値） |

2026-11-17に、`Dockerfile.rpmb` で構築したOP-TEE 4.4.0 / QEMU環境で正常版のビルド・呼出しを確認しました。初期値0、5への増加、5への同値更新、`2^32 + 7` への増加を読出しで確認し、範囲外slot 256は `TEE_ERROR_BAD_PARAMETERS` でした。2回の実行で観測が一致しました。

- `write_rb_idx` は保存済み値を読んで、更新値が小さければ `TEE_ERROR_SECURITY` を返し、書込みを行いません。これは入力の型・長さ・slotの範囲検査とは別の、保護状態に依存した単調性の制約です。
- ORDER候補では、この検査を消さずに書込みの後へ移動します。正常版と候補は同じエラーを返しますが、後続の読出しで正常版は元の値、候補は拒否された小さい値になります。手書き候補と独立したAI生成の両方でR1〜R3を確認しました。
- 手書き候補（`examples/avb_order.json`）には対照の入力列も入れています。同じ「slot 0 を3へ更新」の呼出しが、初期状態では成功して3が読め、5を保存した後では `TEE_ERROR_SECURITY` で拒否されます。許可・拒否が呼出しのパラメータではなく、それまでの呼出しで保存された値で決まることを、正常版と候補の両方で確認しました。
- `TEE_STORAGE_PRIVATE_RPMB` を指定するため、通常のイメージでは保存機能を実行できません。追加イメージはRPMBエミュレータを使い、各入力列の開始時に保存状態を初期化します。実機の耐リプレイ性、再起動をまたぐ保持、Verified Boot全体の安全性を確認したものではありません。
- 上流の他の経路ではlock stateの変更時にrollback stateを作り直せます。ここで確認した正常性は、状態を作り直さない `write_rb_idx` の入力列に限定します。呼出し元の権限・ブートローダとの統合は、このTA単体のベンチマーク対象外です。
- Foundries.IOのFIOVBはAVBと出自・構造が共通するため、独立したORDER実装数を増やす目的では取り込んでいません。

## 注意

- `random` の出力と `acipher` の暗号文は実行ごとに変わります。R3はこの変動ステップを比較から除くため、これらの出力値そのものを発火観測にする不備は `unknown` になります。
- `plugins` は含めていません。REE側のsyslogプラグインが必要で、実行イメージのrootfsに入っていないためです。
- `host/` は上流のまま置いていますが、このツールは使用しません。呼出しは共通クライアントが行います。
- `sha`・`ecdsa`・`sign_verify`・`ecdh`・`gatekeeper` の `host/` や HAL も、このツールは使用しません。
- 上流のサンプルは学習用であり、不備がないことは保証されません。
