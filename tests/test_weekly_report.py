import pytest
from unittest.mock import MagicMock, patch
from datetime import date


class TestWeekDateRange:
    def test_rango_semana_anterior_desde_lunes(self):
        from weekly_report import get_last_week_range

        # Simular lunes 25/05/2026 — día que corre el scheduler
        with patch("weekly_report.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 25)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            desde, hasta = get_last_week_range()

        assert desde == "2026-05-18"  # lunes anterior (25 - 7)
        assert hasta == "2026-05-24"  # domingo anterior (25 - 1)


class TestFormatShortReport:
    def test_reporte_contiene_campos_clave(self):
        from weekly_report import format_short_report

        retail_data = [
            {"grupo": "Patagonia", "facturacion": 600_533_269, "ordenes": 15109, "ticket": 39747},
            {"grupo": "Temple",    "facturacion": 305_373_356, "ordenes": 8237,  "ticket": 37073},
            {"grupo": "Feriado",   "facturacion": 11_368_900,  "ordenes": 235,   "ticket": 48378},
        ]
        objectives = {
            "Patagonia": {"obj_fac": 2929, "pace_pct": 80.6, "dias_transcurridos": 25, "dias_mes": 31},
            "Temple":    {"obj_fac": 1424, "pace_pct": 80.6, "dias_transcurridos": 25, "dias_mes": 31},
            "Feriado":   {"obj_fac": 63,   "pace_pct": 80.6, "dias_transcurridos": 25, "dias_mes": 31},
        }

        text = format_short_report("2026-05-18", "2026-05-25", retail_data, objectives)

        assert "Patagonia" in text
        assert "Temple" in text
        assert "Feriado" in text
        assert "%" in text
        assert "$" in text
        assert "ticket" in text.lower() or "Ticket" in text

    def test_marca_sin_objetivo_no_rompe(self):
        from weekly_report import format_short_report

        retail_data = [{"grupo": "Temple", "facturacion": 100_000_000, "ordenes": 1000, "ticket": 100_000}]
        objectives = {}  # sin objetivos — no debe crashear

        text = format_short_report("2026-05-18", "2026-05-25", retail_data, objectives)
        assert "Temple" in text
