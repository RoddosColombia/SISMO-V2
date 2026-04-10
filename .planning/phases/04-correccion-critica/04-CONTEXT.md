# SESION DE CORRECCION CRITICA — SISMO V2

## PASO 1: Eliminar escrituras MongoDB del Contador
Buscar en `backend/agents/contador/handlers/` las escrituras a `inventario_motos` y `loanbook`:
- `facturacion.py` lineas ~76,82,151,157
- `cartera.py` linea ~56

ELIMINAR esas escrituras MongoDB. Reemplazar cada una por un `await publish_event()` con el evento correspondiente (`factura.venta.creada` o `pago.cuota.registrado`) con payload enriquecido.

El Contador NUNCA escribe en MongoDB excepto `roddos_events`, `conciliacion_jobs` y `backlog_movimientos`.

## PASO 2: Corregir formato entries para Alegra
Buscar en todos los handlers el formato de entries. Si hay `{"account": {"id": X}}` cambiarlo a `{"id": str(X), "debit": N, "credit": N}`. Alegra espera `id` directo, NO anidado en `account`.

## PASO 3: Obtener IDs reales de Alegra
Ejecutar contra Alegra real:
- `GET /categories` para obtener TODAS las categorias con sus IDs internos
- `GET /bank-accounts` para obtener IDs reales de bancos

Guardar el mapeo completo codigo NIIF -> ID Alegra en `.planning/mapeo_alegra_ids.json`.

**Credenciales:** almacenadas en variables de entorno, NO en archivos commitables.

## PASO 4: Actualizar tools.py con IDs reales
Actualizar `tools.py` y el system prompt del Contador con los IDs REALES de Alegra (no codigos NIIF).
- Cuenta clave: ingresos cuotas cartera = 41502001 Creditos Directos Roddos
- CXC Socios = 132505
- Fallback gastos = buscar ID real de Gastos Generales
- NUNCA 5495

## PASO 5: Reescribir CLAUDE.md
- ROG-4 reforzada: Contador solo Alegra, DataKeeper actualiza MongoDB, Loanbook dueno de creditos
- Formato entries correcto
- Mapeo IDs como referencia
- Escrituras MongoDB permitidas/prohibidas
- Estado del proyecto actualizado

## PASO 6: Verificar todo
- `grep` anti-MongoDB (0 resultados excluyendo bus y conciliacion)
- Journal de prueba real POST+GET+DELETE
- pytest completo
- commit y push
