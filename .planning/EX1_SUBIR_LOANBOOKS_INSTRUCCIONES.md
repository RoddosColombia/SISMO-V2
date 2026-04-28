# EX1+EX2 — Subir loanbooks faltantes desde Excel V1 + marcar entrega jueves

## Que hace el script

`backend/scripts/subir_loanbooks_excel_v1.py` con datos embebidos de las 43 filas del Excel.

3 modos:
1. **`--dry-run`** (default) - Solo imprime que crearia, NO toca DB
2. **`--ejecutar`** - Crea loanbooks + crm_clientes faltantes (idempotente)
3. **`--marcar-entrega-jueves`** - Marca las 10 Raider 27-28abr para entrega 2026-04-30

## ADVERTENCIA importante sobre telefonos

Los telefonos del Excel original venian truncados/incompletos en la lectura.
El script tiene placeholders (3015434981, 3004613796, etc.) que coincidiran
con los reales solo en algunos casos. **Despues de correr el dry-run vamos a
revisar fila por fila** para corregir los telefonos antes de ejecutar real.

Las cedulas, nombres, VINs y montos SI son los del Excel.

## Pasos

### 1. Push del script al repo

```powershell
cd C:\Users\AndresSanJuan\roddos-workspace\SISMO-V2
if (Test-Path .git\index.lock) { Remove-Item .git\index.lock -Force }

git add backend/scripts/subir_loanbooks_excel_v1.py
git add .planning/EX1_SUBIR_LOANBOOKS_INSTRUCCIONES.md

git commit -m "feat(import): script subir_loanbooks_excel_v1.py con 43 filas embebidas

Idempotente: solo crea loanbooks + crm_clientes que falten.
Modos: --dry-run (default), --ejecutar, --marcar-entrega-jueves.

Las 10 Raider del 27-28 abril (FE474-FE483) marcadas para entrega
programada 2026-04-30 (jueves).

Telefonos placeholder en el script - se corrigen despues del primer dry-run."

git push origin main
```

### 2. Esperar 1-2 min para deploy en Render

### 3. Dry-run desde Render Shell

```bash
# IMPORTANTE: cwd debe ser /opt/render/project/src/backend (no /src)
cd /opt/render/project/src/backend
python3 scripts/subir_loanbooks_excel_v1.py --dry-run
```

Output esperado:
- Lista de las 43 filas con estado: "OK existe" o "DRY_RUN crear"
- Resumen final: cuantos crearia

### 4. Revisar el output del dry-run

- Verificar que los que dice "ya existe" sean los correctos
- Verificar que los faltantes (los que crearia) sean los esperados
- **Compartir el output conmigo** para validar antes de ejecutar real

### 5. Ejecutar real (cuando hayamos revisado)

```bash
cd /opt/render/project/src/backend
python3 scripts/subir_loanbooks_excel_v1.py --ejecutar
```

### 6. Marcar entrega jueves para las 10 Raider 27-28abr

```bash
# Primero dry-run para ver cuales encuentra
cd /opt/render/project/src/backend
python3 scripts/subir_loanbooks_excel_v1.py --marcar-entrega-jueves

# Si OK, ejecutar real
python3 scripts/subir_loanbooks_excel_v1.py --marcar-entrega-jueves --ejecutar
```

### 7. Recalcular tarjetas frontend (cartera + recaudo)

Las tarjetas de Loanbook stats se calculan on-the-fly al cargar la pagina.
Pero conviene reiniciar el alegra_sync para que los IDs de Alegra queden
asociados:

```bash
# En Render Shell:
cd /opt/render/project/src/backend
python3 -c "
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from core.alegra_sync import detect_and_sync_new_invoices

async def main():
    cli = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = cli[os.environ['DB_NAME']]
    res = await detect_and_sync_new_invoices(db)
    print(f'sync result: {res}')
    cli.close()

asyncio.run(main())
"
```

Y luego en el frontend cargar `/loanbook` para que las stats se refresquen
desde MongoDB.

## Esquema del documento que se crea

Cada loanbook nuevo tendra estos campos:

```json
{
  "loanbook_id":           "LB-EXCEL-V1-NNN",
  "factura_alegra_id":     "FE444",
  "producto":              "RDX" | "RODANTE",
  "subtipo_rodante":       null | "comparendo" | "licencia",
  "plan_codigo":           "P52S",
  "modalidad_pago":        "semanal",
  "cliente_nombre":        "...",
  "cliente_cedula":        "...",
  "cliente_telefono":      "573...",
  "monto_original":        7800000,
  "cuota_inicial":         1460000,
  "cuota_periodica":       179900,
  "total_cuotas":          52,
  "fecha_factura":         "2026-03-02",
  "fecha_entrega":         "2026-03-05" | null,
  "estado_credito":        "activo" | "mora" | "saldado" | "pendiente_entrega",
  "metadata_producto": {
    "moto_modelo":         "RAIDER 125",
    "moto_vin":            "9FL25AF31VDB95057",
    "moto_motor":          "BF3AT13C2338",
    "moto_valor_origen":   7800000,
    "excel_v1_import": {
      "fila_excel":                    1,
      "cuotas_pagadas_historicas":     6,
      "cuotas_vencidas_historicas":    0,
      "valor_total_excel":             9354800.0,
      "saldo_excel":                   8275400.0,
      "estado_excel":                  "activo",
      "fuente":                        "Excel V1 importado 2026-04-28"
    }
  },
  "via":                   "import_excel_v1",
  "fecha_creacion":        "2026-04-28T...",
  "fecha_actualizacion":   "2026-04-28T..."
}
```

Y en `crm_clientes`:

```json
{
  "cedula":              "1283367",
  "nombre":              "Chenier Quintero",
  "telefono":            "573015434981",
  "mercately_phone":     "573015434981",
  "tags":                ["al_dia"],
  "loanbook_ids":        ["LB-EXCEL-V1-001"],
  "gestiones":           [],
  "via":                 "import_excel_v1"
}
```

## Notas

- El campo `excel_v1_import.saldo_excel` y `cuotas_pagadas_historicas` se
  guardan para auditoria pero el sistema NO los usa para calcular saldos en
  runtime - eso lo hace `services.loanbook.reglas_negocio.calcular_saldos()`
  on-demand. Despues de subir, los saldos del frontend se calcularan
  automaticamente.
- El script NO toca `inventario_motos` ni Alegra (ROG-4 OK).
- Los teléfonos pueden quedar incorrectos en la primera carga - ajustar
  manualmente despues con el panel de admin o un update one-shot.
