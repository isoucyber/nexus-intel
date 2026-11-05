"""Autoteste do executável empacotado (usado no CI e útil para suporte).

Cria um usuário e um projeto de exemplo numa pasta temporária, confere que o
banco ficou cifrado e que a auditoria está íntegra. Não toca nos dados reais.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NEXUS_INTEL_HOME"] = tmp
        from nexus_intel.application.projects import ProjectManager
        from nexus_intel.application.session import Session
        from nexus_intel.infrastructure.crypto.keys import KdfParams
        from nexus_intel.infrastructure.paths import default_paths

        enc = Session.encryption_supported()
        s = Session(default_paths(), kdf_params=KdfParams(memory_kib=64 * 1024, iterations=2, lanes=2))
        s.setup("autoteste", "senha-de-autoteste-123", encrypt=enc)
        m = ProjectManager(s)
        info = m.create("Autoteste", template="example")
        store = m.open(info.id)
        ok = bool(store.search("veneza")) and store.verify_audit() is None
        m.close_current()
        s.lock()
        raw = Path(info.path).read_bytes()[:16]
        cipher_ok = (raw != b"SQLite format 3\x00") if enc else True
        print(f"sqlcipher={'sim' if enc else 'NAO'} dados={'ok' if ok else 'FALHA'} "
              f"cifragem={'ok' if cipher_ok else 'FALHA'}")
        return 0 if (ok and cipher_ok and enc) else 1
