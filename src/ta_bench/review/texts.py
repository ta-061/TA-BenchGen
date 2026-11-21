"""Japanese and English wording of the review screen.

Templates and the server call t() with the Japanese text; English is looked up here.
"""
LANGUAGES = ('ja', 'en')

STATUS_LABELS = {
    'ja': {'unreviewed': '未レビュー', 'in_review': '確認中', 'approved': '承認済み', 'rejected': '却下',
           'partially_approved': '一部承認', 'stale': '再確認が必要', 'invalid': '整合性エラー'},
    'en': {'unreviewed': 'Unreviewed', 'in_review': 'In review', 'approved': 'Approved', 'rejected': 'Rejected',
           'partially_approved': 'Partially approved', 'stale': 'Needs re-review', 'invalid': 'Invalid'},
}

ENGLISH = {
    'TA ベンチマークレビュー': 'TA benchmark review',
    '人によるレビュー': 'Human review',
    '機械検証は、保存された入力で挙動が変わることを確認します。分類と位置の妥当性は人が判断します。':
        'Machine validation confirms that behavior changes on the stored inputs. '
        'Whether the class and the location are right is for a person to judge.',
    # index
    '候補の確認': 'Candidates',
    'レビュー対象': 'Cases to review',
    '{cases} ケース / 承認に {n} 名必要': '{cases} cases / {n} reviewer(s) needed to approve',
    'ケース': 'Case', '正常 TA': 'Normal TA', '分類 × 件数': 'Class × count', '機械判定': 'Machine validation',
    'レビュー': 'Review', '整合性': 'Integrity', '確認済み': 'Checked',
    'レビュー対象はまだありません': 'No cases to review yet',
    '機械検証を通過したケースが benchmark/defective/ に保存されると、ここに表示されます。':
        'Cases that pass machine validation and are saved in benchmark/defective/ appear here.',
    # invalid
    '← ケース一覧': '← All cases',
    '整合性の確認が必要です': 'Integrity must be checked',
    'このケースは承認できません。正常版、保存形式、差分、ラベルと検証結果を確認してください。':
        'This case cannot be approved. Check the normal TA, the stored format, the diff, the labels '
        'and the verification record.',
    '保存されたラベル': 'Stored labels', '保存された検証結果': 'Stored verification record',
    # case: header and review form
    'TA レビュー': 'TA review', '正常 TA 不明': 'Normal TA unknown',
    '整合性の警告': 'Integrity warnings', '警告を解消してから承認してください。': 'Resolve the warnings before approving.',
    'レビュー対象が以前の承認時から変わっています。以前のチェックは新しい承認には使用しません。':
        'The case has changed since it was approved. Earlier checks do not count toward a new approval.',
    '確認項目': 'Checks', '差分': 'Diff', '入力と観測': 'Inputs and observations', 'ソース': 'Source', '履歴': 'History',
    '分類・位置・挙動の確認': 'Class, location and behavior',
    '承認には {n} 名の確認が必要です。評価者名は記録用であり、本人認証ではありません。':
        'Approval needs {n} reviewer(s). The reviewer name is a record, not authentication.',
    '評価者名': 'Reviewer', '評価者名を入力': 'Enter your name',
    '生成時の位置': 'Original location', '生成時の位置を確認済み': 'Original location confirmed',
    '人が修正した位置': 'Corrected by a reviewer',
    '「確認を保存・保留」または「この不備を承認」を押しても、入力した位置を一緒に保存します。':
        'Choosing “Save checks (hold)” or “Approve this defect” also saves the location you enter.',
    '正解位置を編集': 'Edit the reference location', '正解位置を保存': 'Save the reference location',
    '不備版のファイル': 'File in the defective source', '関数名': 'Function',
    '開始行': 'First line', '終了行': 'Last line', '開始行と同じ': 'Same as first line',
    '影響操作': 'Affected operation', '保護操作': 'Protection operation',
    '保護操作なし': 'No protection operation',
    '保護操作（ない場合は全欄を空にする）': 'Protection operation (leave all fields empty if absent)',
    'この不備を承認': 'Approve this defect', 'この不備を却下': 'Reject this defect',
    '正解位置の変更履歴': 'Location change history', '変更前': 'Before', '変更後': 'After',
    'ケース全体': 'Whole case', '正解位置の修正はまだありません。': 'No location corrections yet.',
    '承認 {n}/{total} 件': '{n}/{total} defects approved',
    '承認する不備の分類・位置・挙動を確認してください。': 'Confirm the class, location and behavior of each selected defect.',
    '正解位置を保存できません。ファイル・関数・行範囲を確認してください。':
        'Check the file, function and line range for the reference location.',
    '発火入力': 'Witness tests', '分類の定義': 'Class definition', '定義なし': 'No definition',
    '変更理由': 'Reason for the change', '検出器の報告位置': 'Locations a detector should report',
    '帰属する編集単位': 'Edits of this defect', '正常版': 'Normal', '不備版': 'Defective',
    '分類が定義に当てはまる': 'The class matches its definition',
    '報告すべき位置が妥当である': 'The reported locations are right',
    '観測差を不備の結果として説明できる': 'The observed difference is explained by the defect',
    'コメント・却下理由': 'Comment / reason for rejection',
    '却下時は理由が必須です。': 'A reason is required to reject.',
    '確認を保存・保留': 'Save checks (hold)', '確認済みとして承認': 'Approve as checked',
    '理由を付けて却下': 'Reject with a reason', 'チェック変更時に保存します。': 'Checks are saved when changed.',
    # case: diff, observations, source, history
    'ソース比較': 'Source comparison', '比較ファイル': 'Compare file',
    '変更あり': 'Changed', '変更なし': 'Unchanged', '変更箇所の移動': 'Navigate changes',
    '前の変更': 'Previous change', '次の変更': 'Next change', '選択中の変更を表示': 'Show the selected change',
    '変更 {current} / {total}': 'Change {current} of {total}',
    '削除 {n} 行': '{n} deleted', '追加 {n} 行': '{n} added', '対応する行なし': 'No corresponding line',
    '編集': 'Edit', '空のファイルです。': 'Empty file.', '統一差分': 'Unified diff',
    '正常版からの変更': 'Changes from the normal TA',
    '不明': 'unknown',
    '各入力列は正常版・不備版でそれぞれ2回測定しています。同じ版の2回で値が一致しなかった項目（時刻や乱数を含む出力など）は、'
    '正常版・不備版のどちらで起きても比較から除外します。出力バッファは中身が1バイトでも違えば中身全体を除外し、表では ** '
    'で示します（長さは比較します）。それ以外の項目はすべて比較しています。色の付いた行は、比較した項目に正常版と不備版の差があるステップです。':
        'Every test is measured twice on the normal and on the defective TA. Items whose values differ between the two '
        'runs of the same version (outputs with a time or random value, for example) are left out of the comparison, '
        'whichever version they vary in. A buffer whose contents differ in even one byte is left out as a whole and '
        'shown as ** (its size is still compared). All other items are compared. Colored rows are steps where a '
        'compared item differs between the normal and the defective TA.',
    '一致': 'equal', '差あり（ステップ {steps}）': 'different (step {steps})',
    '指定ステップ {n} 以降': 'from witness step {n}', '比較除外あり': 'some items excluded',
    'ステップ': 'Step', '入力': 'Input', '比較から除外した項目': 'Items left out of the comparison',
    '発火': 'witness', '同じ版の2回で不一致': 'differed between two runs of the same version', 'なし': 'none',
    '除外した項目の実測値と反復結果を含む全記録': 'Full record, with the measured values of excluded items and the repeated runs',
    '不備ごとに戻した結果': 'Result of reverting each defect', '不備版ソース': 'Defective source', '評価者の記録': 'Review records',
    'まだレビューされていません。': 'Not reviewed yet.',
    # excluded item labels
    '戻り値': 'return value', 'エラー発生元': 'error origin', 'TA の異常終了': 'TA crash',
    '共有メモリ操作の記録': 'shared-memory event record', '引数全体': 'all parameters',
    '引数 {n} 全体': 'parameter {n} (whole)', '引数 {n} のデータ': 'parameter {n} data',
    '引数 {n} の長さ': 'parameter {n} size', '引数 {n} の値 a': 'parameter {n} value a',
    '引数 {n} の値 b': 'parameter {n} value b', '引数 {n} の {field}': 'parameter {n} {field}',
    # messages
    'ソースまたは差分を読み込めません。整合性の警告を確認してください。':
        'The source or the diff cannot be read. Check the integrity warnings.',
    '評価者名を入力してください。': 'Enter the reviewer name.',
    '却下理由を入力してください。': 'Enter a reason for the rejection.',
    '整合性または機械検証を確認してください。現在のケースはレビューを保存できません。':
        'Check integrity and machine validation. A review cannot be saved for this case now.',
    '表示後にケースが変更されました。再読み込みして確認し直してください。':
        'The case changed after it was shown. Reload and check again.',
    '全不備について分類・位置・挙動を確認してください。': 'Confirm class, location and behavior for every defect.',
    '評価者名を入力してから「確認を保存」を押してください。': 'Enter the reviewer name, then press "Save checks".',
    '保存中…': 'Saving…', '確認を保存しました。': 'Checks saved.',
    '保存できませんでした。再読み込みして整合性を確認してください。': 'Could not save. Reload and check integrity.',
}


def translate(language: str, text: str, **values) -> str:
    """The wording for one language; Japanese is the source text, so unknown keys stay Japanese."""
    if language == 'en':
        text = ENGLISH.get(text, text)
    return text.format(**values) if values else text
