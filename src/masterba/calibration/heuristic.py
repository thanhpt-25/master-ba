"""Deterministic label matching: sample column headers -> item fields (spec 09 section 3)."""

import re
import unicodedata
from collections.abc import Collection

from masterba.models.enums import DocType

SYNONYMS: dict[str, tuple[str, ...]] = {
    "item_id": ("項目ID", "アイテムID", "item id", "itemid"),
    "requirement_id": (
        "要件ID",
        "要件番号",
        "要求ID",
        "要求番号",
        "requirement id",
        "req id",
        "reqid",
    ),
    "title": ("タイトル", "要件名", "件名", "title"),
    "description": ("要件内容", "内容", "説明", "概要", "description"),
    "scope": ("対象範囲", "範囲", "スコープ", "scope"),
    "source_ref": ("出典", "根拠", "原文", "source"),
    "kind": ("種別", "区分", "種類", "kind", "type"),
    "statement": ("要求記述", "要求内容", "要求", "記述", "statement"),
    "acceptance_hint": ("受入観点", "受入条件", "確認方法", "acceptance"),
    "derives_from": ("派生元", "元要件", "関連要件", "derives from"),
    "realizes": ("実現対象", "対応要件", "realizes"),
    "refines": ("詳細化対象", "refines"),
    "verifies": ("確認対象", "紐付け対象", "紐づけ対象", "verifies"),
    "name": ("機能名", "画面名", "名称", "name"),
    "spec": ("仕様", "詳細", "spec"),
    "test_id": ("テストケースID", "テストID", "ケースID", "test case id", "test id"),
    "level": ("テストレベル", "レベル", "level"),
    "precondition": ("前提条件", "事前条件", "precondition"),
    "input": ("入力値", "入力", "input"),
    "steps": ("操作手順", "手順", "steps"),
    "expected": ("期待結果", "期待値", "expected"),
}
_NUMBER_LABELS = frozenset({"no", "番号", "連番", "通番", "№"})
DOC_INFO: dict[str, str] = {
    "文書id": "$document.id",
    "文書番号": "$document.id",
    "ドキュメントid": "$document.id",
    "ドキュメント番号": "$document.id",
    "版": "$document.version_label",
    "版数": "$document.version_label",
    "バージョン": "$document.version_label",
    "ver": "$document.version_label",
    "version": "$document.version_label",
    "プロジェクト": "$project.id",
    "プロジェクトid": "$project.id",
    "案件": "$project.id",
    "案件名": "$project.id",
    "状態": "$document.status",
    "ステータス": "$document.status",
    "status": "$document.status",
    # spec 28 section 3: every field a cover or an info block usually shows
    "文書名": "$document.title",
    "ドキュメント名": "$document.title",
    "システム名": "$project.name",
    "顧客名": "$project.company",
    "顧客": "$project.company",
    "会社名": "$project.company",
    "作成日": "$document.created_on",
    "更新日": "$document.updated_on",
    "最終更新日": "$document.updated_on",
    "作成者": "$document.author",
    "担当者": "$document.author",
    "承認者": "$document.approver",
    "承認日": "$document.approved_on",
    "機密区分": "$document.classification",
    "発行元": "$document.publisher",
}
# Revision-history columns (spec 28 section 3): label -> `Revision` field.
REVISION_LABELS: dict[str, str] = {
    "版数": "version_label",
    "版": "version_label",
    "改版番号": "version_label",
    "改訂番号": "version_label",
    "バージョン": "version_label",
    "改版日": "date",
    "改訂日": "date",
    "日付": "date",
    "変更日": "date",
    "改版内容": "summary",
    "改訂内容": "summary",
    "変更内容": "summary",
    "内容": "summary",
    "改版理由": "reason",
    "改訂理由": "reason",
    "変更理由": "reason",
    "理由": "reason",
    "改版者": "author",
    "改訂者": "author",
    "作成者": "author",
    "変更者": "author",
    "承認者": "approver",
    "承認日": "approved_on",
    "改版箇所": "changed_sheets",
    "改訂箇所": "changed_sheets",
    "変更箇所": "changed_sheets",
}
REVISION_KEY_FIELD = "version_label"
MIN_REVISION_COLUMNS = 3
VALUE_MAP_FIELDS = {"scope": "scope", "level": "level"}
_STRIP = re.compile(r"[\s\.\:：・、。,;/\\()（）\[\]【】「」\-_*#]+")


def normalise(text: str) -> str:
    """NFKC, lower case, no spaces or punctuation (so 'No.' and 'ＮＯ' both become 'no')."""
    return _STRIP.sub("", unicodedata.normalize("NFKC", text).lower())


_NORMAL_SYNONYMS = {
    field: tuple(sorted({normalise(s) for s in words}, key=len, reverse=True))
    for field, words in SYNONYMS.items()
}


def match_field(text: str, fields: Collection[str]) -> str | None:
    """The field a header most likely names: an exact synonym, else the longest contained one."""
    label = normalise(text)
    if not label:
        return None
    best: tuple[int, str] | None = None
    for field in fields:
        for synonym in _NORMAL_SYNONYMS.get(field, ()):
            if label == synonym:
                return field
            if synonym in label and (best is None or len(synonym) > best[0]):
                best = (len(synonym), field)
    return best[1] if best else None


def is_numbering(text: str) -> bool:
    label = normalise(text)
    return label in _NUMBER_LABELS or text.strip() == "#"


def doc_info_source(text: str) -> str | None:
    return DOC_INFO.get(normalise(text))


_NORMAL_REVISION = {normalise(label): field for label, field in REVISION_LABELS.items()}


def revision_field(text: str) -> str | None:
    """The `Revision` field a revision-history column header names (exact label only)."""
    return _NORMAL_REVISION.get(normalise(text))


def fields_for(doc_type: DocType) -> set[str]:
    """Item fields of the document type that a column may show."""
    from masterba.rendering.bindings import item_class

    return set(item_class(doc_type).model_fields) - {"status"}
