"""Erros de domínio e aplicação com mensagens prontas para o usuário (pt-BR)."""

from __future__ import annotations


class NexusError(Exception):
    """Base. `user_message` é seguro para exibir; nunca contém segredos."""

    user_message = "Ocorreu um erro inesperado."

    def __init__(self, user_message: str | None = None) -> None:
        if user_message:
            self.user_message = user_message
        super().__init__(self.user_message)


class VaultNotInitialized(NexusError):
    user_message = "Nenhum usuário foi criado ainda."


class VaultAlreadyInitialized(NexusError):
    user_message = "O usuário já foi criado neste computador."


class InvalidCredentials(NexusError):
    user_message = "Usuário ou senha incorretos."


class InvalidRecoveryKey(NexusError):
    user_message = "Chave de recuperação inválida."


class ThrottledError(NexusError):
    def __init__(self, wait_seconds: float) -> None:
        self.wait_seconds = wait_seconds
        super().__init__(
            f"Muitas tentativas incorretas. Aguarde {int(wait_seconds) + 1} s para tentar de novo."
        )


class WeakPassword(NexusError):
    pass


class VaultTampered(NexusError):
    user_message = (
        "O arquivo do cofre foi alterado ou está corrompido. "
        "Restaure um backup ou use a chave de recuperação."
    )


class SessionLocked(NexusError):
    user_message = "A sessão está bloqueada."


class EncryptionUnavailable(NexusError):
    user_message = (
        "O componente de criptografia do banco (SQLCipher) não está instalado. "
        "Reinstale o aplicativo ou escolha o modo sem criptografia."
    )


class ProjectNotFound(NexusError):
    user_message = "Projeto não encontrado."


class ProjectLocked(NexusError):
    user_message = "Este projeto já está aberto em outra janela do NEXUS INTEL."


class SchemaTooNew(NexusError):
    user_message = (
        "Este projeto foi criado por uma versão mais nova do NEXUS INTEL. "
        "Atualize o aplicativo para editá-lo."
    )
