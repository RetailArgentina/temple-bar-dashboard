-- WTC (Uruguay): carga manual mensual + tipo de cambio UYU→ARS.
-- Spec: docs/superpowers/specs/2026-10-01-wtc-carga-manual-design.md. Se corre una sola vez.
CREATE TABLE IF NOT EXISTS `temple-bar-439715.Corporativo.wtc_manual_mensual` (
  mes             DATE      NOT NULL OPTIONS(description="primer día del mes; clave"),
  facturacion_uyu NUMERIC   NOT NULL OPTIONS(description="pesos uruguayos, >= 0"),
  ordenes         INT64     NOT NULL,
  litros_cerveza  NUMERIC   NOT NULL OPTIONS(description="litros reales reportados por WTC"),
  cargado_por     STRING,
  cargado_en      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `temple-bar-439715.Corporativo.tipo_cambio_uyu_ars` (
  mes            DATE      NOT NULL OPTIONS(description="primer día del mes; clave"),
  ars_por_uyu    NUMERIC   NOT NULL OPTIONS(description="promedio de días hábiles, BCRA tipoCotizacion"),
  dias           INT64     NOT NULL,
  completo       BOOL      NOT NULL OPTIONS(description="true si el mes ya había cerrado al calcularlo"),
  actualizado_en TIMESTAMP
);
