"""Deterministic `.xlsx` serialisation.

openpyxl stamps zip entries with the current time, so identical workbooks would differ byte for
byte. Re-packing with a fixed timestamp makes re-rendering unchanged content a no-op in git.
"""

import re
import zipfile
from io import BytesIO

from openpyxl import Workbook

ZIP_TIME = (2000, 1, 1, 0, 0, 0)
FIXED_MODIFIED = "2000-01-01T00:00:00Z"
# openpyxl overwrites `modified` with the current time inside `save`, so it is patched afterwards.
_MODIFIED = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")


def workbook_bytes(wb: Workbook) -> bytes:
    raw = BytesIO()
    wb.save(raw)
    out = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(raw.getvalue())) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            data = source.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _MODIFIED.sub(rb"\g<1>" + FIXED_MODIFIED.encode() + rb"\g<2>", data)
            target.writestr(entry, data)
    return out.getvalue()
