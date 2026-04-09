"""
Wave 2 — 8 consultas read-only handlers.

REGLAS:
- NUNCA usar GET /accounts — usar GET /categories
- NUNCA escribir en MongoDB (estos handlers son solo lectura)
- Usan alegra.get() para todos los GETs — no request_with_verify() (eso es para writes)
- Ejecutan inmediatamente sin ExecutionCard (is_read_only_tool == True)
"""
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from services.alegra.client import AlegraClient


async def handle_consultar_plan_cuentas(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /categories — NUNCA /accounts (da 403)."""
    try:
        data = await alegra.get("categories")
        return {"success": True, "data": data, "count": len(data) if isinstance(data, list) else 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando plan de cuentas: {str(e)}"}


async def handle_consultar_journals(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /journals con filtros opcionales por fecha."""
    try:
        params = {"limit": tool_input.get("limit", 50)}
        if tool_input.get("date_from"):
            params["date[from]"] = tool_input["date_from"]
        if tool_input.get("date_to"):
            params["date[to]"] = tool_input["date_to"]
        data = await alegra.get("journals", params=params)
        return {"success": True, "data": data, "count": len(data) if isinstance(data, list) else 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando journals: {str(e)}"}


async def handle_consultar_balance(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /balance con parametros de fecha."""
    try:
        params = {}
        if tool_input.get("date_from"):
            params["start-date"] = tool_input["date_from"]
        if tool_input.get("date_to"):
            params["end-date"] = tool_input["date_to"]
        data = await alegra.get("balance", params=params)
        return {"success": True, "data": data, "count": 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando balance: {str(e)}"}


async def handle_consultar_estado_resultados(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /income-statement — Estado de Resultados desde Alegra (no MongoDB)."""
    try:
        params = {}
        if tool_input.get("date_from"):
            params["start-date"] = tool_input["date_from"]
        if tool_input.get("date_to"):
            params["end-date"] = tool_input["date_to"]
        data = await alegra.get("income-statement", params=params)
        return {"success": True, "data": data, "count": 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando estado de resultados: {str(e)}"}


async def handle_consultar_pagos(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /payments."""
    try:
        params = {}
        if tool_input.get("date_from"):
            params["date[from]"] = tool_input["date_from"]
        if tool_input.get("date_to"):
            params["date[to]"] = tool_input["date_to"]
        data = await alegra.get("payments", params=params)
        return {"success": True, "data": data, "count": len(data) if isinstance(data, list) else 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando pagos: {str(e)}"}


async def handle_consultar_contactos(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /contacts."""
    try:
        params = {}
        if tool_input.get("query"):
            params["name"] = tool_input["query"]
        data = await alegra.get("contacts", params=params)
        return {"success": True, "data": data, "count": len(data) if isinstance(data, list) else 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando contactos: {str(e)}"}


async def handle_consultar_items(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /items."""
    try:
        data = await alegra.get("items")
        return {"success": True, "data": data, "count": len(data) if isinstance(data, list) else 1}
    except Exception as e:
        return {"success": False, "error": f"Error consultando items: {str(e)}"}


async def handle_consultar_movimiento_cuenta(
    tool_input: dict,
    alegra: AlegraClient,
    db: AsyncIOMotorDatabase,
    event_bus: Any,
    user_id: str,
) -> dict:
    """GET /journals filtrado por account_id."""
    try:
        account_id = tool_input.get("account_id")
        if not account_id:
            return {"success": False, "error": "account_id es requerido para consultar_movimiento_cuenta"}
        params = {"account": account_id, "limit": tool_input.get("limit", 50)}
        if tool_input.get("date_from"):
            params["date[from]"] = tool_input["date_from"]
        if tool_input.get("date_to"):
            params["date[to]"] = tool_input["date_to"]
        data = await alegra.get("journals", params=params)
        return {
            "success": True,
            "data": data,
            "count": len(data) if isinstance(data, list) else 1,
            "account_id": account_id,
        }
    except Exception as e:
        return {"success": False, "error": f"Error consultando movimiento de cuenta: {str(e)}"}
