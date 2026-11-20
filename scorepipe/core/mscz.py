"""Read and rewrite a MuseScore .mscz container while keeping its display IR editable."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .mscx import MsxcDocument


class MsczArchive:
    """A .mscz is a zip with a main .mscx plus optional styles/settings files."""

    def __init__(
        self,
        names: list[str],
        data: dict[str, bytes],
        mscx_name: str,
        document: MsxcDocument,
    ):
        self.names = names
        self.data = data
        self.mscx_name = mscx_name
        self.document = document

    @classmethod
    def open(cls, path: str | Path) -> "MsczArchive":
        with zipfile.ZipFile(str(path)) as archive:
            names = archive.namelist()
            data = {name: archive.read(name) for name in names}
        mscx_name = _main_score(data, names)
        if mscx_name is None:
            raise ValueError("mscz has no .mscx score")
        root = ElementTree.fromstring(data[mscx_name].decode("utf-8"))
        return cls(names, data, mscx_name, MsxcDocument(root))

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.data[self.mscx_name] = ElementTree.tostring(
            self.document.root, encoding="UTF-8", xml_declaration=True
        )
        with zipfile.ZipFile(str(destination), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in self.names:
                archive.writestr(name, self.data[name])

    def state_hash(self) -> str:
        return self.document.state_hash()


def _main_score(data: dict[str, bytes], names: list[str]) -> str | None:
    container = data.get("META-INF/container.xml")
    if container:
        match = re.search(rb'full-path="([^"]+\.mscx)"', container)
        if match:
            candidate = match.group(1).decode("utf-8")
            if candidate in data:
                return candidate
    return next((name for name in names if name.endswith(".mscx")), None)
