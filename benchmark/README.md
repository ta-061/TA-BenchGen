# TAベンチマーク

**`defective/` に不備TA 16個（不備ラベル20件）、`normal/` に正常対照10個**を収録しています。検出器の評価には、このうち承認済みの17件とPKCS#11の2件を合わせた19件を使います。ケース全体が人手レビューで却下された4個は [rejected/](rejected/) に保存しています。正常対照は生成要求で指定した9個と、PKCS#11の比較に使うP00です。 [生成要求](../config/requests.production.yaml) · [DUSの追加要求](../config/requests.dus-additional.yaml) · [正常対照の出典](normal/UPSTREAM.md)

## 評価に使う不備の内訳

評価に使う19件を分類別に数えました。影響行（`effect`）は19件すべてにあり、保護行（`protection`）があるのは14件です。UDOは保護処理を持たない不備なので、3件とも影響行だけです。[不備ごとの位置（CSV）](../results/summary/labels.csv) · [採用条件と集計](../results/score.py)

| 分類 | 不備 | 影響行あり | 保護行あり | 影響行のみ | 不備を含む不備TA | レビュー |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| IVW | 9 | 9 | 9 | 0 | 9 | 承認9 |
| UDO | 3 | 3 | 0 | 3 | 3 | 承認3 |
| DUS | 2 | 2 | 1 | 1 | 2 | 承認2 |
| ORDER | 5 | 5 | 4 | 1 | 4 | 承認3、未レビュー2（PKCS#11） |
| **合計** | **19** | **19** | **14** | **5** | **16** | 承認17、未レビュー2 |

不備TAは16個で、うち3個が不備を2件含みます。「不備を含む不備TA」の列は分類ごとに数えているため、合計の16とは一致しません。shaの一部承認ケースは、承認したD1だけを数え、承認時に追加した保護行（`sha_ta.c:83`、[レビュー履歴](defective/case_c4cb059bfbd14ca1/label_history.json)）を含めています。却下したD2と `rejected/` の4個は含めていません。

正常対照ごとの内訳は次のとおりです。数字は不備の件数で、括弧内は保護行を持つ件数です。

| 正常対照 | 不備TA | IVW | UDO | DUS | ORDER | 不備の合計 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| avb | 1 | — | — | — | 1（1） | 1 |
| ecdsa | 2 | 1（1） | 1（0） | — | — | 2 |
| gatekeeper | 4 | 2（2） | — | 1（0） | 2（2） | 5 |
| hotp | 1 | 1（1） | — | — | — | 1 |
| pkcs11 | 1 | — | — | — | 2（1） | 2 |
| secure_storage | 1 | 1（1） | — | — | — | 1 |
| sha | 2 | 2（2） | — | — | — | 2 |
| shared_record | 1 | — | — | 1（1） | — | 1 |
| sign_verify | 3 | 2（2） | 2（0） | — | — | 4 |
| **合計** | **16** | **9（9）** | **3（0）** | **2（1）** | **5（4）** | **19** |

## 不備TAと正常対照の対応表

検出器の評価に使うのは、以下の不備TA 16個です。一部承認のshaはD1のみ、PKCS#11はC1・C2の2件を採用しています。「ID」は検出結果で使う識別子です。[検出結果](../results/README.md)

正常対照は各ケースの `labels.json` に記録された `normal.path` に基づきます。不備の内容は `reason` の要約です。ラベル位置は公開 `detector_targets` の行番号で、「影響」は `effect`、「保護」は `protection` を示します。レビュー欄には保存済みの採否を載せ、履歴があるケースはそのファイルにリンクしています。 `rejected/` の4個は表の末尾にあります。

| ID | 不備TAのソース | 正常対照 | 分類と不備の内容 | ラベル位置 | レビュー | 収録記録 |
| --- | --- | --- | --- | --- | --- | --- |
| T26 | [case_9ab8adeb3dd74fba](defective/case_9ab8adeb3dd74fba/source/) | [avb](normal/avb/) | **D1 ORDER** ロールバックインデックスを値の検査前に保存し、拒否された要求でも保存状態が変わる。 | 影響 [entry.c:166](defective/case_9ab8adeb3dd74fba/source/ta/entry.c#L166)、保護 [entry.c:170](defective/case_9ab8adeb3dd74fba/source/ta/entry.c#L170) | [全件承認](defective/case_9ab8adeb3dd74fba/label_history.json) | [ラベル](defective/case_9ab8adeb3dd74fba/labels.json) · [差分](defective/case_9ab8adeb3dd74fba/changes.diff) · [検証](defective/case_9ab8adeb3dd74fba/verification.json) |
| T18 | [case_19b7f03571ec46b1](defective/case_19b7f03571ec46b1/source/) | [ecdsa](normal/ecdsa/) | **D1 IVW** ECDSA署名の必要容量を過小評価し、署名のコピーが出力バッファの範囲を越える。 | 影響 [ecdsa_ta.c:293](defective/case_19b7f03571ec46b1/source/ta/ecdsa_ta.c#L293)、保護 [ecdsa_ta.c:286](defective/case_19b7f03571ec46b1/source/ta/ecdsa_ta.c#L286) | [全件承認](defective/case_19b7f03571ec46b1/label_history.json) | [ラベル](defective/case_19b7f03571ec46b1/labels.json) · [差分](defective/case_19b7f03571ec46b1/changes.diff) · [検証](defective/case_19b7f03571ec46b1/verification.json) |
| T35 | [case_edd8fccc76624196](defective/case_edd8fccc76624196/source/) | [ecdsa](normal/ecdsa/) | **D1 UDO** ECDSA署名の応答に秘密鍵を平文で付け加える。 | 影響 [ecdsa_ta.c:297](defective/case_edd8fccc76624196/source/ta/ecdsa_ta.c#L297) | [全件承認](defective/case_edd8fccc76624196/label_history.json) | [ラベル](defective/case_edd8fccc76624196/labels.json) · [差分](defective/case_edd8fccc76624196/changes.diff) · [検証](defective/case_edd8fccc76624196/verification.json) |
| T21 | [case_427eec3671c74536](defective/case_427eec3671c74536/source/) | [gatekeeper](normal/gatekeeper/) | **D1 IVW** パスワード長の検査に実際の入力バッファの容量を使わず、認証処理がバッファの範囲外を読み込む。 | 影響 [gatekeeper_ta.c:214](defective/case_427eec3671c74536/source/ta/gatekeeper_ta.c#L214)、保護 [gatekeeper_ta.c:624](defective/case_427eec3671c74536/source/ta/gatekeeper_ta.c#L624) | [全件承認](defective/case_427eec3671c74536/label_history.json) | [ラベル](defective/case_427eec3671c74536/labels.json) · [差分](defective/case_427eec3671c74536/changes.diff) · [検証](defective/case_427eec3671c74536/verification.json) |
| T24 | [case_684c4bfe44b04d86](defective/case_684c4bfe44b04d86/source/) | [gatekeeper](normal/gatekeeper/) | **D1 IVW** 登録応答の容量検査が固定値に依存し、実際の出力バッファの範囲を越えて書き込む。<br>**D2 ORDER** 登録時に試行制限を確認する前に失敗記録を消すため、試行制限が機能しない。 | **D1** 影響 [gatekeeper_ta.c:543–544](defective/case_684c4bfe44b04d86/source/ta/gatekeeper_ta.c#L543-L544)、保護 [gatekeeper_ta.c:455](defective/case_684c4bfe44b04d86/source/ta/gatekeeper_ta.c#L455)<br>**D2** 影響 [gatekeeper_ta.c:493](defective/case_684c4bfe44b04d86/source/ta/gatekeeper_ta.c#L493)、保護 [gatekeeper_ta.c:496](defective/case_684c4bfe44b04d86/source/ta/gatekeeper_ta.c#L496) | [全件承認](defective/case_684c4bfe44b04d86/label_history.json) | [ラベル](defective/case_684c4bfe44b04d86/labels.json) · [差分](defective/case_684c4bfe44b04d86/changes.diff) · [検証](defective/case_684c4bfe44b04d86/verification.json) |
| T28 | [case_b9e19bc717204a6f](defective/case_b9e19bc717204a6f/source/) | [gatekeeper](normal/gatekeeper/) | **D1 ORDER** パスワード照合前に失敗記録を消すため、試行制限に必要な回数が蓄積しない。 | 影響 [gatekeeper_ta.c:672](defective/case_b9e19bc717204a6f/source/ta/gatekeeper_ta.c#L672)、保護 [gatekeeper_ta.c:675](defective/case_b9e19bc717204a6f/source/ta/gatekeeper_ta.c#L675) | [全件承認](defective/case_b9e19bc717204a6f/label_history.json) | [ラベル](defective/case_b9e19bc717204a6f/labels.json) · [差分](defective/case_b9e19bc717204a6f/changes.diff) · [検証](defective/case_b9e19bc717204a6f/verification.json) |
| T36 | [case_edc7a9e855a140d7](defective/case_edc7a9e855a140d7/source/) | [gatekeeper](normal/gatekeeper/) | **D1 DUS** 照合の直前にパスワード長を共有メモリから読み直すため、検査後に書き換えられた長さでバッファの範囲外を読み込む。 | 影響 [gatekeeper_ta.c:672](defective/case_edc7a9e855a140d7/source/ta/gatekeeper_ta.c#L672) | [全件承認](defective/case_edc7a9e855a140d7/label_history.json) | [ラベル](defective/case_edc7a9e855a140d7/labels.json) · [差分](defective/case_edc7a9e855a140d7/changes.diff) · [検証](defective/case_edc7a9e855a140d7/verification.json) |
| T22 | [case_4c9c820bfad042e7](defective/case_4c9c820bfad042e7/source/) | [hotp](normal/hotp/) | **D1 IVW** 共有鍵用バッファの容量を超える鍵を受理し、セッション状態を書き換える範囲外書き込みが生じる。 | 影響 [hotp_ta.c:153](defective/case_4c9c820bfad042e7/source/ta/hotp_ta.c#L153)、保護 [hotp_ta.c:149](defective/case_4c9c820bfad042e7/source/ta/hotp_ta.c#L149) | [全件承認](defective/case_4c9c820bfad042e7/label_history.json) | [ラベル](defective/case_4c9c820bfad042e7/labels.json) · [差分](defective/case_4c9c820bfad042e7/changes.diff) · [検証](defective/case_4c9c820bfad042e7/verification.json) |
| T33 | [case_e264a169df23d680](defective/case_e264a169df23d680/source/) | [pkcs11](normal/pkcs11/) | **D1 ORDER・C1** 試行状態の保存が成功する前に、PINの正誤に依存する結果が観測され得る。<br>**D2 ORDER・C2** 変更前のポリシーで認可を得る前に、初期化済みトークンの認証状態を変更する。 | **D1** 影響 [pkcs11_token.c:1207](defective/case_e264a169df23d680/source/ta/src/pkcs11_token.c#L1207)、保護 [pkcs11_token.c:1225](defective/case_e264a169df23d680/source/ta/src/pkcs11_token.c#L1225)<br>**D2** 影響 [pkcs11_token.c:884](defective/case_e264a169df23d680/source/ta/src/pkcs11_token.c#L884) | 未レビュー | [ラベル](defective/case_e264a169df23d680/labels.json) · [差分](defective/case_e264a169df23d680/changes.diff) · [検証](defective/case_e264a169df23d680/verification.json) |
| T17 | [case_061088fe19e546b2](defective/case_061088fe19e546b2/source/) | [secure_storage](normal/secure_storage/) | **D1 IVW** 永続オブジェクトを読み出す際のサイズ検査が不十分で、バッファの範囲を越えて書き込む。 | 影響 [secure_storage_ta.c:211–212](defective/case_061088fe19e546b2/source/ta/secure_storage_ta.c#L211-L212)、保護 [secure_storage_ta.c:201](defective/case_061088fe19e546b2/source/ta/secure_storage_ta.c#L201) | [全件承認](defective/case_061088fe19e546b2/label_history.json) | [ラベル](defective/case_061088fe19e546b2/labels.json) · [差分](defective/case_061088fe19e546b2/changes.diff) · [検証](defective/case_061088fe19e546b2/verification.json) |
| T27 | [case_b1818f0fd5ae4f9e](defective/case_b1818f0fd5ae4f9e/source/) | [sha](normal/sha/) | **D1 IVW** 割当容量を超える出力長をMAC計算に渡し、バッファの範囲外に書き込む。 | 影響 [sha_ta.c:365–366](defective/case_b1818f0fd5ae4f9e/source/ta/sha_ta.c#L365-L366)、保護 [sha_ta.c:357](defective/case_b1818f0fd5ae4f9e/source/ta/sha_ta.c#L357) | [全件承認](defective/case_b1818f0fd5ae4f9e/label_history.json) | [ラベル](defective/case_b1818f0fd5ae4f9e/labels.json) · [差分](defective/case_b1818f0fd5ae4f9e/changes.diff) · [検証](defective/case_b1818f0fd5ae4f9e/verification.json) |
| T30 | [case_c4cb059bfbd14ca1](defective/case_c4cb059bfbd14ca1/source/) | [sha](normal/sha/) | **D1 IVW** ダイジェストの出力長と実際の出力容量が合わず、バッファの範囲外に書き込む。<br>**D2 UDO** ダイジェストの応答にセッション内の鍵素材を平文で付け加える。 | **D1** 影響 [sha_ta.c:104](defective/case_c4cb059bfbd14ca1/source/ta/sha_ta.c#L104)<br>**D2** 影響 [sha_ta.c:110](defective/case_c4cb059bfbd14ca1/source/ta/sha_ta.c#L110) | [一部承認](defective/case_c4cb059bfbd14ca1/label_history.json)<br>D1承認・D2却下 | [ラベル](defective/case_c4cb059bfbd14ca1/labels.json) · [差分](defective/case_c4cb059bfbd14ca1/changes.diff) · [検証](defective/case_c4cb059bfbd14ca1/verification.json) |
| T31 | [case_c893fb83418c44fd](defective/case_c893fb83418c44fd/source/) | [shared_record](normal/shared_record/) | **D1 DUS** 検査後に共有メモリから値を読み直すため、検査した値とレコードに保存する値が異なり得る。 | 影響 [entry.c:25](defective/case_c893fb83418c44fd/source/ta/entry.c#L25)、保護 [entry.c:23](defective/case_c893fb83418c44fd/source/ta/entry.c#L23) | [全件承認](defective/case_c893fb83418c44fd/label_history.json) | [ラベル](defective/case_c893fb83418c44fd/labels.json) · [差分](defective/case_c893fb83418c44fd/changes.diff) · [検証](defective/case_c893fb83418c44fd/verification.json) |
| T19 | [case_1ac4b6f08ebd405a](defective/case_1ac4b6f08ebd405a/source/) | [sign_verify](normal/sign_verify/) | **D1 UDO** RSA署名の応答に秘密指数を平文で含める。 | 影響 [sign_verify_ta.c:245–246](defective/case_1ac4b6f08ebd405a/source/ta/sign_verify_ta.c#L245-L246) | [全件承認](defective/case_1ac4b6f08ebd405a/label_history.json) | [ラベル](defective/case_1ac4b6f08ebd405a/labels.json) · [差分](defective/case_1ac4b6f08ebd405a/changes.diff) · [検証](defective/case_1ac4b6f08ebd405a/verification.json) |
| T20 | [case_2509fc67e11f4a0d](defective/case_2509fc67e11f4a0d/source/) | [sign_verify](normal/sign_verify/) | **D1 IVW** RSA署名の必要容量を過小評価し、署名のコピーが出力バッファの範囲を越える。 | 影響 [sign_verify_ta.c:240](defective/case_2509fc67e11f4a0d/source/ta/sign_verify_ta.c#L240)、保護 [sign_verify_ta.c:233](defective/case_2509fc67e11f4a0d/source/ta/sign_verify_ta.c#L233) | [全件承認](defective/case_2509fc67e11f4a0d/label_history.json) | [ラベル](defective/case_2509fc67e11f4a0d/labels.json) · [差分](defective/case_2509fc67e11f4a0d/changes.diff) · [検証](defective/case_2509fc67e11f4a0d/verification.json) |
| T34 | [case_e8b4365cf5a3481c](defective/case_e8b4365cf5a3481c/source/) | [sign_verify](normal/sign_verify/) | **D1 IVW** RSA署名の出力バッファの容量検査が省略され、署名のコピーがバッファの範囲を越える。<br>**D2 UDO** RSA署名の応答に秘密鍵の素因数を平文で含める。 | **D1** 影響 [sign_verify_ta.c:240](defective/case_e8b4365cf5a3481c/source/ta/sign_verify_ta.c#L240)、保護 [sign_verify_ta.c:233](defective/case_e8b4365cf5a3481c/source/ta/sign_verify_ta.c#L233)<br>**D2** 影響 [sign_verify_ta.c:245](defective/case_e8b4365cf5a3481c/source/ta/sign_verify_ta.c#L245) | [全件承認](defective/case_e8b4365cf5a3481c/label_history.json) | [ラベル](defective/case_e8b4365cf5a3481c/labels.json) · [差分](defective/case_e8b4365cf5a3481c/changes.diff) · [検証](defective/case_e8b4365cf5a3481c/verification.json) |
| — | [case_8ee54fbfc3364928](rejected/case_8ee54fbfc3364928/source/) | [aes](normal/aes/) | **D1 UDO** 短い入力の暗号化を省略し、平文のまま返す。 | 影響 [aes_ta.c:357–358](rejected/case_8ee54fbfc3364928/source/ta/aes_ta.c#L357-L358)、保護 [aes_ta.c:366](rejected/case_8ee54fbfc3364928/source/ta/aes_ta.c#L366) | [却下](rejected/case_8ee54fbfc3364928/label_history.json) | [ラベル](rejected/case_8ee54fbfc3364928/labels.json) · [差分](rejected/case_8ee54fbfc3364928/changes.diff) · [検証](rejected/case_8ee54fbfc3364928/verification.json) |
| — | [case_bbeac31ee64a446a](rejected/case_bbeac31ee64a446a/source/) | [hotp](normal/hotp/) | **D1 UDO** HOTPの応答に共有鍵の一部を平文で含める。 | 影響 [hotp_ta.c:192–194](rejected/case_bbeac31ee64a446a/source/ta/hotp_ta.c#L192-L194) | [却下](rejected/case_bbeac31ee64a446a/label_history.json) | [ラベル](rejected/case_bbeac31ee64a446a/labels.json) · [差分](rejected/case_bbeac31ee64a446a/changes.diff) · [検証](rejected/case_bbeac31ee64a446a/verification.json) |
| — | [case_c8a67e91786a479f](rejected/case_c8a67e91786a479f/source/) | [secure_storage](normal/secure_storage/) | **D1 DUS** オブジェクトIDを私有領域へコピーした後、共有メモリから取り直すため、使用するIDが変わり得る。 | 影響 [secure_storage_ta.c:179](rejected/case_c8a67e91786a479f/source/ta/secure_storage_ta.c#L179)、保護 [secure_storage_ta.c:172](rejected/case_c8a67e91786a479f/source/ta/secure_storage_ta.c#L172) | [却下](rejected/case_c8a67e91786a479f/label_history.json) | [ラベル](rejected/case_c8a67e91786a479f/labels.json) · [差分](rejected/case_c8a67e91786a479f/changes.diff) · [検証](rejected/case_c8a67e91786a479f/verification.json) |
| — | [case_59069f72fe80459a](rejected/case_59069f72fe80459a/source/) | [sha](normal/sha/) | **D1 UDO** MACの応答に秘密鍵を平文で含める。 | 影響 [sha_ta.c:372–375](rejected/case_59069f72fe80459a/source/ta/sha_ta.c#L372-L375) | [却下](rejected/case_59069f72fe80459a/label_history.json) | [ラベル](rejected/case_59069f72fe80459a/labels.json) · [差分](rejected/case_59069f72fe80459a/changes.diff) · [検証](rejected/case_59069f72fe80459a/verification.json) |

## ケースの読み方

不備TAのソースは `source/`、正常対照との差分は `changes.diff` にあります。`labels.json` は分類・検出位置・対応する編集・ケース全体の承認状態を収録しています。`label_history.json` は位置の修正前後、評価者の判断・コメント、承認時の照合用ハッシュを記録します。`verification.json` では検証環境、両版の観測結果、判定を確認できます。

`labels.json` の `defects` に、不備を `D1`、`D2` のように個別に記録します。`edits` はその不備に対応する変更箇所です。`detector_targets` は検出器の報告と照合する位置で、不備TAのファイル・関数・行範囲（1始まり、両端を含む）を指します。`effect` は影響が生じる操作、`protection` は該当経路に残る保護操作です。[分類の定義](../config/classes.yaml)

## 検証結果とレビュー状態

生成ケースでは、通常入力で両版の観測が一致すること（R1）、不備を調べる入力では指定ステップ以降に差が現れること（R2）、反復実行でも安定した項目に差が残ること（R3）を確認します。複数の不備を含むケースでは、不備を一つずつ戻した場合の観測も記録します。

`labels.json` の `review.status` は、全不備を承認したケースで `approved`、それ以外で `unreviewed` です。レビュー中の検出位置は画面で確認でき、公開ラベルには生成時または直近の承認時の位置が残ります。不備ごとの判断は `label_history.json` の `review.per_defect`、操作やコメントは `review.reviews` に記録されます。

生成ケースは全件承認14個と一部承認1個が `defective/`、ケース全体を却下した4個が `rejected/` にあります。既定のブラインド出力は全件承認の14個が対象です。`--include-unreviewed` を指定すると、一部承認を含む15個が対象になります。

PKCS#11の1個には、ユーザーPINの試行記録とトークンの再初期化に関する2件の `ORDER` ラベル（C1・C2）があります。`verification.json` は専用の `pkcs11-controlled-1` 形式で、正常対照と不備TAについて各8シナリオの観測を収録しています。このケースのラベルと観測は同梱ファイルから参照できます。[位置ラベル](defective/case_e264a169df23d680/labels.json) · [検証記録](defective/case_e264a169df23d680/verification.json)
