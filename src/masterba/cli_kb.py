"""`masterba kb ...`: the project knowledge base on the command line (spec 12)."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from masterba.knowledge import (
    HybridRetriever,
    IncomingFile,
    KbError,
    SearchArgumentError,
    add_sources,
    list_sources,
    reindex,
)
from masterba.knowledge.embedder import (
    ModelSetupError,
    RagUnavailableError,
    configured_model,
    rag_available,
    setup_model,
)
from masterba.knowledge.proposal import remove_with_proposal, replace_with_proposal
from masterba.knowledge.retriever import DEFAULT_K
from masterba.knowledge.safety import MAX_FILE_BYTES
from masterba.models.ids import SOURCE_ID_PATTERN
from masterba.trace_store import ProjectStore, open_project

KB_ERRORS = (KbError, SearchArgumentError, RagUnavailableError, ModelSetupError)


def _source_id(value: str) -> str:
    if not re.match(SOURCE_ID_PATTERN, value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a Source_Id like KB-0001")
    return value


def add_kb_parsers(commands: Any, project_id: Any) -> None:
    kb = commands.add_parser("kb", help="the project's knowledge base")
    subs = kb.add_subparsers(dest="kb_command", required=True)

    def with_project(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--project", type=project_id, required=True)
        return parser

    subs.add_parser("setup", help="download the embedding model once").add_argument(
        "--model", default=None
    )
    add = with_project(subs.add_parser("add", help="add files as knowledge sources"))
    add.add_argument("--by", default=None, help="who adds them (default: git user)")
    add.add_argument("files", nargs="+", type=Path)
    with_project(subs.add_parser("list"))
    replace = with_project(subs.add_parser("replace", help="replace a source's file"))
    replace.add_argument("source_id", type=_source_id)
    replace.add_argument("file", type=Path)
    replace.add_argument("--by", default=None)
    with_project(subs.add_parser("remove")).add_argument("source_id", type=_source_id)
    with_project(subs.add_parser("reindex", help="rebuild the index from the sources"))
    search = with_project(subs.add_parser("search"))
    search.add_argument("query")
    search.add_argument("-k", type=int, default=DEFAULT_K)


def _out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def _acting_user(root: Path, given: str | None) -> str:
    if given and given.strip():
        return given.strip()
    name = os.environ.get("GIT_AUTHOR_NAME", "").strip()
    if name:
        return name
    done = subprocess.run(
        ["git", "config", "user.name"], cwd=root, capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def _read(path: Path) -> IncomingFile | str:
    """The file, or the reason it cannot be read."""
    try:
        if not path.is_file():
            return "the file does not exist"
        with path.open("rb") as handle:
            # One byte past the limit is enough for check_upload to refuse it.
            return IncomingFile(path.name, handle.read(MAX_FILE_BYTES + 1))
    except OSError as exc:
        return f"cannot read the file: {exc.strerror or exc}"


def _setup(args: argparse.Namespace) -> int:
    if not rag_available():
        hint = (
            "rebuild the image with --build-arg EXTRAS=rag"
            if os.environ.get("MASTERBA_IN_CONTAINER")
            else "run `uv sync --extra rag`"
        )
        raise RagUnavailableError(f"the rag extra is not installed; {hint}")
    result = setup_model(args.model or configured_model())
    _out(f"model {result.model}: {'downloaded' if result.downloaded else 'already present'}")
    _out(f"cache: {result.cache_path}")
    return 0


def _add(args: argparse.Namespace, store: ProjectStore, root: Path) -> int:
    files: list[IncomingFile] = []
    refused: list[tuple[str, str]] = []
    for path in args.files:
        read = _read(path)
        if isinstance(read, str):
            refused.append((path.name, read))
        else:
            files.append(read)
    if files:
        report = add_sources(store, files, _acting_user(root, args.by))
        for source in report.added:
            state = report.statuses[source.id]
            reason = f" ({state.reason})" if state.reason else ""
            _out(f"added {source.id} {source.file_name}: {state.status}{reason}")
        for name, match in report.skipped:
            _out(f"skipped {name}: same content as {match}")
        refused.extend(report.refused)
        if report.notice:
            _out(f"notice: {report.notice}")
    for name, reason in refused:
        _out(f"refused {name}: {reason}")
    return 1 if refused else 0


def _list(store: ProjectStore) -> int:
    views = list_sources(store)
    if not views:
        _out("the knowledge base is empty")
    for view in views:
        s = view.source
        added = s.added_at.isoformat().replace("+00:00", "Z")
        reason = f" ({view.reason})" if view.reason else ""
        _out(f"{s.id}\t{s.file_name}\t{s.added_by}\t{added}\t{view.status}{reason}")
    return 0


def _proposed(dr: Any) -> None:
    if dr is not None:
        _out(f"proposed {dr.id} for {len(dr.impacted_items)} citing item(s)")


def _replace(args: argparse.Namespace, store: ProjectStore, root: Path) -> int:
    read = _read(args.file)
    if isinstance(read, str):
        raise KbError(f"{args.file.name}: {read}")
    report, dr = replace_with_proposal(store, args.source_id, read, _acting_user(root, args.by))
    reason = f" ({report.status.reason})" if report.status.reason else ""
    _out(f"replaced {args.source_id} with {report.after.file_name}: {report.status.status}{reason}")
    _proposed(dr)
    if report.notice:
        _out(f"notice: {report.notice}")
    return 0


def _remove(args: argparse.Namespace, store: ProjectStore) -> int:
    removed, dr = remove_with_proposal(store, args.source_id)
    _out(f"removed {removed.id} {removed.file_name}")
    _proposed(dr)
    return 0


def _reindex(store: ProjectStore) -> int:
    outcome = reindex(store)
    states = outcome.record.sources
    _out(f"sources indexed: {sum(1 for s in states.values() if s.status == 'indexed')}")
    _out(f"chunks indexed: {outcome.chunk_count}")
    for source_id, state in states.items():
        if state.status == "failed":
            _out(f"failed {source_id}: {state.reason}")
    if outcome.notice:
        _out(f"notice: {outcome.notice}")
    return 0


def _search(args: argparse.Namespace, store: ProjectStore) -> int:
    retriever = HybridRetriever(store)
    passages = retriever.search(args.query, args.k)
    if retriever.mode == "keyword":
        _out("notice: only keyword search was used")
    if not passages:
        _out("no passages matched")
    for rank, passage in enumerate(passages, start=1):
        heading = " › ".join(passage.heading_path) or passage.sheet or ""
        _out(f"{rank}. {passage.chunk_ref}  {heading}".rstrip())
        _out(f"   {passage.text}")
    return 0


def dispatch_kb(args: argparse.Namespace, root: Path) -> int:
    command: str = args.kb_command
    if command == "setup":
        return _setup(args)
    store = open_project(root / "projects", args.project)
    if command == "add":
        return _add(args, store, root)
    if command == "list":
        return _list(store)
    if command == "replace":
        return _replace(args, store, root)
    if command == "remove":
        return _remove(args, store)
    if command == "reindex":
        return _reindex(store)
    return _search(args, store)
