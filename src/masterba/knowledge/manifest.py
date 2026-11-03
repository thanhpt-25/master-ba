"""Reading and serialising `knowledge/manifest.json`."""

import json

from masterba.knowledge.paths import KbPaths
from masterba.models import KbManifest


def load_manifest(paths: KbPaths) -> KbManifest:
    """The Manifest, or an empty one when the file is absent."""
    if not paths.manifest.is_file():
        return KbManifest()
    return KbManifest.model_validate_json(paths.manifest.read_bytes())


def manifest_bytes(manifest: KbManifest) -> bytes:
    # Same layout as every other committed JSON file (trace_store.store._write_json).
    text = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False
    )
    return (text + "\n").encode("utf-8")
