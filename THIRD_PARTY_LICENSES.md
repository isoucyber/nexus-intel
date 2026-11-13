# Licenças de terceiros

| Componente | Licença | Uso |
|---|---|---|
| Qt 6 / PySide6 | LGPL-3.0 | Interface. Distribuído em modo pasta: as bibliotecas do Qt podem ser substituídas pelo usuário. Código-fonte do Qt: https://code.qt.io |
| SQLCipher / sqlcipher3 | BSD-3-Clause / zlib | Banco cifrado |
| SQLite | Domínio público | Banco de dados |
| OpenSSL (via cryptography e SQLCipher) | Apache-2.0 | Criptografia |
| cryptography | Apache-2.0 ou BSD-3-Clause | AES-GCM, HKDF, Argon2id |
| Pydantic | MIT | Validação |
| platformdirs | MIT | Pastas do sistema |
| NumPy | BSD-3-Clause | Layout do grafo |
| Inter (fonte) | SIL OFL 1.1 | Fonte da interface. Nomes internos normalizados para agrupar os pesos |
| JetBrains Mono (fonte) | SIL OFL 1.1 | Fonte monoespaçada para IDs e placas |
| Lucide (ícones) | ISC | Ícones da interface |
| Python | PSF License | Runtime empacotado |

**Opcionais (voz, ADR-0004)** — instalados à parte; não fazem parte do instalador:

| Componente | Licença | Uso |
|---|---|---|
| sounddevice / PortAudio | MIT | Microfone e alto-falante (`pip install "nexus-intel[voz]"`) |
| faster-whisper / CTranslate2 | MIT | Reconhecimento de fala local |
| Whisper small (modelo, conversão Systran) | MIT | Modelo de reconhecimento de fala, baixado por `tools/baixar_voz.py` |
| Vozes Piper pt_BR cadu e jeff | Dados CC0 | Vozes neurais, baixadas por `tools/baixar_voz.py` |
| Piper (piper-tts) e espeak-ng | GPL-3.0 | **Programa separado**, instalado num ambiente próprio e executado como processo externo; o NEXUS não o embute nem o distribui |
| Ollama / LM Studio / llama.cpp | MIT / proprietária / MIT | Mecanismo de IA instalado pelo usuário; o NEXUS só conversa com ele por HTTP local |

Os textos completos das licenças acompanham cada pacote dentro da pasta de instalação. Fontes e ícones: `nexus_intel/ui/assets/LICENSE-*.txt`.
