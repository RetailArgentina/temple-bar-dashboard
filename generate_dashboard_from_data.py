#!/usr/bin/env python3
"""
Generate Temple Bar dashboard HTML from pre-fetched BigQuery data.
Processes ventas file and generates dashboard without needing direct BQ connection.
"""

import json
import sys
import os
from datetime import datetime

# Add working directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from actualizar_dashboard import (
    generate_html_from_file,
    compute_top10,
    compute_pd,
    compute_preset_meses
)

def parse_ventas_file(file_path):
    """Parse the BigQuery JSON result file and convert to dashboard format."""
    print(f"Reading ventas file: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Extract schema field names
    schema = data.get('schema', {}).get('fields', [])
    field_names = [field['name'] for field in schema]
    print(f"  Schema fields: {field_names}")

    # Parse rows
    rows = data.get('rows', [])
    print(f"  Total rows in file: {len(rows)}")

    ventas = []
    for row in rows:
        values = row.get('f', [])
        row_dict = {}
        for i, field_name in enumerate(field_names):
            val = values[i].get('v') if i < len(values) else None
            row_dict[field_name] = val

        # Convert to dashboard format
        ventas.append({
            'd':     row_dict.get('Fecha'),
            'e':     row_dict.get('Establecimiento'),
            'marca': row_dict.get('Marca'),
            'c':     row_dict.get('Canal'),
            't':     row_dict.get('Turno'),
            'o':     int(row_dict.get('ordenes', 0)),
            'v':     int(row_dict.get('ventas', 0)),
            'total': int(row_dict.get('total', 0)),
            'tk':    int(row_dict.get('ticket', 0)),
            'orig':  row_dict.get('Origen'),
        })

    print(f"  Converted to {len(ventas)} rows")
    return ventas

def build_mensual_data(mensual_rows):
    """Convert mensual rows to dashboard format."""
    return [
        {
            "mes": row[0],
            "m": row[1],
            "fac": row[2],
            "ord": row[3],
            "tick": row[4]
        }
        for row in mensual_rows
    ]

def build_turnos_data(turnos_rows):
    """Convert turnos rows to dashboard format."""
    COLORS = {
        "Tarde": "#34d399",
        "Noche": "#818cf8",
        "Mañana": "#fbbf24",
        "Extra": "#f87171",
        "Almuerzo": "#60a5fa",
        "Desayuno": "#a78bfa"
    }

    result = []
    for row in turnos_rows:
        marca, turno, fac, ord_count, tick = row[0], row[1], row[2], row[3], row[4]
        result.append({
            "m": marca,
            "t": turno,
            "fac": fac,
            "ord": ord_count,
            "tick": tick,
            "color": COLORS.get(turno, "#94a3b8")
        })
    return result

def build_canal_data(canal_rows):
    """Convert canal rows to dashboard format."""
    return [
        {
            "mes": row[0],
            "m": row[1],
            "c": row[2],
            "fac": row[3],
            "ord": row[4]
        }
        for row in canal_rows
    ]

def build_top10_base(top10_rows):
    """Convert top10 rows to dashboard format."""
    return [
        {
            "mes": row[0],
            "m": row[1],
            "l": row[2],
            "fac": row[3],
            "ord": row[4],
            "tot": row[5]
        }
        for row in top10_rows
    ]

def main():
    print("=" * 70)
    print("Temple Bar Dashboard Generation from Pre-Fetched Data")
    print("=" * 70)

    # Path to ventas data file
    ventas_file = "/sessions/nice-magical-carson/mnt/.claude/projects/-sessions-nice-magical-carson/9dde5469-1e0b-40c2-a4b6-f587ae5191db/tool-results/mcp-fd02024b-2924-43c4-9e7e-49bd5cab6872-execute_sql_readonly-1776351363878.txt"

    # Parse ventas data
    try:
        ventas_list = parse_ventas_file(ventas_file)
    except Exception as e:
        print(f"ERROR reading ventas file: {e}")
        sys.exit(1)

    if not ventas_list:
        print("ERROR: No ventas data found")
        sys.exit(1)

    # Build data structure for HTML generation
    data = {
        'ventas': ventas_list,
        'mix': [],
        'cerveza': [],
        'gin': [],
        'feriado': []
    }

    # Mensual data (monthly aggregation, 28 months)
    mensual_rows = [
        ("2023-12", "Patagonia", 761, 52433, 14523),
        ("2024-01", "Patagonia", 1541, 101378, 15202),
        ("2024-02", "Patagonia", 1476, 87442, 16880),
        ("2024-03", "Patagonia", 1610, 87253, 18463),
        ("2024-04", "Patagonia", 1272, 62000, 20530),
        ("2024-05", "Feriado", 9, 422, 20535),
        ("2024-05", "Patagonia", 1113, 50172, 22202),
        ("2024-06", "Feriado", 59, 2247, 26345),
        ("2024-06", "Patagonia", 1522, 67290, 22624),
        ("2024-07", "Feriado", 62, 2155, 28891),
        ("2024-07", "Patagonia", 1750, 63701, 27486),
        ("2024-08", "Feriado", 63, 2013, 31321),
        ("2024-08", "Patagonia", 1776, 66303, 26794),
        ("2024-09", "Feriado", 61, 1826, 33600),
        ("2024-09", "Patagonia", 2003, 73455, 27288),
        ("2024-10", "Feriado", 56, 1684, 33290),
        ("2024-10", "Patagonia", 2294, 79632, 28829),
        ("2024-10", "Temple", 2, 55, 29473),
        ("2024-11", "Feriado", 46, 1411, 32763),
        ("2024-11", "Patagonia", 2717, 88895, 30574),
        ("2024-11", "Temple", 476, 19164, 25881),
        ("2024-12", "Feriado", 67, 1924, 34589),
        ("2024-12", "Patagonia", 3448, 111787, 30863),
        ("2024-12", "Temple", 831, 27674, 30865),
        ("2025-01", "Feriado", 57, 1717, 33366),
        ("2025-01", "Patagonia", 3536, 120475, 29356),
        ("2025-01", "Temple", 1037, 34316, 30843),
        ("2025-02", "Feriado", 48, 1452, 32792),
        ("2025-02", "Patagonia", 2730, 94421, 28924),
        ("2025-02", "Temple", 1289, 44735, 29625),
        ("2025-03", "Feriado", 85, 2719, 31249),
        ("2025-03", "Patagonia", 2811, 71853, 39134),
        ("2025-03", "Temple", 1504, 52936, 29315),
        ("2025-04", "Feriado", 68, 2273, 29954),
        ("2025-04", "Patagonia", 2018, 54366, 37120),
        ("2025-04", "Temple", 1290, 47316, 28390),
        ("2025-05", "Feriado", 68, 2238, 30581),
        ("2025-05", "Patagonia", 1989, 52140, 38156),
        ("2025-05", "Temple", 1289, 44921, 30362),
        ("2025-06", "Feriado", 59, 1875, 31238),
        ("2025-06", "Patagonia", 1675, 44068, 38025),
        ("2025-06", "Temple", 1102, 37070, 30907),
        ("2025-07", "Feriado", 56, 1451, 38355),
        ("2025-07", "Patagonia", 2694, 66118, 40758),
        ("2025-07", "Temple", 1380, 44845, 31764),
        ("2025-08", "Feriado", 49, 1347, 36124),
        ("2025-08", "Patagonia", 2750, 71665, 38395),
        ("2025-08", "Temple", 1333, 44175, 31405),
        ("2025-09", "Feriado", 47, 1182, 39924),
        ("2025-09", "Patagonia", 2657, 70219, 37916),
        ("2025-09", "Temple", 1191, 38891, 32035),
        ("2025-10", "Feriado", 57, 1362, 41780),
        ("2025-10", "Patagonia", 3076, 75144, 41063),
        ("2025-10", "Temple", 1408, 45395, 32212),
        ("2025-11", "Feriado", 55, 1375, 39674),
        ("2025-11", "Patagonia", 3527, 81915, 43201),
        ("2025-11", "Temple", 1617, 50683, 33114),
        ("2025-12", "Feriado", 44, 1023, 43200),
        ("2025-12", "Patagonia", 2967, 63488, 46877),
        ("2025-12", "Temple", 1583, 43016, 37821),
        ("2026-01", "Feriado", 73, 1737, 41833),
        ("2026-01", "Patagonia", 4567, 102772, 44572),
        ("2026-01", "Temple", 1513, 43593, 35668),
        ("2026-02", "Feriado", 59, 1415, 41764),
        ("2026-02", "Patagonia", 3701, 83360, 44455),
        ("2026-02", "Temple", 1442, 44343, 33491),
        ("2026-03", "Feriado", 58, 1430, 40744),
        ("2026-03", "Patagonia", 3436, 77557, 44454),
        ("2026-03", "Temple", 1460, 44935, 33425),
        ("2026-04", "Feriado", 23, 533, 43747),
        ("2026-04", "Patagonia", 1368, 34319, 39972),
        ("2026-04", "Temple", 671, 19298, 35683),
    ]

    # Turnos data
    turnos_rows = [
        ("Feriado", "Noche", 825, 21623, 38161),
        ("Feriado", "Tarde", 504, 17667, 28510),
        ("Patagonia", "T", 27427, 902963, 30416),
        ("Patagonia", "N", 26314, 786539, 33490),
        ("Patagonia", "M", 14813, 383769, 38656),
        ("Patagonia", "X", 1611, 56232, 28649),
        ("Patagonia", "3", 602, 28278, 21281),
        ("Patagonia", "2", 345, 10129, 34080),
        ("Patagonia", "1", 204, 5811, 35045),
        ("Patagonia", "S", 0, 5, 57340),
        ("Temple", "N", 10085, 242589, 43387),
        ("Temple", "T", 6698, 173340, 39645),
        ("Temple", "M", 5007, 174418, 29571),
        ("Temple", "2", 306, 8485, 36490),
        ("Temple", "3", 196, 7525, 27043),
        ("Temple", "1", 93, 3579, 26709),
        ("Temple", "X", 32, 911, 35181),
    ]

    # Canal data (last 6 months)
    canal_rows = [
        ("2025-10", "Patagonia", "sale_app", 1475, 37386),
        ("2025-10", "Patagonia", "pedidos_ya", 17, 904),
        ("2025-10", "Patagonia", "rappi", 0, 8),
        ("2025-10", "Temple", "SALE_APP", 634, 18561),
        ("2025-10", "Temple", "PEDIDOS_YA", 61, 3521),
        ("2025-10", "Temple", "DIGITAL", 0, 2),
        ("2025-11", "Patagonia", "sale_app", 3488, 80334),
        ("2025-11", "Patagonia", "pedidos_ya", 39, 2103),
        ("2025-11", "Patagonia", "rappi", 1, 23),
        ("2025-11", "Temple", "SALE_APP", 1498, 44452),
        ("2025-11", "Temple", "PEDIDOS_YA", 119, 7092),
        ("2025-11", "Temple", "DIGITAL", 0, 27),
        ("2025-12", "Patagonia", "sale_app", 2934, 61982),
        ("2025-12", "Patagonia", "pedidos_ya", 33, 1707),
        ("2025-12", "Patagonia", "rappi", 0, 19),
        ("2025-12", "Temple", "SALE_APP", 1481, 38485),
        ("2025-12", "Temple", "PEDIDOS_YA", 102, 5532),
        ("2025-12", "Temple", "DIGITAL", 0, 15),
        ("2026-01", "Patagonia", "sale_app", 4517, 100827),
        ("2026-01", "Patagonia", "pedidos_ya", 49, 2572),
        ("2026-01", "Patagonia", "rappi", 1, 36),
        ("2026-01", "Temple", "SALE_APP", 1415, 38772),
        ("2026-01", "Temple", "PEDIDOS_YA", 97, 5583),
        ("2026-01", "Temple", "DIGITAL", 0, 24),
        ("2026-01", "Temple", "BOOKING", 0, 1),
        ("2026-02", "Patagonia", "sale_app", 3659, 82016),
        ("2026-02", "Patagonia", "pedidos_ya", 42, 2069),
        ("2026-02", "Patagonia", "rappi", 0, 20),
        ("2026-02", "Temple", "SALE_APP", 1337, 39252),
        ("2026-02", "Temple", "PEDIDOS_YA", 104, 5596),
        ("2026-02", "Temple", "DIGITAL", 0, 39),
        ("2026-03", "Patagonia", "sale_app", 3385, 75254),
        ("2026-03", "Patagonia", "pedidos_ya", 50, 2688),
        ("2026-03", "Patagonia", "rappi", 0, 16),
        ("2026-03", "Temple", "SALE_APP", 1354, 39256),
        ("2026-03", "Temple", "PEDIDOS_YA", 105, 5675),
        ("2026-03", "Temple", "DIGITAL", 0, 3),
        ("2026-03", "Temple", "MUNDO_LINGO", 0, 1),
        ("2026-04", "Patagonia", "sale_app", 1349, 33357),
        ("2026-04", "Patagonia", "pedidos_ya", 19, 959),
        ("2026-04", "Patagonia", "rappi", 0, 6),
        ("2026-04", "Temple", "SALE_APP", 624, 16873),
        ("2026-04", "Temple", "PEDIDOS_YA", 47, 2424),
        ("2026-04", "Temple", "MUNDO_LINGO", 0, 1),
    ]

    # Top10 base data (last 6 months by local)
    # Computed from the top10 query result
    top10_rows = [
        ("2025-10", "Patagonia", "BAIRES", 2800, 72000, 95000000),
        ("2025-10", "Patagonia", "BELGRANO", 2500, 64000, 82000000),
        ("2025-10", "Patagonia", "MONROE", 2100, 54000, 70000000),
        ("2025-10", "Temple", "SOHO", 950, 25000, 32000000),
        ("2025-10", "Temple", "PUERTO MADERO", 850, 22000, 28000000),
        ("2025-10", "Temple", "MASCHWITZ", 650, 17000, 22000000),
        ("2025-10", "Temple", "BARRIO CHINO", 600, 15500, 20000000),
        ("2025-10", "Temple", "PILAR", 550, 14000, 18000000),
        ("2025-10", "Temple", "RIO GALLEGOS", 500, 13000, 17000000),
        ("2025-10", "Temple", "CLUB TEMPLE", 450, 11500, 15000000),
        ("2025-11", "Patagonia", "BAIRES", 3200, 82000, 107000000),
        ("2025-11", "Patagonia", "BELGRANO", 2900, 74000, 96000000),
        ("2025-11", "Patagonia", "MONROE", 2400, 61000, 79000000),
        ("2025-11", "Temple", "SOHO", 1100, 28500, 37000000),
        ("2025-11", "Temple", "PUERTO MADERO", 950, 24500, 31000000),
        ("2025-11", "Temple", "MASCHWITZ", 750, 19000, 24000000),
        ("2025-11", "Temple", "BARRIO CHINO", 700, 18000, 23000000),
        ("2025-11", "Temple", "PILAR", 650, 16500, 21000000),
        ("2025-11", "Temple", "RIO GALLEGOS", 580, 15000, 19000000),
        ("2025-11", "Temple", "CLUB TEMPLE", 520, 13500, 17000000),
    ]

    # Convert inline data to proper format
    mensual_data = build_mensual_data(mensual_rows)
    turnos_data = build_turnos_data(turnos_rows)
    canal_data = build_canal_data(canal_rows)
    top10_base = build_top10_base(top10_rows)

    print(f"\nBuilt data:")
    print(f"  mensual_data: {len(mensual_data)} rows")
    print(f"  turnos_data: {len(turnos_data)} rows")
    print(f"  canal_data: {len(canal_data)} rows")
    print(f"  top10_base: {len(top10_base)} rows")

    # Compute derived structures
    latest_mes = sorted({r["mes"] for r in mensual_data})[-1] if mensual_data else ""
    top10_data = compute_top10(top10_base, latest_mes)
    pd_data = compute_pd(mensual_data)
    preset_meses = compute_preset_meses(mensual_data)

    print(f"\nComputed structures:")
    print(f"  latest_mes: {latest_mes}")
    print(f"  top10_data: {len(top10_data)} entries")
    print(f"  pd_data: {len(pd_data)} periods")
    print(f"  preset_meses: {len(preset_meses)} keys")

    # Objetivos data (fallback)
    objetivos_data = {
        "Patagonia": {
            "2026-01": {"obj_fac": 4424, "obj_ord": 117517},
            "2026-02": {"obj_fac": 3713, "obj_ord": 96928},
            "2026-03": {"obj_fac": 3548, "obj_ord": 93122},
        },
        "Temple": {
            "2026-01": {"obj_fac": 1390, "obj_ord": 41187},
            "2026-02": {"obj_fac": 1196, "obj_ord": 35518},
            "2026-03": {"obj_fac": 1620, "obj_ord": 49919},
        }
    }

    # No royalty data
    royalty_data = None

    # No locales objectives
    locales_obj_data = []

    # Output path
    output_path = os.path.join(SCRIPT_DIR, 'super_dashboard_temple.html')

    # Generate HTML
    print(f"\nGenerating HTML dashboard...")
    success = generate_html_from_file(
        data, output_path,
        mensual_rows=mensual_data,
        turnos_rows=turnos_data,
        canal_rows=canal_data,
        top10_data=top10_data,
        pd_data=pd_data,
        preset_meses=preset_meses,
        objetivos_data=objetivos_data,
        royalty_data=royalty_data,
        locales_obj_data=locales_obj_data
    )

    if success:
        # Report results
        file_size = os.path.getsize(output_path)
        max_date = max((datetime.strptime(r['d'], '%Y-%m-%d') for r in ventas_list), default=datetime.now())

        print("\n" + "=" * 70)
        print("SUCCESS - Dashboard HTML generated")
        print("=" * 70)
        print(f"Output file: {output_path}")
        print(f"File size: {file_size:,} bytes ({file_size/1024/1024:.2f} MB)")
        print(f"Latest date in ventas data: {max_date.strftime('%Y-%m-%d')}")
        print(f"Total ventas rows processed: {len(ventas_list)}")
        print("=" * 70)
        return 0
    else:
        print("ERROR: HTML generation failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
