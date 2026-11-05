"""Catálogo padrão: 15 tipos de entidade, campos e 25 tipos de relação (seções 6.3 e 6.5)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    datatype: str = "text"
    conflict_rule: str = "single"  # single, single_per_period, multi
    sensitive: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypeSpec:
    key: str
    label: str
    icon: str
    color: str
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


F = FieldSpec
_COMMON = (F("site", "Site", "url", "multi"), F("observacao_publica", "Observação", "text", "multi"))

ENTITY_TYPES: tuple[TypeSpec, ...] = (
    TypeSpec("person", "Pessoa", "user", "#38bdf8", (
        F("nascimento", "Data de nascimento", "date"),
        F("falecimento", "Data de falecimento", "date"),
        F("nacionalidade", "Nacionalidade", "text", "multi"),
        F("profissao", "Profissão", "text", "single_per_period"),
        F("cargo", "Cargo", "text", "single_per_period"),
        F("email", "E-mail", "email", "multi"),
        F("telefone", "Telefone", "phone", "multi"),
        F("endereco", "Endereço", "text", "single_per_period"),
        F("saude", "Informação de saúde", "text", "multi", sensitive=True),
        F("religiao", "Religião", "text", "single_per_period", sensitive=True),
    )),
    TypeSpec("company", "Empresa", "building-2", "#a78bfa", (
        F("fundacao", "Data de fundação", "date"),
        F("razao_social", "Razão social", "text", "single_per_period"),
        F("setor", "Setor", "text", "multi"),
        F("situacao", "Situação cadastral", "enum", "single_per_period",
          options=("Ativa", "Baixada", "Suspensa", "Inapta", "Nula")),
        F("capital_social", "Capital social (R$)", "number", "single_per_period"),
        F("endereco", "Endereço", "text", "single_per_period"),
        F("email", "E-mail", "email", "multi"),
        F("telefone", "Telefone", "phone", "multi"),
        *_COMMON,
    )),
    TypeSpec("organization", "Organização", "landmark", "#c084fc", (
        F("fundacao", "Data de fundação", "date"),
        F("natureza", "Natureza", "text"),
        F("endereco", "Endereço", "text", "single_per_period"),
        *_COMMON,
    )),
    TypeSpec("website", "Site", "globe", "#22d3ee", (
        F("url", "URL", "url"),
        F("titulo", "Título", "text", "single_per_period"),
        F("observacao_publica", "Observação", "text", "multi"),
    )),
    TypeSpec("domain", "Domínio", "at-sign", "#06b6d4", (
        F("registro", "Data de registro", "date"),
        F("expiracao", "Data de expiração", "date", "single_per_period"),
        F("registrador", "Registrador", "text", "single_per_period"),
        F("nameserver", "Servidor de nomes", "text", "multi"),
    )),
    TypeSpec("ip", "Endereço IP", "network", "#0ea5e9", (
        F("asn", "ASN", "text", "single_per_period"),
        F("provedor", "Provedor", "text", "single_per_period"),
    )),
    TypeSpec("subject", "Assunto", "hash", "#f59e0b", (F("observacao_publica", "Observação", "text", "multi"),)),
    TypeSpec("project", "Projeto", "folder-kanban", "#eab308", (
        F("inicio", "Início", "date"),
        F("fim", "Fim", "date"),
        F("situacao", "Situação", "enum", "single_per_period", options=("Planejado", "Em andamento", "Concluído", "Cancelado")),
    )),
    TypeSpec("object", "Objeto", "box", "#a3a3a3", (
        F("descricao_fisica", "Descrição física", "text", "multi"),
        F("numero_serie", "Número de série", "text"),
    )),
    TypeSpec("vehicle", "Veículo", "car", "#f97316", (
        F("marca", "Marca", "text"),
        F("modelo", "Modelo", "text"),
        F("ano", "Ano", "number"),
        F("cor", "Cor", "text", "single_per_period"),
        F("chassi", "Chassi", "text"),
    )),
    TypeSpec("location", "Localização", "map-pin", "#10b981", (
        F("endereco", "Endereço", "text"),
        F("cidade", "Cidade", "text"),
        F("pais", "País", "text"),
        F("latitude", "Latitude", "number"),
        F("longitude", "Longitude", "number"),
    )),
    TypeSpec("event", "Evento", "calendar", "#f43f5e", (
        F("data", "Data", "date"),
        F("local", "Local (texto)", "text"),
    )),
    TypeSpec("document", "Documento", "file-text", "#84cc16", (
        F("data_documento", "Data do documento", "date"),
        F("numero", "Número", "text"),
        F("autor", "Autor", "text", "multi"),
    )),
    TypeSpec("account", "Conta online", "at-sign", "#ec4899", (
        F("plataforma", "Plataforma", "text"),
        F("usuario", "Nome de usuário", "text", "single_per_period"),
        F("url", "URL do perfil", "url"),
    )),
    TypeSpec("other", "Outro", "circle", "#94a3b8", (F("observacao_publica", "Observação", "text", "multi"),)),
)

# (key, rótulo, rótulo inverso, direcionada)
RELATION_TYPES: tuple[tuple[str, str, str, bool], ...] = (
    ("owns", "possui", "pertence a", True),
    ("works_at", "trabalha em", "emprega", True),
    ("partner_of", "sócio de", "tem como sócio", True),
    ("controls", "controla", "é controlada por", True),
    ("manages", "administra", "é administrada por", True),
    ("relative_of", "parente de", "parente de", False),
    ("spouse_of", "cônjuge de", "cônjuge de", False),
    ("knows", "conhece", "conhece", False),
    ("located_in", "localizado em", "abriga", True),
    ("lives_in", "reside em", "é residência de", True),
    ("occurred_in", "ocorreu em", "foi local de", True),
    ("participated_in", "participou de", "teve participação de", True),
    ("member_of", "membro de", "tem como membro", True),
    ("mentions", "menciona", "é mencionado em", True),
    ("authored", "é autor de", "tem como autor", True),
    ("hosts", "hospeda", "é hospedado por", True),
    ("resolves_to", "resolve para", "é destino de", True),
    ("registered_by", "registrado por", "registrou", True),
    ("uses", "usa", "é usado por", True),
    ("contracted", "contratou", "foi contratado por", True),
    ("paid", "pagou", "recebeu de", True),
    ("subsidiary_of", "subsidiária de", "controladora de", True),
    ("represents", "representa", "é representado por", True),
    ("related_to", "relacionado a", "relacionado a", False),
    ("same_as_candidate", "possivelmente o mesmo que", "possivelmente o mesmo que", False),
)

TEMPLATES = {
    "blank": "Em branco",
    "investigation": "Investigação",
    "research": "Pesquisa acadêmica",
    "it_assets": "Ativos de TI",
    "genealogy": "Genealogia",
    "example": "Exemplo guiado",
}
