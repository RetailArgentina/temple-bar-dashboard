"""
tests/test_permissions.py — Tests para permissions.py

Cubre:
- BRAND_FAMILIES estructura
- get_available_brands()
- get_user_permissions(db, email)
- resolve_brand_families(brands)
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# BRAND_FAMILIES y get_available_brands
# ---------------------------------------------------------------------------

def test_brand_families_contains_expected_keys():
    from permissions import BRAND_FAMILIES
    assert set(BRAND_FAMILIES.keys()) == {"bosque", "feriado", "cerveza", "merch"}


def test_brand_families_prefixes():
    from permissions import BRAND_FAMILIES
    assert BRAND_FAMILIES["bosque"] == ["bosque_"]
    assert BRAND_FAMILIES["feriado"] == ["feriado_"]
    assert BRAND_FAMILIES["cerveza"] == ["lata_"]
    assert BRAND_FAMILIES["merch"] == ["merch"]


def test_get_available_brands_returns_sorted_list():
    from permissions import get_available_brands
    result = get_available_brands()
    assert isinstance(result, list)
    assert result == sorted(result)


def test_get_available_brands_contains_all_brands():
    from permissions import get_available_brands
    result = get_available_brands()
    assert set(result) == {"bosque", "feriado", "cerveza", "merch"}


# ---------------------------------------------------------------------------
# get_user_permissions
# ---------------------------------------------------------------------------

def _make_mock_db(doc_data):
    """Helper: crea un mock de Firestore db que devuelve doc_data para get()."""
    mock_doc = MagicMock()
    mock_doc.exists = doc_data is not None
    if doc_data is not None:
        mock_doc.to_dict.return_value = doc_data

    mock_collection = MagicMock()
    mock_collection.document.return_value.get.return_value = mock_doc

    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection
    return mock_db


def test_get_user_permissions_existing_user_returns_dict():
    from permissions import get_user_permissions
    doc_data = {
        "role": "editor",
        "brands": ["bosque", "feriado"],
        "can_edit_objectives": False,
    }
    db = _make_mock_db(doc_data)
    result = get_user_permissions(db, "darwin.salinas@temple.com.ar")
    assert result is not None
    assert isinstance(result, dict)
    assert result["role"] == "editor"
    assert result["brands"] == ["bosque", "feriado"]
    assert result["can_edit_objectives"] is False


def test_get_user_permissions_not_found_returns_none():
    from permissions import get_user_permissions
    db = _make_mock_db(None)
    result = get_user_permissions(db, "unknown@external.com")
    assert result is None


def test_get_user_permissions_normalizes_email_to_lowercase():
    from permissions import get_user_permissions, COLLECTION
    doc_data = {"role": "viewer", "brands": ["*"], "can_edit_objectives": False}
    db = _make_mock_db(doc_data)
    get_user_permissions(db, "DARWIN.SALINAS@TEMPLE.COM.AR")
    # Verifica que se buscó con email en minúsculas
    db.collection.assert_called_with(COLLECTION)
    db.collection.return_value.document.assert_called_with(
        "darwin.salinas@temple.com.ar"
    )


def test_get_user_permissions_uses_correct_collection():
    from permissions import get_user_permissions, COLLECTION
    doc_data = {"role": "superadmin", "brands": ["*"], "can_edit_objectives": True}
    db = _make_mock_db(doc_data)
    get_user_permissions(db, "admin@temple.com.ar")
    db.collection.assert_called_with(COLLECTION)


# ---------------------------------------------------------------------------
# resolve_brand_families
# ---------------------------------------------------------------------------

def test_resolve_brand_families_wildcard_returns_all_prefixes():
    from permissions import resolve_brand_families, BRAND_FAMILIES
    result = resolve_brand_families(["*"])
    expected = []
    for prefixes in BRAND_FAMILIES.values():
        expected.extend(prefixes)
    assert sorted(result) == sorted(expected)


def test_resolve_brand_families_specific_brands():
    from permissions import resolve_brand_families
    result = resolve_brand_families(["bosque", "feriado"])
    assert sorted(result) == sorted(["bosque_", "feriado_"])


def test_resolve_brand_families_cerveza():
    from permissions import resolve_brand_families
    result = resolve_brand_families(["cerveza"])
    assert result == ["lata_"]


def test_resolve_brand_families_merch():
    from permissions import resolve_brand_families
    result = resolve_brand_families(["merch"])
    assert result == ["merch"]


def test_resolve_brand_families_empty_returns_empty_list():
    from permissions import resolve_brand_families
    result = resolve_brand_families([])
    assert result == []


def test_resolve_brand_families_single_wildcard_covers_all_four():
    from permissions import resolve_brand_families, BRAND_FAMILIES
    result = resolve_brand_families(["*"])
    # Debe cubrir las 4 familias
    all_prefixes = [p for ps in BRAND_FAMILIES.values() for p in ps]
    assert len(result) == len(all_prefixes)


# ---------------------------------------------------------------------------
# Helpers para CRUD tests
# ---------------------------------------------------------------------------

def _make_mock_db_stream(docs_data):
    """Helper: crea mock de Firestore db que devuelve lista de docs para stream()."""
    mock_docs = []
    for email, data in docs_data:
        mock_doc = MagicMock()
        mock_doc.id = email
        mock_doc.to_dict.return_value = data
        mock_docs.append(mock_doc)

    mock_collection = MagicMock()
    mock_collection.stream.return_value = iter(mock_docs)

    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection
    return mock_db


def _make_mock_db_crud(doc_exists, doc_data=None):
    """Helper: crea mock de Firestore db para operaciones CRUD (get/set/update/delete)."""
    mock_doc_ref = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.exists = doc_exists
    if doc_data is not None:
        mock_snapshot.to_dict.return_value = doc_data
    mock_doc_ref.get.return_value = mock_snapshot

    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref

    mock_db = MagicMock()
    mock_db.collection.return_value = mock_collection
    return mock_db, mock_doc_ref


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

def test_list_users():
    from permissions import list_users
    docs_data = [
        ("alice@temple.com.ar", {"role": "editor", "brands": ["bosque"]}),
        ("bob@temple.com.ar",   {"role": "viewer",  "brands": ["feriado"]}),
    ]
    db = _make_mock_db_stream(docs_data)
    result = list_users(db)
    assert isinstance(result, list)
    assert len(result) == 2
    emails = {u["email"] for u in result}
    assert emails == {"alice@temple.com.ar", "bob@temple.com.ar"}
    for user in result:
        assert "email" in user


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

def test_create_user_valid():
    from permissions import create_user
    db, doc_ref = _make_mock_db_crud(doc_exists=False)
    result = create_user(db, "nuevo@temple.com.ar", "editor", ["bosque"])
    assert result["ok"] is True
    doc_ref.set.assert_called_once()
    call_args = doc_ref.set.call_args[0][0]
    assert call_args["role"] == "editor"
    assert call_args["brands"] == ["bosque"]
    assert call_args["can_edit_objectives"] is True


def test_create_user_already_exists():
    from permissions import create_user
    db, _ = _make_mock_db_crud(doc_exists=True, doc_data={"role": "viewer", "brands": ["bosque"]})
    result = create_user(db, "existente@temple.com.ar", "viewer", ["bosque"])
    assert result["ok"] is False
    assert "error" in result


def test_create_user_rejects_superadmin():
    from permissions import create_user
    db, _ = _make_mock_db_crud(doc_exists=False)
    result = create_user(db, "nuevo@temple.com.ar", "superadmin", ["*"])
    assert result["ok"] is False
    assert "error" in result


def test_create_user_rejects_invalid_role():
    from permissions import create_user
    db, _ = _make_mock_db_crud(doc_exists=False)
    result = create_user(db, "nuevo@temple.com.ar", "admin", ["bosque"])
    assert result["ok"] is False
    assert "error" in result


def test_create_user_rejects_invalid_brand():
    from permissions import create_user
    db, _ = _make_mock_db_crud(doc_exists=False)
    result = create_user(db, "nuevo@temple.com.ar", "viewer", ["whisky"])
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# update_user
# ---------------------------------------------------------------------------

def test_update_user():
    from permissions import update_user
    existing_data = {"role": "viewer", "brands": ["bosque"], "can_edit_objectives": False}
    db, doc_ref = _make_mock_db_crud(doc_exists=True, doc_data=existing_data)
    result = update_user(db, "alice@temple.com.ar", role="editor", brands=["feriado"])
    assert result["ok"] is True
    doc_ref.update.assert_called_once()
    call_args = doc_ref.update.call_args[0][0]
    assert call_args["role"] == "editor"
    assert call_args["brands"] == ["feriado"]
    assert call_args["can_edit_objectives"] is True


def test_update_user_not_found():
    from permissions import update_user
    db, _ = _make_mock_db_crud(doc_exists=False)
    result = update_user(db, "noexiste@temple.com.ar", role="editor")
    assert result["ok"] is False
    assert "error" in result


def test_update_user_cannot_change_superadmin():
    from permissions import update_user
    existing_data = {"role": "superadmin", "brands": ["*"], "can_edit_objectives": True}
    db, _ = _make_mock_db_crud(doc_exists=True, doc_data=existing_data)
    result = update_user(db, "admin@temple.com.ar", role="editor")
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# delete_user
# ---------------------------------------------------------------------------

def test_delete_user():
    from permissions import delete_user
    existing_data = {"role": "viewer", "brands": ["bosque"], "can_edit_objectives": False}
    db, doc_ref = _make_mock_db_crud(doc_exists=True, doc_data=existing_data)
    result = delete_user(db, "alice@temple.com.ar", actor_email="darwin@temple.com.ar")
    assert result["ok"] is True
    doc_ref.delete.assert_called_once()


def test_delete_user_cannot_delete_self():
    from permissions import delete_user
    db, _ = _make_mock_db_crud(doc_exists=True, doc_data={"role": "editor"})
    result = delete_user(db, "darwin@temple.com.ar", actor_email="darwin@temple.com.ar")
    assert result["ok"] is False
    assert "error" in result


def test_delete_user_cannot_delete_superadmin():
    from permissions import delete_user
    existing_data = {"role": "superadmin", "brands": ["*"], "can_edit_objectives": True}
    db, _ = _make_mock_db_crud(doc_exists=True, doc_data=existing_data)
    result = delete_user(db, "admin@temple.com.ar", actor_email="darwin@temple.com.ar")
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Rol gerencia
# ---------------------------------------------------------------------------

def test_gerencia_in_valid_roles():
    from permissions import VALID_ROLES
    assert "gerencia" in VALID_ROLES


def test_create_gerencia_user_sets_can_edit_objectives_true():
    from permissions import create_user
    doc_ref = MagicMock()
    doc_ref.get.return_value.exists = False
    db = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    result = create_user(db, "gerencia@temple.com.ar", "gerencia", ["*"])
    assert result["ok"] is True
    call_args = doc_ref.set.call_args[0][0]
    assert call_args["can_edit_objectives"] is True


# ---------------------------------------------------------------------------
# parse_flat_objectives
# ---------------------------------------------------------------------------

_HEADER = ["marca", "dimension", "nombre",
           "ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic"]

def _obj_row(marca="bosque", dim="product", nombre="bosque_nativo", vals=None):
    if vals is None:
        vals = ["100"] * 12
    return [marca, dim, nombre] + vals


def test_parse_flat_objectives_valid():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(vals=["100","110","120","130","140","150",
                                     "160","170","180","190","200","210"])]
    docs, errors = parse_flat_objectives(rows)
    assert errors == []
    assert len(docs) == 1
    assert docs[0]["marca"] == "bosque"
    assert docs[0]["nombre"] == "bosque_nativo"
    assert docs[0]["valores"] == [100,110,120,130,140,150,160,170,180,190,200,210]


def test_parse_flat_objectives_missing_column():
    from permissions import parse_flat_objectives
    rows = [["marca", "dimension", "nombre", "ene", "feb"], _obj_row(vals=["100","110"])]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("Faltan columnas" in e for e in errors)


def test_parse_flat_objectives_unknown_marca():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(marca="desconocida")]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("marca desconocida" in e for e in errors)


def test_parse_flat_objectives_duplicate_row():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(), _obj_row()]
    docs, errors = parse_flat_objectives(rows)
    assert len(docs) == 1
    assert any("duplicado" in e for e in errors)


def test_parse_flat_objectives_nonnumeric_value():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(vals=["ABC"] + ["100"] * 11)]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("no numérico" in e for e in errors)


def test_parse_flat_objectives_no_header():
    from permissions import parse_flat_objectives
    rows = [_obj_row()]
    docs, errors = parse_flat_objectives(rows)
    assert docs == []
    assert any("encabezado" in e for e in errors)


def test_parse_flat_objectives_empty_values_become_zero():
    from permissions import parse_flat_objectives
    rows = [_HEADER, _obj_row(vals=["","110","120","130","140","150",
                                      "160","170","180","190","200","210"])]
    docs, errors = parse_flat_objectives(rows)
    assert errors == []
    assert docs[0]["valores"][0] == 0


def test_parse_flat_objectives_skips_empty_rows():
    from permissions import parse_flat_objectives
    rows = [_HEADER, ["","","","","","","","","","","","","","",""], _obj_row()]
    docs, errors = parse_flat_objectives(rows)
    assert len(docs) == 1
    assert errors == []


# ---------------------------------------------------------------------------
# list_objectives / save_objectives
# ---------------------------------------------------------------------------

def _make_stream_db(docs_data):
    mock_docs = []
    for doc_id, data in docs_data.items():
        d = MagicMock()
        d.id = doc_id
        d.to_dict.return_value = data
        d.reference = MagicMock()
        mock_docs.append(d)
    db = MagicMock()
    db.collection.return_value.stream.return_value = iter(mock_docs)
    return db


def test_list_objectives_returns_sorted_list():
    from permissions import list_objectives
    db = _make_stream_db({
        "feriado__product__feriado_rojo": {
            "marca": "feriado", "dimension": "product",
            "nombre": "feriado_rojo", "valores": [1]*12,
        },
        "bosque__product__bosque_nativo": {
            "marca": "bosque", "dimension": "product",
            "nombre": "bosque_nativo", "valores": [2]*12,
        },
    })
    result = list_objectives(db)
    assert len(result) == 2
    assert result[0]["marca"] == "bosque"
    assert result[1]["marca"] == "feriado"


def test_save_objectives_deletes_existing_and_writes_new():
    from permissions import save_objectives
    existing_doc = MagicMock()
    existing_doc.reference = MagicMock()
    db = MagicMock()
    db.collection.return_value.stream.return_value = iter([existing_doc])
    docs = [{"marca": "bosque", "dimension": "product",
             "nombre": "bosque_nativo", "valores": [100]*12}]
    result = save_objectives(db, docs, updated_by="test@temple.com.ar")
    assert result["ok"] is True
    assert result["count"] == 1
    existing_doc.reference.delete.assert_called_once()
    db.collection.return_value.document.return_value.set.assert_called_once()


def test_save_objectives_rejects_empty_docs():
    from permissions import save_objectives
    db = MagicMock()
    result = save_objectives(db, [], updated_by="test@temple.com.ar")
    assert result["ok"] is False
