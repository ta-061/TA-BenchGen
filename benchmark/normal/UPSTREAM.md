# 正常対照の出典

| 正常対照 | 上流のソース | 同梱のライセンス・表記 |
| --- | --- | --- |
| `hello_world`、`random`、`aes`、`acipher`、`hotp`、`secure_storage` | [optee_examples 4.4.0](https://github.com/linaro-swg/optee_examples/tree/378dc0db2d5dd279f58a3b6cb3f78ffd6b165035) | [BSD 2-Clause](LICENSE.optee_examples) |
| `sha`、`ecdsa`、`sign_verify`、`ecdh` | [optee_examples 4.11.0](https://github.com/linaro-swg/optee_examples/tree/71e8f3f320eef46a9369700bf30b91d67427d535) | [BSD 2-Clause](LICENSE.optee_examples) |
| `gatekeeper` | [kmgk の Gatekeeper TA](https://github.com/linaro-swg/kmgk/tree/b5a86e5ef8fb02381a4d2555f64dc976614e72e3/gatekeeper/ta) | [Apache License 2.0](LICENSE.kmgk) |
| `storage` | [optee_test 4.4.0 の storage TA](https://github.com/OP-TEE/optee_test/tree/695231ef8987866663a9ed5afd8f77d1bae3dc08/ta/storage) | [BSD 2-Clause](LICENSE.optee_test) |
| `avb` | [optee_os 4.4.0 の AVB TA](https://github.com/OP-TEE/optee_os/tree/8f645256efc0dc66bd5c118778b0b50c44469ae1/ta/avb) | [BSD 2-Clause](avb/LICENSE) |
| `pkcs11` | [optee_os の PKCS#11 TA](https://github.com/OP-TEE/optee_os/tree/d75c42ff2847b090d5b1f11c49067cd41fcc2734/ta/pkcs11) | [TAのライセンス](pkcs11/ta/LICENSE)と[クライアント各ファイルの表記](pkcs11/host/libckteec/) |

個別の著作権・ライセンス表記は各ファイルにあります。`secure_kv` と `shared_record` はこのベンチマーク用の正常対照です。[secure_kv](secure_kv/README.md) · [shared_record](shared_record/README.md)
