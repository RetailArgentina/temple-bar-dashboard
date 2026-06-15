#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crea las vistas de Feriado en BQ optimizadas para Looker Studio."""
import google.auth
from google.cloud import bigquery

creds, _ = google.auth.default()
client = bigquery.Client(project="temple-bar-439715", credentials=creds)

# ── Vista 1: vw_Ventas_Feriado ────────────────────────────────────────────────

VIEW_VENTAS = "temple-bar-439715.Feriado.vw_Ventas_Feriado"

ventas_query = """
SELECT
  v.Fecha_Apertura,
  v.Fecha_Cierre,

  -- Fecha de negocio: órdenes que cierran 00:00–03:59 → día anterior
  v.fecha_negocio                           AS Fecha,
  EXTRACT(YEAR  FROM v.fecha_negocio)       AS Anio,
  EXTRACT(MONTH FROM v.fecha_negocio)       AS Mes_Num,
  FORMAT_DATE('%B',    v.fecha_negocio)     AS Mes_Nombre,
  FORMAT_DATE('%Y-%m', v.fecha_negocio)     AS Anio_Mes,
  DATE_TRUNC(v.fecha_negocio, WEEK(MONDAY)) AS Semana_Inicio,
  FORMAT_DATE('%G-W%V',v.fecha_negocio)     AS Semana,
  EXTRACT(DAYOFWEEK FROM v.fecha_negocio)   AS Dia_Semana_Num,
  FORMAT_DATE('%A',    v.fecha_negocio)     AS Dia_Semana,

  v.Establecimiento,

  -- Turno: Tarde 10-18h / Noche resto (re-derivado desde hora_apertura)
  CASE
    WHEN EXTRACT(HOUR FROM v.hora_apertura) BETWEEN 10 AND 18 THEN 'Tarde'
    ELSE 'Noche'
  END                                       AS Turno,

  v.Canal,

  -- Sector: distingue Salón vs tipo de delivery
  CASE
    WHEN v.Canal = 'Salón'
      THEN 'Salón'
    WHEN v.medio_pago IN ('PedidosYa', 'PedidosYa Vouchers')
      THEN 'Delivery PedidosYa'
    WHEN v.medio_pago IN ('Rappi', 'Rappi Sistema')
      THEN 'Delivery Rappi'
    WHEN v.medio_pago = 'Tucan'
      THEN 'Delivery Tucan'
    WHEN v.Canal = 'Delivery' AND v.mesa LIKE 'V-9%'
      THEN 'Delivery App'
    WHEN v.Canal = 'Delivery'
      THEN 'Delivery Propio'
    ELSE 'Salón'
  END                                       AS Sector,

  v.mozo                                    AS Mozo,
  v.producto_id                             AS Producto_ID,
  v.Producto,
  v.Mix                                     AS Categoria_Toteat,
  bd.categoria_1                            AS Categoria_1,
  bd.categoria_2                            AS Categoria_2,
  emp.categoria_empresa                     AS Categoria_Empresa,

  v.medio_pago                              AS Medio_Pago,
  CASE
    WHEN v.medio_pago IN (
      'Visa','Mastercard','Amex Credito','Cabal','Tarjeta Naranja',
      'Mastercard Precarga','Visa Precarga'
    ) THEN 'Tarjeta Crédito'
    WHEN v.medio_pago IN (
      'Débito Visa','Débito Maestro','Débito Visa Sin','Débito Maestro Sin'
    ) THEN 'Tarjeta Débito'
    WHEN v.medio_pago IN ('Mercadopago','Mercadopago Sin','Tucan')
      THEN 'Billetera Digital'
    WHEN v.medio_pago IN ('PedidosYa','PedidosYa Vouchers','Rappi','Rappi Sistema')
      THEN 'App Delivery'
    WHEN v.medio_pago IN ('Efectivo','Efectivo Sin')
      THEN 'Efectivo'
    WHEN v.medio_pago = 'Transferencia'
      THEN 'Transferencia'
    ELSE 'Otros'
  END                                       AS Medio_Pago_Grupo,

  v.Cantidad,
  v.Dinero                                  AS Facturacion,
  v.precio_unitario * v.Cantidad            AS Precio_A_Pagar,
  v.descuentos                              AS Descuentos,
  v.impuestos                               AS Impuestos,

  CASE
    WHEN bd.ml_por_unidad IS NOT NULL
    THEN ROUND(v.Cantidad * bd.ml_por_unidad / 1000.0, 4)
    ELSE NULL
  END                                       AS Litros,
  bd.ml_por_unidad                          AS ML_Por_Unidad,

  v.orden_id                                AS Orden_ID,
  v.total_orden                             AS Total_Orden,

  -- Comensales: solo primera fila por orden para evitar duplicados
  CASE WHEN v._rn = 1 THEN v.n_clientes ELSE 0 END  AS Comensales,

  CAST(v._rn = 1 AS INT64)                  AS cuenta_orden

FROM (
  SELECT *,
    -- Fecha de negocio: cierre 00:00–03:59 → día anterior
    CASE
      WHEN EXTRACT(HOUR FROM hora_cierre) < 4
      THEN DATE_SUB(CAST(hora_cierre AS DATE), INTERVAL 1 DAY)
      ELSE CAST(hora_cierre AS DATE)
    END                                                                   AS fecha_negocio,
    Fecha                                                                 AS Fecha_Apertura,
    CAST(hora_cierre AS DATE)                                             AS Fecha_Cierre,
    ROW_NUMBER() OVER (PARTITION BY orden_id ORDER BY producto_id, Producto) AS _rn
  FROM `temple-bar-439715.Feriado.Ventas_Toteat`
  WHERE Fecha IS NOT NULL
) v
LEFT JOIN `temple-bar-439715.Feriado.Cat_BD`      bd  ON bd.producto_id  = v.producto_id
LEFT JOIN `temple-bar-439715.Feriado.Cat_Empresa` emp ON emp.producto_id = v.producto_id
"""

# ── Vista 2: vw_Consumo_Insumos ───────────────────────────────────────────────

VIEW_INSUMOS = "temple-bar-439715.Feriado.vw_Consumo_Insumos"

insumos_query = """
SELECT
  -- Fecha de negocio: cierre 00:00–03:59 → día anterior
  CASE
    WHEN EXTRACT(HOUR FROM v.hora_cierre) < 4
    THEN DATE_SUB(CAST(v.hora_cierre AS DATE), INTERVAL 1 DAY)
    ELSE CAST(v.hora_cierre AS DATE)
  END                                       AS Fecha,
  v.Fecha                                   AS Fecha_Apertura,
  CAST(v.hora_cierre AS DATE)               AS Fecha_Cierre,
  FORMAT_DATE('%Y-%m',
    CASE WHEN EXTRACT(HOUR FROM v.hora_cierre) < 4
    THEN DATE_SUB(CAST(v.hora_cierre AS DATE), INTERVAL 1 DAY)
    ELSE CAST(v.hora_cierre AS DATE) END)   AS Anio_Mes,
  v.Establecimiento,
  v.Canal,

  -- Turno: Tarde 10-18h / Noche resto
  CASE
    WHEN EXTRACT(HOUR FROM v.hora_apertura) BETWEEN 10 AND 18 THEN 'Tarde'
    ELSE 'Noche'
  END                                       AS Turno,

  -- Sector
  CASE
    WHEN v.Canal = 'Salón'
      THEN 'Salón'
    WHEN v.medio_pago IN ('PedidosYa', 'PedidosYa Vouchers')
      THEN 'Delivery PedidosYa'
    WHEN v.medio_pago IN ('Rappi', 'Rappi Sistema')
      THEN 'Delivery Rappi'
    WHEN v.medio_pago = 'Tucan'
      THEN 'Delivery Tucan'
    WHEN v.Canal = 'Delivery' AND v.mesa LIKE 'V-9%'
      THEN 'Delivery App'
    WHEN v.Canal = 'Delivery'
      THEN 'Delivery Propio'
    ELSE 'Salón'
  END                                       AS Sector,

  v.producto_id                             AS Producto_ID,
  v.Producto,
  bd.categoria_1                            AS Categoria_1,
  bd.categoria_2                            AS Categoria_2,
  emp.categoria_empresa                     AS Categoria_Empresa,

  r.insumo_id                               AS Insumo_ID,
  r.ingrediente                             AS Ingrediente,
  r.tipo_unidad                             AS Unidad,
  r.costo_insumo                            AS Costo_Insumo_Unit,
  r.presentacion                            AS Presentacion,

  v.Cantidad                                AS Unidades_Vendidas,
  r.uso                                     AS Uso_Por_Plato,
  ROUND(v.Cantidad * r.uso, 4)              AS Consumo_Total,
  r.tipo_unidad                             AS Consumo_Unidad,
  ROUND(v.Cantidad * r.costo_insumo, 2)     AS Costo_Consumo_Total,

  v.Dinero                                  AS Facturacion,
  v.orden_id                                AS Orden_ID

FROM `temple-bar-439715.Feriado.Ventas_Toteat`    v
JOIN `temple-bar-439715.Feriado.Recetas_BQ`       r   ON r.producto_id  = v.producto_id
LEFT JOIN `temple-bar-439715.Feriado.Cat_BD`      bd  ON bd.producto_id  = v.producto_id
LEFT JOIN `temple-bar-439715.Feriado.Cat_Empresa` emp ON emp.producto_id = v.producto_id
WHERE v.Fecha IS NOT NULL
  AND r.ingrediente IS NOT NULL
  AND r.ingrediente != ''
"""

# ── Crear / reemplazar vistas ─────────────────────────────────────────────────

for view_id, query, nombre in [
    (VIEW_VENTAS,  ventas_query,  "vw_Ventas_Feriado"),
    (VIEW_INSUMOS, insumos_query, "vw_Consumo_Insumos"),
]:
    client.delete_table(view_id, not_found_ok=True)
    view_ref = bigquery.Table(view_id)
    view_ref.view_query = query
    client.create_table(view_ref)
    print(f"Vista creada: {view_id}")

    q = f"SELECT COUNT(*) as n FROM `{view_id}` LIMIT 1"
    for r in client.query(q).result():
        print(f"  Filas: {r['n']:,}")

print()

# ── Verificar litros y consumo ────────────────────────────────────────────────
print("Litros por categoría empresa (últimos 30 días):")
q = """
SELECT Categoria_Empresa, ROUND(SUM(Litros),1) as litros_total
FROM `temple-bar-439715.Feriado.vw_Ventas_Feriado`
WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND Litros IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
"""
for r in client.query(q).result():
    print(f"  {r['Categoria_Empresa']}: {r['litros_total']} L")

print()
print("Top insumos consumidos (últimos 30 días):")
q2 = """
SELECT Ingrediente, Unidad, ROUND(SUM(Consumo_Total),1) as consumo
FROM `temple-bar-439715.Feriado.vw_Consumo_Insumos`
WHERE Fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10
"""
for r in client.query(q2).result():
    print(f"  {r['Ingrediente']}: {r['consumo']} {r['Unidad']}")
