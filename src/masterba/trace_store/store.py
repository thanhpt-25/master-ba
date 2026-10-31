"""File-based project store (specs/01-data-contracts.md sections 3-4).

Every business action writes files under ``projects/<project_id>/`` and is
recorded as exactly one git commit (specs/00-constitution.md section 5).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from masterba.models import (
    LEVEL_BY_TEST_TYPE,
    PAYLOAD_BY_TYPE,
    DecisionRecord,
    Document,
    Payload,
    ProjectConfig,
    RequirementItem,
    TestSpecContent,
    TraceLink,
    payload_items,
)
from masterba.models.enums import DocType, ItemStatus
from masterba.models.ids import doc_type_of
from masterba.trace_store.errors import (
    DuplicateIdError,
    IdStabilityError,
    InvalidDocumentError,
    NotFoundError,
)
from masterba.trace_store.git import commit_paths

_DOC_FILE = re.compile(r"^(?P<id>DOC-[A-Z_]+-\d{4})\.v(?P<version>\d+)\.json$")
_INTAKE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(txt|md)$")


@dataclass(frozen=True)
class ProjectStore:
    root: Path
    project_id: str

    @property
    def path(self) -> Path:
        return self.root / self.project_id


def _data(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _commit(store: ProjectStore, paths: list[Path], message: str) -> None:
    commit_paths(store.root, paths, message)


def create_project(root: Path, config: ProjectConfig) -> ProjectStore:
    store = ProjectStore(root, config.project_id)
    config_path = store.path / "project.json"
    if config_path.exists():
        raise DuplicateIdError(f"project {config.project_id} already exists")
    _write_json(config_path, _data(config))
    _commit(store, [config_path], f"project({store.project_id}): create")
    return store


def open_project(root: Path, project_id: str) -> ProjectStore:
    store = ProjectStore(root, project_id)
    if not (store.path / "project.json").exists():
        raise NotFoundError(f"project {project_id} does not exist")
    return store


def get_config(store: ProjectStore) -> ProjectConfig:
    return ProjectConfig.model_validate(_read_json(store.path / "project.json"))


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _intake_path(store: ProjectStore, name: str) -> Path:
    if not _INTAKE_NAME.match(name):
        raise InvalidDocumentError(f"invalid intake name {name!r}; use a .txt or .md file name")
    return store.path / "intake" / name


def add_intake(store: ProjectStore, name: str, text: str) -> str:
    """Store an immutable intake text; return its project-relative path ``intake/<name>``."""
    path = _intake_path(store, name)
    if path.exists():
        raise DuplicateIdError(f"intake {name} already exists (intake is immutable)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize_text(text), encoding="utf-8")
    _commit(store, [path], f"intake({store.project_id}): add {name}")
    return f"intake/{name}"


def get_intake(store: ProjectStore, name: str) -> str:
    path = _intake_path(store, name)
    if not path.exists():
        raise NotFoundError(f"intake {name} does not exist")
    return path.read_text(encoding="utf-8")


def _requirement_path(store: ProjectStore, req_id: str) -> Path:
    return store.path / "requirements" / f"{req_id}.json"


def add_requirement(store: ProjectStore, req: RequirementItem) -> None:
    path = _requirement_path(store, req.id)
    if path.exists():
        raise DuplicateIdError(f"{req.id} already exists (ids are never reused)")
    if req.parent_id and not _requirement_path(store, req.parent_id).exists():
        raise NotFoundError(f"parent {req.parent_id} does not exist")
    _write_json(path, _data(req))
    _commit(store, [path], f"req({store.project_id}): add {req.id}")


def update_requirement(store: ProjectStore, req: RequirementItem) -> None:
    """Rewrite an existing requirement (same id) as one commit; ids are never changed."""
    path = _requirement_path(store, req.id)
    if not path.exists():
        raise NotFoundError(f"{req.id} does not exist")
    _write_json(path, _data(req))
    _commit(store, [path], f"req({store.project_id}): update {req.id}")


def get_requirement(store: ProjectStore, req_id: str) -> RequirementItem:
    path = _requirement_path(store, req_id)
    if not path.exists():
        raise NotFoundError(f"{req_id} does not exist")
    return RequirementItem.model_validate(_read_json(path))


def list_requirements(store: ProjectStore) -> list[RequirementItem]:
    folder = store.path / "requirements"
    if not folder.exists():
        return []
    return [
        RequirementItem.model_validate(_read_json(p)) for p in sorted(folder.glob("REQ-*.json"))
    ]


def _doc_dir(store: ProjectStore, doc_type: DocType) -> Path:
    return store.path / "json" / doc_type.value.lower()


def _doc_versions(store: ProjectStore, doc_id: str) -> list[int]:
    folder = _doc_dir(store, DocType(doc_type_of(doc_id)))
    if not folder.exists():
        return []
    versions: list[int] = []
    for path in folder.glob(f"{doc_id}.v*.json"):
        match = _DOC_FILE.match(path.name)
        if match and match["id"] == doc_id:
            versions.append(int(match["version"]))
    return sorted(versions)


def get_document(
    store: ProjectStore, doc_id: str, version: int | None = None
) -> tuple[Document, Payload]:
    versions = _doc_versions(store, doc_id)
    chosen = version if version is not None else (versions[-1] if versions else None)
    if chosen is None or chosen not in versions:
        raise NotFoundError(f"{doc_id} version {version or 'latest'} does not exist")
    folder = _doc_dir(store, DocType(doc_type_of(doc_id)))
    raw = _read_json(folder / f"{doc_id}.v{chosen}.json")
    doc = Document.model_validate(raw["document"])
    return doc, PAYLOAD_BY_TYPE[doc.type].model_validate(raw["content"])


def latest_documents(store: ProjectStore) -> list[tuple[Document, Payload]]:
    json_dir = store.path / "json"
    if not json_dir.exists():
        return []
    ids = {
        match["id"] for path in json_dir.glob("*/*.json") if (match := _DOC_FILE.match(path.name))
    }
    return [get_document(store, doc_id) for doc_id in sorted(ids)]


def _check_id_stability(previous: Payload, new: Payload) -> None:
    prev = {i.item_id: i for i in payload_items(previous)}
    cur = {i.item_id: i for i in payload_items(new)}
    dropped = sorted(prev.keys() - cur.keys())
    if dropped:
        raise IdStabilityError(f"item ids dropped: {dropped}; mark them status=removed instead")
    revived = sorted(
        item_id
        for item_id, item in prev.items()
        if item.status is ItemStatus.REMOVED and cur[item_id].status is ItemStatus.ACTIVE
    )
    if revived:
        raise IdStabilityError(f"removed item ids cannot be revived: {revived}")


def _validate_new_document(store: ProjectStore, doc: Document, content: Payload) -> list[int]:
    if doc.project_id != store.project_id:
        raise InvalidDocumentError(f"document belongs to {doc.project_id}, not {store.project_id}")
    if not isinstance(content, PAYLOAD_BY_TYPE[doc.type]):
        raise InvalidDocumentError(f"payload {type(content).__name__} does not fit {doc.type}")
    expected_ref = f"json/{doc.type.value.lower()}/{doc.id}.v{doc.version}.json"
    if doc.content_ref != expected_ref:
        raise InvalidDocumentError(f"content_ref must be {expected_ref}")
    versions = _doc_versions(store, doc.id)
    expected_version = (versions[-1] if versions else 0) + 1
    if doc.version != expected_version:
        raise InvalidDocumentError(f"expected version {expected_version}, got {doc.version}")
    ids = [item.item_id for item in payload_items(content)]
    if len(ids) != len(set(ids)):
        raise InvalidDocumentError("duplicate item ids in payload")
    foreign = [i for i in ids if not i.startswith(f"{doc.id}#item.")]
    if foreign:
        raise InvalidDocumentError(f"item ids must start with {doc.id}#item.: {foreign}")
    if isinstance(content, TestSpecContent):
        level = LEVEL_BY_TEST_TYPE[doc.type]
        wrong = [t.test_id for t in content.items if t.level is not level]
        if wrong:
            raise InvalidDocumentError(f"test cases {wrong} are not level {level}")
        test_ids = [t.test_id for t in content.items]
        if len(test_ids) != len(set(test_ids)):
            raise InvalidDocumentError("duplicate test ids in payload")
    return versions


def add_document(store: ProjectStore, doc: Document, content: Payload) -> None:
    versions = _validate_new_document(store, doc, content)
    if versions:
        _check_id_stability(get_document(store, doc.id, versions[-1])[1], content)
    path = _doc_dir(store, doc.type) / f"{doc.id}.v{doc.version}.json"
    _write_json(path, {"document": _data(doc), "content": _data(content)})
    _commit(store, [path], f"doc({store.project_id}): create {doc.id} v{doc.version}")


def known_nodes(store: ProjectStore) -> dict[str, str]:
    """Map every traceable id to its kind: requirement, document, item, test_case, test_id."""
    nodes: dict[str, str] = {r.id: "requirement" for r in list_requirements(store)}
    for doc, content in latest_documents(store):
        nodes[doc.id] = "document"
        is_test = doc.type in LEVEL_BY_TEST_TYPE
        for item in payload_items(content):
            nodes[item.item_id] = "test_case" if is_test else "item"
        if isinstance(content, TestSpecContent):
            for case in content.items:
                nodes[case.test_id] = "test_id"
    return nodes


def _links_path(store: ProjectStore) -> Path:
    return store.path / "traceability" / "links.json"


def get_trace_links(store: ProjectStore) -> list[TraceLink]:
    path = _links_path(store)
    if not path.exists():
        return []
    return [TraceLink.model_validate(raw) for raw in _read_json(path)]


def add_trace_link(store: ProjectStore, link: TraceLink) -> None:
    known = known_nodes(store)
    missing = [end for end in (link.from_id, link.to_id) if end not in known]
    if missing:
        raise NotFoundError(f"unknown trace endpoints: {missing}")
    links = get_trace_links(store)
    if link in links:
        raise DuplicateIdError(f"link {link.from_id} -> {link.to_id} ({link.link_type}) exists")
    ordered = sorted([*links, link], key=lambda x: (x.from_id, x.to_id, x.link_type.value))
    path = _links_path(store)
    _write_json(path, [_data(x) for x in ordered])
    _commit(store, [path], f"trace({store.project_id}): link {link.from_id} -> {link.to_id}")


def _dr_path(store: ProjectStore, dr_id: str) -> Path:
    return store.path / "decision-records" / f"{dr_id}.json"


def add_decision_record(store: ProjectStore, dr: DecisionRecord) -> None:
    path = _dr_path(store, dr.id)
    if path.exists():
        raise DuplicateIdError(f"{dr.id} already exists")
    _write_json(path, _data(dr))
    _commit(store, [path], f"dr({store.project_id}): create {dr.id}")


def get_decision_record(store: ProjectStore, dr_id: str) -> DecisionRecord:
    path = _dr_path(store, dr_id)
    if not path.exists():
        raise NotFoundError(f"{dr_id} does not exist")
    return DecisionRecord.model_validate(_read_json(path))


def list_decision_records(store: ProjectStore) -> list[DecisionRecord]:
    folder = store.path / "decision-records"
    if not folder.exists():
        return []
    return [
        DecisionRecord.model_validate(_read_json(p)) for p in sorted(folder.glob("DR-????.json"))
    ]


def _dr_extra_path(store: ProjectStore, dr_id: str, suffix: str) -> Path:
    return store.path / "decision-records" / f"{dr_id}.{suffix}.json"


def get_dr_extra(store: ProjectStore, dr_id: str, suffix: str) -> Any | None:
    """Derived data stored next to a DR (``impact``, ``propagation``); None when absent."""
    path = _dr_extra_path(store, dr_id, suffix)
    return _read_json(path) if path.exists() else None


def write_dr_extra(store: ProjectStore, dr_id: str, suffix: str, data: Any, message: str) -> None:
    """Write one derived DR file as its own commit with the given message."""
    path = _dr_extra_path(store, dr_id, suffix)
    _write_json(path, data)
    _commit(store, [path], message)


def save_decision_record(
    store: ProjectStore,
    dr: DecisionRecord,
    action: str,
    extras: Mapping[str, Any] | None = None,
) -> None:
    """Rewrite an existing DR (and any derived files) as one commit ``dr(P): <action> <id>``."""
    path = _dr_path(store, dr.id)
    if not path.exists():
        raise NotFoundError(f"{dr.id} does not exist")
    _write_json(path, _data(dr))
    paths = [path]
    for suffix, data in (extras or {}).items():
        extra = _dr_extra_path(store, dr.id, suffix)
        _write_json(extra, data)
        paths.append(extra)
    _commit(store, paths, f"dr({store.project_id}): {action} {dr.id}")
