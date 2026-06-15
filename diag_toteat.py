#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_toteat.py
Diagnóstico: muestra la estructura completa de la respuesta de la API de Toteat
para un día puntual, sin escribir nada en BQ.

Uso:
  python -X utf8 diag_toteat.py --fecha 20260501
"""

import argparse
import requests
from datetime import datetime

TOTEAT_BASE  = "https://api.toteat.com/mw/or/1.0"
TOTEAT_XIU   = "1003"
TOTEAT_XIR   = "5862845152100352"
TOTEAT_XIL   = "1"
TOTEAT_TOKEN = "Cp7U3WnJGPrIR4urdU2u7pYxNkbJxiVT"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", required=True, help="Fecha YYYYMMDD a inspeccionar")
    args = parser.parse_args()

    ini = end = datetime.strptime(args.fecha, "%Y%m%d").date()

    url = (
        f"{TOTEAT_BASE}/sales"
        f"?xir={TOTEAT_XIR}&xil={TOTEAT_XIL}&xiu={TOTEAT_XIU}"
        f"&xapitoken={TOTEAT_TOKEN}"
        f"&ini={ini.strftime('%Y%m%d')}&end={end.strftime('%Y%m%d')}"
    )

    print(f"\n[URL] {url}\n")

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    resp = r.json()

    # ── 1. Claves de la respuesta ──────────────────────────────────────────
    print("=== CLAVES DE LA RESPUESTA ===")
    for k, v in resp.items():
        if k == "data":
            print(f"  data: [{len(v)} items]")
        else:
            print(f"  {k}: {v}")

    ordenes = resp.get("data", [])
    if not ordenes:
        print("\n  Sin ordenes para esta fecha.")
        return

    # ── 2. Claves de la primera orden ─────────────────────────────────────
    print("\n=== CLAVES DE UNA ORDEN (primera) ===")
    o = ordenes[0]
    for k, v in o.items():
        if k == "products":
            print(f"  products: [{len(v)} items]")
        elif k == "paymentForms":
            print(f"  paymentForms: {v}")
        else:
            print(f"  {k}: {v}")

    # ── 3. Claves de un producto ───────────────────────────────────────────
    if o.get("products"):
        print("\n=== CLAVES DE UN PRODUCTO (primer producto de la primera orden) ===")
        p = o["products"][0]
        for k, v in p.items():
            print(f"  {k}: {v}")

    # ── 4. Totales por campo ───────────────────────────────────────────────
    print("\n=== TOTALES ===")
    print(f"  Ordenes recibidas       : {len(ordenes)}")

    orden_ids   = {str(o.get("orderId","")) for o in ordenes}
    payment_ids = {str(o.get("paymentId","")) for o in ordenes}
    print(f"  orderId unicos          : {len(orden_ids)}")
    print(f"  paymentId unicos        : {len(payment_ids)}")

    # Suma de total por orderId único (evita duplicados por split de pago)
    seen_orders = {}
    for o in ordenes:
        oid = str(o.get("orderId",""))
        if oid not in seen_orders:
            seen_orders[oid] = float(o.get("total", 0))
    suma_total_unico = sum(seen_orders.values())
    suma_total_bruto = sum(float(o.get("total", 0)) for o in ordenes)

    # Suma de campos por producto
    suma_payed    = 0.0
    suma_netprice = 0.0
    n_productos   = 0
    for o in ordenes:
        for p in o.get("products", []):
            suma_payed    += float(p.get("payed", 0))
            suma_netprice += float(p.get("netPrice", 0)) * float(p.get("quantity", 1))
            n_productos   += 1

    print(f"  Productos totales       : {n_productos}")
    print(f"  SUM(payed/producto)     : $ {suma_payed:,.2f}   <- lo que usa Dinero en BQ")
    print(f"  SUM(netPrice x qty)     : $ {suma_netprice:,.2f}  <- precio neto sin desc/imp")
    print(f"  SUM(total) bruto        : $ {suma_total_bruto:,.2f}  <- puede incluir dups por split")
    print(f"  SUM(total) por ord unica: $ {suma_total_unico:,.2f}  <- por orderId unico")

    # ── 5. Ordenes con split de pago ──────────────────────────────────────
    splits = [o for o in ordenes if len(o.get("paymentForms", [])) > 1]
    print(f"\n  Ordenes con split de pago: {len(splits)}")
    if splits:
        ex = splits[0]
        print(f"  Ejemplo orderId={ex.get('orderId')} total={ex.get('total')} paymentForms={ex.get('paymentForms')}")

    # ── 6. Campos de paginacion ───────────────────────────────────────────
    print("\n=== CAMPOS DE PAGINACION EN LA RESPUESTA ===")
    pag_keys = [k for k in resp.keys() if any(x in k.lower() for x in
                ["page","total","count","limit","offset","next","has_more","size"])]
    if pag_keys:
        for k in pag_keys:
            print(f"  {k}: {resp[k]}")
    else:
        print("  No se encontraron campos de paginacion.")
        print(f"  Claves disponibles: {list(resp.keys())}")


if __name__ == "__main__":
    main()
