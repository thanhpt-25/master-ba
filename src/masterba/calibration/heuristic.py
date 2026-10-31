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
    "版": "$document.version",
    "版数": "$document.version",
    "バージョン": "$document.version",
    "ver": "$document.version",
    "version": "$document.version",
    "プロジェクト": "$project.id",
    "プロジェクトid": "$project.id",
    "案件": "$project.id",
    "案件名": "$project.id",
    "状態": "$document.status",
    "ステータス": "$document.status",
    "status": "$document.status",
}
VALUE_MAP_FIELDS = {"scope": "scope"}
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


def fields_for(doc_type: DocType) -> set[str]:
    """Item fields of the document type that a column may show."""
    from masterba.rendering.bindings import item_class

    return set(item_class(doc_type).model_fields) - {"status"}
