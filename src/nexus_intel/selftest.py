"""Autoteste do executável empacotado (usado no CI e útil para suporte).

Numa pasta temporária: cria um perfil, um projeto de exemplo com fotografias em
todos os formatos aceitos, exporta para .nexus e importa em outro perfil. Confere
que o banco ficou cifrado, que a auditoria está íntegra e que as fotos voltaram
idênticas. Não toca nos dados reais.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path


def _image(fmt: str) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (32, 24), (120, 60, 200)).save(out, fmt)
    return out.getvalue()


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NEXUS_INTEL_HOME"] = tmp
        from nexus_intel.application.profiles import ProfileManager
        from nexus_intel.application.projects import ProjectManager
        from nexus_intel.application.session import Session
        from nexus_intel.application.sharing import export_project, import_package
        from nexus_intel.infrastructure.crypto.keys import KdfParams
        from nexus_intel.infrastructure.paths import default_paths

        enc = Session.encryption_supported()
        kdf = KdfParams(memory_kib=64 * 1024, iterations=2, lanes=2)
        profiles = ProfileManager(default_paths(), kdf_params=kdf)
        s, _ = profiles.create("Autoteste", "autoteste", "senha-de-autoteste-123", encrypt=enc)
        m = ProjectManager(s)
        info = m.create("Autoteste", template="example")
        store = m.open(info.id)
        ok = bool(store.search("veneza")) and store.verify_audit() is None
        eid = store.search("veneza")[0]["id"]
        imgs = {fmt: _image(fmt) for fmt in ("PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF")}
        for fmt, data in imgs.items():
            store.add_photo(eid, data, f"teste.{fmt.lower()}")
        pkg = export_project(m, store, Path(tmp) / "autoteste.nexus", "senha-do-pacote-123", kdf)
        m.close_current()
        s.lock()
        raw = Path(info.path).read_bytes()[:16]
        cipher_ok = (raw != b"SQLite format 3\x00") if enc else True

        s2, _ = profiles.create("Destino", "destino", "senha-do-destino-123", encrypt=enc)
        m2 = ProjectManager(s2)
        imported = import_package(m2, pkg.path, "senha-do-pacote-123")
        st2 = m2.open(imported.id)
        back = {p["original_name"]: st2.photo_bytes(p["id"]) for p in st2.list_photos(eid)}
        photos_ok = all(back.get(f"teste.{f.lower()}") == d for f, d in imgs.items())
        m2.close_current()
        s2.lock()
        print(f"sqlcipher={'sim' if enc else 'NAO'} dados={'ok' if ok else 'FALHA'} "
              f"cifragem={'ok' if cipher_ok else 'FALHA'} fotos+pacote={'ok' if photos_ok else 'FALHA'}")
        return 0 if (ok and cipher_ok and enc and photos_ok) else 1
