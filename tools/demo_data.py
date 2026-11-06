"""Dados fictícios e determinísticos para capturas de tela e testes de volume.

Todos os nomes são inventados. Nada aqui representa pessoas ou empresas reais.
"""

from __future__ import annotations

import random

from nexus_intel.application.project_store import ProjectStore

PEOPLE = [
    "Helena Prado", "Rafael Antunes", "Marina Coutinho", "Otávio Brandão", "Lívia Damasceno",
    "Caio Valadares", "Beatriz Moraes", "Diego Fontoura", "Sofia Albuquerque", "Tomás Rezende",
]
COMPANIES = [
    "Aurora Logística Ltda.", "Vértice Importações S.A.", "Delta Norte Consultoria",
    "Cais Azul Transportes", "Monteverde Participações",
]
PLACES = ["Veneza", "Porto de Santos", "Salvador", "Lisboa", "Gênova"]
VEHICLES = ["Caminhão placa QZX-1A23", "Sedan placa RTA-4B56"]
DOMAINS = ["aurora-log.example", "vertice-imp.example"]


def seed(store: ProjectStore, extra_people: int = 0, rng_seed: int = 42) -> dict[str, list[str]]:
    """Popula o projeto aberto. Devolve os IDs criados por categoria."""
    rng = random.Random(rng_seed)
    ids: dict[str, list[str]] = {"person": [], "company": [], "location": [], "vehicle": [], "domain": []}
    for name in PEOPLE + [f"Pessoa fictícia {i:05d}" for i in range(extra_people)]:
        ids["person"].append(store.create_entity("person", name, importance=rng.randint(1, 5)))
    for name in COMPANIES:
        ids["company"].append(store.create_entity("company", name, importance=rng.randint(2, 5)))
    for name in PLACES:
        ids["location"].append(store.create_entity("location", name))
    for name in VEHICLES:
        ids["vehicle"].append(store.create_entity("vehicle", name))
    for name in DOMAINS:
        ids["domain"].append(store.create_entity("domain", name))

    sources = [
        store.create_source("Junta comercial — ficha cadastral (fictícia)", kind="official", reliability="A"),
        store.create_source("Reportagem do Diário do Porto (fictícia)", kind="news", reliability="C",
                            url="https://jornal.example/materia"),
        store.create_source("Entrevista com testemunha (fictícia)", kind="interview", reliability="D"),
        store.create_source("Registro WHOIS (fictício)", kind="website", reliability="B"),
    ]
    statuses = ["verified", "reported", "unverified", "hypothesis"]

    people = ids["person"][: len(PEOPLE)]
    for i, p in enumerate(people):
        company = ids["company"][i % len(COMPANIES)]
        st = statuses[i % 4]
        src = sources[i % 3] if st != "unverified" else None
        store.create_relation("works_at", p, company, status=st, evidence_source=src,
                              excerpt="consta no quadro de funcionários" if src else "")
        if i % 3 == 0:
            store.create_relation("partner_of", p, ids["company"][(i + 1) % len(COMPANIES)],
                                  status="verified", evidence_source=sources[0])
        if i > 0 and i % 2 == 0:
            store.create_relation("knows", p, people[i - 1], status="reported", evidence_source=sources[2])
        store.add_claim(p, "profissao", rng.choice(["Despachante", "Contadora", "Engenheiro", "Advogada"]),
                        status=st, source_id=src)
    for j, c in enumerate(ids["company"]):
        store.create_relation("located_in", c, ids["location"][j % len(PLACES)], status="verified",
                              evidence_source=sources[0])
        store.add_claim(c, "situacao", "Ativa", status="verified", source_id=sources[0])
    store.create_relation("owns", ids["company"][0], ids["vehicle"][0], status="verified", evidence_source=sources[0])
    store.create_relation("owns", people[3], ids["vehicle"][1], status="reported", evidence_source=sources[1])
    store.create_relation("located_in", ids["vehicle"][0], ids["location"][0], status="reported",
                          evidence_source=sources[1], excerpt="caminhão fotografado em Veneza")
    for d, c in zip(ids["domain"], ids["company"], strict=False):
        store.create_relation("registered_by", d, c, status="verified", evidence_source=sources[3])
    # Um conflito proposital para a tela de Qualidade.
    store.add_claim(people[0], "nascimento", "03/1984", status="reported", source_id=sources[1])
    store.add_claim(people[0], "nascimento", "1986", status="reported", source_id=sources[2])
    # Algumas entidades extras recebem relações para o teste de volume do grafo.
    extra = ids["person"][len(PEOPLE):]
    for k, e in enumerate(extra):
        store.create_relation("knows", e, people[k % len(people)])
    return ids
