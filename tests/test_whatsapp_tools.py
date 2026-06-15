import pytest
from unittest.mock import MagicMock, patch
from datetime import date


def make_bq_row(grupo, facturacion, ordenes, ticket):
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: grupo if k in ("Marca","Local","Canal","Fecha") else None)
    row.Facturacion = facturacion
    row.Ordenes = ordenes
    row.Ticket_Promedio = ticket
    return row


class TestQueryRetail:
    def test_retorna_lista_con_estructura_correcta(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_row = make_bq_row("Temple", 279_758_420, 7502, 37_291)
        mock_client.query.return_value.result.return_value = [mock_row]

        result = query_retail(mock_client, "2026-05-18", "2026-05-24", "marca")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["facturacion"] == 279_758_420
        assert result[0]["ordenes"] == 7502
        assert result[0]["ticket"] == 37_291

    def test_agrupar_por_dia_usa_columna_fecha(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_retail(mock_client, "2026-05-18", "2026-05-24", "dia")

        call_args = mock_client.query.call_args[0][0]
        assert "Fecha" in call_args
        assert "GROUP BY Fecha" in call_args

    def test_agrupar_por_marca(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_retail(mock_client, "2026-05-18", "2026-05-24", "marca")

        call_args = mock_client.query.call_args[0][0]
        assert "GROUP BY Marca" in call_args

    def test_agrupar_por_local(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_retail(mock_client, "2026-05-18", "2026-05-24", "local")

        call_args = mock_client.query.call_args[0][0]
        assert "GROUP BY Local" in call_args

    def test_agrupar_por_canal(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_retail(mock_client, "2026-05-18", "2026-05-24", "canal")

        call_args = mock_client.query.call_args[0][0]
        assert "GROUP BY Canal" in call_args

    def test_agrupar_por_invalido_lanza_error(self):
        from whatsapp_tools import query_retail

        mock_client = MagicMock()

        with pytest.raises(ValueError):
            query_retail(mock_client, "2026-05-18", "2026-05-24", "semana")


class TestGetObjectives:
    def test_retorna_estructura_con_pace(self):
        from whatsapp_tools import get_objectives_for_tool

        mock_obj = {
            "Temple": {
                "2026-05": {"obj_fac": 1424, "obj_ord": 38137}
            }
        }

        with patch("whatsapp_tools.fetch_objetivos_data", return_value=mock_obj):
            result = get_objectives_for_tool("Temple", "2026-05")

        assert result["obj_fac"] == 1424
        assert result["obj_ord"] == 38137
        assert "pace_pct" in result
        assert "dias_transcurridos" in result
        assert "dias_mes" in result
        assert 0 < result["pace_pct"] <= 100

    def test_marca_inexistente_retorna_ceros(self):
        from whatsapp_tools import get_objectives_for_tool

        with patch("whatsapp_tools.fetch_objetivos_data", return_value={}):
            result = get_objectives_for_tool("MarcaFalsa", "2026-05")

        assert result["obj_fac"] == 0
        assert result["obj_ord"] == 0


class TestQueryProduct:
    def test_retorna_kpis_con_mix_y_ranking(self):
        from whatsapp_tools import query_product

        mock_row = MagicMock()
        mock_row.familia = "Cerveza"
        mock_row.lts_total = 320.5
        mock_row.facturacion = 150_000_000
        mock_row.producto = "Rubia 500cc"

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = [mock_row]

        result = query_product(mock_client, "2026-05-18", "2026-05-24", "TEMPLE")

        assert "mix" in result
        assert "top_productos" in result
        assert isinstance(result["mix"], list)
        assert isinstance(result["top_productos"], list)

    def test_feriado_usa_columnas_distintas(self):
        from whatsapp_tools import query_product

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_product(mock_client, "2026-05-18", "2026-05-24", "FERIADO")

        calls = mock_client.query.call_args_list
        assert len(calls) == 2  # query_mix + query_top
        sql_mix = calls[0][0][0]
        assert "Fecha_de_creacion" in sql_mix
        assert "Nombre" in sql_mix or "Categor__as_de_Productos_Platos" in sql_mix

    def test_todas_no_aplica_filtro_de_marca(self):
        from whatsapp_tools import query_product

        mock_client = MagicMock()
        mock_client.query.return_value.result.return_value = []

        query_product(mock_client, "2026-05-18", "2026-05-24", "TODAS")

        sql = mock_client.query.call_args_list[0][0][0]
        assert "AND marca" not in sql.lower()


class TestToolDefinitions:
    def test_hay_tres_tools_definidas(self):
        from whatsapp_tools import TOOL_DEFINITIONS
        assert len(TOOL_DEFINITIONS) == 3
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "query_retail" in names
        assert "get_objectives" in names
        assert "query_product" in names

    def test_viewer_tools_excluye_query_product(self):
        from whatsapp_tools import VIEWER_TOOL_DEFINITIONS
        names = [t["name"] for t in VIEWER_TOOL_DEFINITIONS]
        assert "query_product" not in names
        assert "query_retail" in names
        assert "get_objectives" in names
