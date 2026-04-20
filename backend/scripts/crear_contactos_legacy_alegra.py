"""
crear_contactos_legacy_alegra.py — BUILD 0.3 (V2)

Crea en Alegra los contactos faltantes para los 14 créditos legacy
que no tienen alegra_contact_id, luego actualiza loanbook_legacy y
publica evento en el bus roddos_events.

Usage:
    python -m scripts.crear_contactos_legacy_alegra [--dry-run]

Requiere MONGO_URL en el entorno (Render env var o export local).
Credenciales Alegra: hardcodeadas (contabilidad@roddos.com).
"""
import argparse
import asyncio
import base64
import json
import os
from datetime import datetime, timezone

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# ── Alegra ────────────────────────────────────────────────────────────────────
ALEGRA_BASE  = "https://api.alegra.com/api/v1"
ALEGRA_USER  = "contabilidad@roddos.com"
ALEGRA_TOKEN = "17a8a3b7016e1c15c514"
ALEGRA_AUTH  = base64.b64encode(f"{ALEGRA_USER}:{ALEGRA_TOKEN}".encode()).decode()
HEADERS      = {
    "Authorization": f"Basic {ALEGRA_AUTH}",
    "Content-Type":  "application/json",
    "Accept":        "application/json",
}

# ── Mongo ─────────────────────────────────────────────────────────────────────
V2_DB     = "sismo-v2"
COL_LB    = "loanbook_legacy"
COL_EVENTS = "roddos_events"

# ── Known cédulas sin contacto (pre-verificadas) ──────────────────────────────
CEDULAS_SIN_CONTACTO = {
    "1023927115", "150201557",  "1014270352", "1015994188",
    "4877500",    "5203386",    "5319879",    "1000572543",
    "1070624740", "1073609685", "1005581753", "1022337560",
    "1023015723", "1098636229",
}


# ── Alegra helpers ────────────────────────────────────────────────────────────

async def crear_contacto(client: httpx.AsyncClient, doc: dict) -> tuple[str | None, str]:
    """
    POST /contacts para crear un contacto.
    Returns (alegra_id, status) where status ∈ 'creado'|'existia'|'error'.
    """
    nombre = doc["nombre_completo"]
    cedula = doc["cedula"]
    # Alegra Colombia: kindOfPerson=PERSON_ENTITY requiere nameObject, no name plano
    partes = nombre.split()
    first_name = partes[0] if partes else nombre
    last_name  = " ".join(partes[1:]) if len(partes) > 1 else ""
    payload = {
        "nameObject":           {"firstName": first_name, "lastName": last_name},
        "identificationObject": {"type": "CC", "number": cedula},
        "type":                 "client",
        "kindOfPerson":         "PERSON_ENTITY",
        "observations":  (
            f"Cartera legacy - aliado={doc['aliado']} "
            f"placa={doc.get('placa') or 'N/A'}"
        ),
    }

    try:
        resp = await client.post(f"{ALEGRA_BASE}/contacts", json=payload, headers=HEADERS, timeout=20)

        if resp.status_code in (200, 201):
            data = resp.json()
            alegra_id = str(data.get("id", ""))
            return alegra_id, "creado"

        # 400 o 409 puede significar "ya existe"
        if resp.status_code in (400, 409):
            body_text = resp.text.lower()
            if any(kw in body_text for kw in ("ya exist", "already", "duplicat", "exist")):
                # Buscar por identificación
                found_id = await buscar_contacto_por_cedula(client, cedula)
                if found_id:
                    return found_id, "existia"

        # Otro error
        print(f"  [ERROR] {cedula} | HTTP {resp.status_code} | {resp.text[:200]}")
        return None, f"error_http_{resp.status_code}"

    except Exception as exc:
        print(f"  [ERROR] {cedula} | Exception: {exc}")
        return None, f"error_exc"


async def buscar_contacto_por_cedula(client: httpx.AsyncClient, cedula: str) -> str | None:
    """GET /contacts?identification={cedula} → id del primer resultado."""
    try:
        resp = await client.get(
            f"{ALEGRA_BASE}/contacts",
            params={"identification": cedula, "limit": 1},
            headers=HEADERS,
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return str(data[0].get("id", ""))
            if isinstance(data, dict) and data.get("data"):
                return str(data["data"][0].get("id", ""))
    except Exception as exc:
        print(f"  [WARN] buscar_contacto {cedula}: {exc}")
    return None


# ── Core ──────────────────────────────────────────────────────────────────────

async def run(dry_run: bool) -> None:
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}BUILD 0.3 (V2) — crear_contactos_legacy_alegra")
    print(f"DB     : {V2_DB}.{COL_LB}")
    print(f"Alegra : {ALEGRA_BASE}")
    print()

    # ── 1. Cargar docs sin alegra_contact_id ──────────────────────────────────
    mongo_url = os.environ["MONGO_URL"]
    client_mg = AsyncIOMotorClient(mongo_url)
    col_lb    = client_mg[V2_DB][COL_LB]
    col_ev    = client_mg[V2_DB][COL_EVENTS]

    docs_sin_contacto = await col_lb.find(
        {"cedula": {"$in": list(CEDULAS_SIN_CONTACTO)}, "alegra_contact_id": None}
    ).to_list(length=100)

    print(f"Docs sin alegra_contact_id: {len(docs_sin_contacto)}")
    if len(docs_sin_contacto) == 0:
        print("Nada que hacer — todos los docs ya tienen contacto.")
        client_mg.close()
        return

    # Agrupar por cédula (puede haber cédula repetida con distintos créditos)
    cedulas_vistas: dict[str, dict] = {}
    for doc in docs_sin_contacto:
        cedula = doc["cedula"]
        if cedula not in cedulas_vistas:
            cedulas_vistas[cedula] = doc

    print(f"Cédulas únicas a procesar: {len(cedulas_vistas)}")
    print()

    if dry_run:
        for cedula, doc in cedulas_vistas.items():
            nombre_safe = doc['nombre_completo'].encode("ascii", "replace").decode("ascii")
            print(f"  {cedula} | {nombre_safe[:40]} | {doc['aliado']}")
        print("\n[DRY-RUN] Nada enviado a Alegra ni escrito en MongoDB.")
        client_mg.close()
        return

    # ── 2. Crear contactos en Alegra ──────────────────────────────────────────
    resultados: list[dict] = []
    n_creados   = 0
    n_existian  = 0
    lista_fallos: list[str] = []

    async with httpx.AsyncClient() as http:
        for cedula, doc in cedulas_vistas.items():
            nombre = doc["nombre_completo"].encode("ascii", "replace").decode("ascii")
            print(f"  Procesando {cedula} | {nombre[:35]:<35} ... ", end="", flush=True)

            alegra_id, status = await crear_contacto(http, doc)

            if alegra_id:
                print(f"OK  id={alegra_id}  [{status}]")
                resultados.append({"cedula": cedula, "alegra_id": alegra_id, "status": status})

                # ── 3. Actualizar loanbook_legacy (todos los créditos de esa cédula)
                now = datetime.now(timezone.utc)
                result = await col_lb.update_many(
                    {"cedula": cedula},
                    {"$set": {"alegra_contact_id": alegra_id, "updated_at": now}},
                )
                print(f"          -> MongoDB updated {result.modified_count} doc(s)")

                if status == "creado":
                    n_creados += 1
                else:
                    n_existian += 1
            else:
                print(f"FALLO [{status}]")
                lista_fallos.append(cedula)
                resultados.append({"cedula": cedula, "alegra_id": None, "status": status})

    # ── 5. Publicar evento en bus ─────────────────────────────────────────────
    await col_ev.insert_one({
        "event_type": "loanbook_legacy.contactos_creados",
        "source":     "script_crear_contactos",
        "timestamp":  datetime.utcnow(),
        "datos": {
            "creados":                n_creados,
            "ya_existian":            n_existian,
            "fallos":                 lista_fallos,
            "total_sin_contacto_previo": len(cedulas_vistas),
            "detalle": resultados,
        },
    })
    print("\nEvento publicado en roddos_events.")

    client_mg.close()

    # ── 6. Reporte final ──────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"REPORTE BUILD 0.3")
    print(f"  Creados en Alegra : {n_creados}")
    print(f"  Ya existian       : {n_existian}")
    print(f"  Fallos            : {len(lista_fallos)}")
    print()
    print(f"  {'CEDULA':<15}  {'ALEGRA_ID':<10}  STATUS")
    print(f"  {'-'*15}  {'-'*10}  {'-'*12}")
    for r in resultados:
        print(f"  {r['cedula']:<15}  {str(r['alegra_id'] or 'FALLO'):<10}  {r['status']}")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crea contactos legacy en Alegra")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar, no crear")
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))
