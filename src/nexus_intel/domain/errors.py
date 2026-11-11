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


class InvalidImage(NexusError):
    user_message = "O arquivo não é uma imagem válida em um formato aceito (JPG, PNG, WEBP, GIF, BMP ou TIFF)."


class AttachmentTooLarge(NexusError):
    user_message = "A imagem é grande demais (limite de 50 MB por arquivo)."


class BlobCorrupted(NexusError):
    user_message = "Um arquivo anexado está corrompido ou foi alterado fora do NEXUS INTEL."


class PackageError(NexusError):
    user_message = "O arquivo .nexus é inválido ou está corrompido."


class PackageAuthError(PackageError):
    user_message = "Senha incorreta ou arquivo .nexus alterado. Nada foi importado."


class PackageIncompatible(PackageError):
    user_message = "Este arquivo .nexus foi criado por uma versão mais nova do NEXUS INTEL. Atualize o aplicativo."


class ReauthRequired(NexusError):
    user_message = "Por segurança, confirme sua senha para continuar."


class ProfileError(NexusError):
    user_message = "Não foi possível concluir a operação no perfil."
