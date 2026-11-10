"""0.3.4: Nexus Notepad e fotografias (validação por conteúdo, deduplicação, coleta)."""

from __future__ import annotations

import pytest

from nexus_intel.domain.errors import AttachmentTooLarge, InvalidImage, NexusError
from nexus_intel.infrastructure.media import images
from tests.imagefactory import make_image


# ----------------------------------------------------------------- notas
def test_notes_crud_search_and_entity_link(store):
    eid = store.create_entity("person", "Pessoa A")
    n1 = store.create_note("Hipótese inicial", "texto " * 5000)  # texto longo
    n2 = store.create_note("Reunião", "falar sobre o veículo", entity_id=eid)
    assert {n["id"] for n in store.list_notes()} == {n1, n2}
    assert [n["id"] for n in store.list_notes("veículo")] == [n2]
    assert [n["id"] for n in store.list_notes(entity_id=eid)] == [n2]
    assert store.get_note(n2)["entity_name"] == "Pessoa A"
    store.update_note(n1, "Hipótese revisada", "novo texto")
    assert store.list_notes()[0]["id"] == n1  # ordem por atualização
    assert [n["title"] for n in store.list_notes(order="title")] == ["Hipótese revisada", "Reunião"]
    store.delete_note(n1)
    with pytest.raises(NexusError):
        store.get_note(n1)


def test_note_survives_entity_purge_without_link(store):
    eid = store.create_entity("person", "Pessoa B")
    nid = store.create_note("Obs", "x", entity_id=eid)
    store.trash_entity(eid)
    store.delete_entity_permanently(eid)
    assert store.get_note(nid)["entity_id"] is None


# ----------------------------------------------------------- imagens
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF"])
def test_inspect_accepts_formats_by_content(fmt):
    info = images.inspect_image(make_image(fmt))
    assert (info.width, info.height) == (64, 48)
    assert images.render_png(make_image(fmt), 32).startswith(b"\x89PNG")


def test_inspect_rejects_fake_and_truncated_and_huge():
    with pytest.raises(InvalidImage):
        images.inspect_image(b"MZ\x90\x00" + b"\x00" * 100)  # executável renomeado
    with pytest.raises(InvalidImage):
        images.inspect_image(make_image("PNG")[:60])  # truncado
    with pytest.raises(AttachmentTooLarge):
        images.inspect_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * (images.MAX_IMAGE_BYTES + 1))


def test_inspect_detects_gps_exif():
    info = images.inspect_image(make_image("JPEG", gps=True))
    assert info.has_exif and info.has_gps


# -------------------------------------------------------- fotografias
def test_photos_add_list_replace_remove_and_dedupe(store):
    a = store.create_entity("person", "Pessoa A")
    b = store.create_entity("person", "Pessoa B")
    red, blue = make_image("PNG", color=(255, 0, 0)), make_image("JPEG", color=(0, 0, 255))
    pa = store.add_photo(a, red, "foto.png")
    pb = store.add_photo(b, red, "mesma.png")  # mesma imagem em outra entidade
    store.add_photo(a, blue, "azul.jpg")
    assert [p["original_name"] for p in store.list_photos(a)] == ["foto.png", "azul.jpg"]
    assert store.list_photos(a)[0]["entity_name"] == "Pessoa A"
    assert len(store.blobs.list_shas()) == 2  # um arquivo por conteúdo
    with pytest.raises(NexusError):
        store.add_photo(a, red, "de novo.png")
    assert store.photo_bytes(pa) == red

    store.remove_photo(pa)  # a imagem continua: a entidade B ainda usa
    assert store.photo_bytes(pb) == red
    assert len(store.blobs.list_shas()) == 2

    green = make_image("WEBP", color=(0, 255, 0))
    store.replace_photo(pb, green, "verde.webp")
    assert store.photo_bytes(pb) == green
    assert len(store.blobs.list_shas()) == 2  # vermelho saiu, verde entrou


def test_photo_files_are_encrypted_when_project_is(store):
    eid = store.create_entity("person", "Pessoa C")
    data = make_image("PNG")
    pid = store.add_photo(eid, data, "c.png")
    sha = store.get_photo(pid)["sha256"]
    raw = store.blobs.path_for(sha).read_bytes()
    if store.blobs.encrypted:
        assert data not in raw and raw[:4] == b"NXB1"
    else:
        assert raw[:4] == b"NXB0"


def test_tampered_blob_is_detected(store):
    from nexus_intel.domain.errors import BlobCorrupted

    eid = store.create_entity("person", "Pessoa D")
    pid = store.add_photo(eid, make_image("PNG"), "d.png")
    path = store.blobs.path_for(store.get_photo(pid)["sha256"])
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(BlobCorrupted):
        store.photo_bytes(pid)


def test_purging_entity_collects_unused_files(store):
    eid = store.create_entity("person", "Pessoa E")
    store.add_photo(eid, make_image("PNG"), "e.png")
    store.trash_entity(eid)
    store.delete_entity_permanently(eid)
    assert store.blobs.list_shas() == []
    assert store._all("SELECT * FROM attachment") == []


def test_invalid_image_is_not_stored(store):
    eid = store.create_entity("person", "Pessoa F")
    with pytest.raises(InvalidImage):
        store.add_photo(eid, b"isto nao e imagem", "falsa.jpg")
    assert store.blobs.list_shas() == []
