"""Ponto de entrada: `python -m nexus_intel` ou o executável `NexusIntel.exe`."""

from __future__ import annotations

import sys


def main() -> int:
    if "--version" in sys.argv:
        from nexus_intel import __version__

        print(__version__)
        return 0
    if "--self-test" in sys.argv:
        # Verificação rápida do executável empacotado: cripto, banco cifrado e migrações.
        from nexus_intel.selftest import run_self_test

        return run_self_test()
    from nexus_intel.ui.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
