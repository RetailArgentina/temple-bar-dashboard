"""
whatsapp_agent.py
Agente IA retail vía WhatsApp: session management, Claude API loop y access control.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from google.cloud import firestore

from whatsapp_tools import (
    TOOL_DEFINITIONS,
    VIEWER_TOOL_DEFINITIONS,
    query_retail,
    get_objectives_for_tool,
    query_product,
)

# ── Session Management ─────────────────────────────────────────────────────────

SESSION_TTL_HOURS = 2
MAX_MESSAGES      = 10


def get_session(db, phone: str) -> list:
    """Retorna historial activo. Retorna [] si no existe o expiró (>2h)."""
    doc = db.collection("sessions").document(phone).get()
    if not doc.exists:
        return []

    data = doc.to_dict()
    last_activity = data.get("last_activity")

    if last_activity:
        if hasattr(last_activity, "tzinfo") and last_activity.tzinfo is not None:
            last_activity = last_activity.replace(tzinfo=None)
        if datetime.utcnow() - last_activity > timedelta(hours=SESSION_TTL_HOURS):
            return []

    return data.get("messages", [])


def save_session(db, phone: str, messages: list, user_name: str, role: str) -> None:
    """Persiste los últimos MAX_MESSAGES mensajes en Firestore."""
    db.collection("sessions").document(phone).set({
        "messages":      messages[-MAX_MESSAGES:],
        "last_activity": datetime.utcnow(),
        "user_name":     user_name,
        "role":          role,
    })


# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sos un analista de ventas senior de Temple Bar Argentina.
Respondés preguntas sobre ventas retail de 3 marcas: Temple, Patagonia y Feriado.

REGLAS DE FORMATO (respuestas van a WhatsApp):
- Texto plano únicamente, sin markdown
- Emojis para jerarquía visual: 📊 ✅ ⚠️ 🔵 🟣 🟢
- Números en millones con M (ej: $600.5M). Facturación en pesos argentinos.
- Sin tablas — usá listas simples con saltos de línea
- Respuestas concisas y ejecutivas

SIEMPRE incluir en análisis de ventas:
- Facturación + órdenes + ticket promedio
- Cumplimiento real % = real / objetivo mensual × 100
- Cumplimiento esperado % = días transcurridos / días del mes × 100 (pace)
- Brecha en puntos porcentuales entre ambos
- Monto que falta para estar en pace (si hay brecha negativa)

Si no tenés datos para responder, decilo claramente. No inventes números.
Respondé siempre en español."""


# ── Access Control ─────────────────────────────────────────────────────────────

def get_user(phone: str, config: dict) -> dict | None:
    """Retorna el usuario si está en la whitelist, None si no."""
    for user in config.get("users", []):
        if user["phone"] == phone:
            return user
    return None


# ── Serialization helper ───────────────────────────────────────────────────────

def _serialize_content(content) -> list:
    """Convierte bloques del SDK de Anthropic a dicts planos para Firestore.
    Solo incluye los campos que la API de Anthropic acepta (sin nulls)."""
    result = []
    for block in content:
        if hasattr(block, "type"):
            btype = block.type if not isinstance(block, dict) else block.get("type")
            if btype == "text":
                result.append({"type": "text", "text": block.text if hasattr(block, "text") else block["text"]})
            elif btype == "tool_use":
                result.append({
                    "type":  "tool_use",
                    "id":    block.id    if hasattr(block, "id")    else block["id"],
                    "name":  block.name  if hasattr(block, "name")  else block["name"],
                    "input": block.input if hasattr(block, "input") else block["input"],
                })
            elif isinstance(block, dict):
                result.append(block)
        elif isinstance(block, dict):
            result.append(block)
        else:
            result.append({"type": "text", "text": str(block)})
    return result


# ── Tool Executor ──────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict, bq_client) -> dict:
    if tool_name == "query_retail":
        return query_retail(bq_client, **tool_input)
    elif tool_name == "get_objectives":
        return get_objectives_for_tool(**tool_input)
    elif tool_name == "query_product":
        return query_product(bq_client, **tool_input)
    return {"error": f"Tool desconocida: {tool_name}"}


# ── Agent Loop ─────────────────────────────────────────────────────────────────

def run_agent(
    user_message: str,
    history: list,
    user_role: str,
    bq_client,
    anthropic_client,
) -> tuple[str, list]:
    """
    Ejecuta el loop del agente Claude con tool use.
    Retorna (texto_respuesta, historial_actualizado).
    """
    tools    = TOOL_DEFINITIONS if user_role == "admin" else VIEWER_TOOL_DEFINITIONS
    messages = history + [{"role": "user", "content": user_message}]

    for _ in range(10):
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "No pude procesar tu consulta."
            )
            messages.append({"role": "assistant", "content": _serialize_content(response.content)})
            return text, messages

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": _serialize_content(response.content)})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, bq_client)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(result, ensure_ascii=False, default=str),
                    })
            messages.append({"role": "user", "content": tool_results})

    return "Ocurrió un error procesando tu consulta.", messages
