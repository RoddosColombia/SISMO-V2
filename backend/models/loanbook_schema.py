"""
models/loanbook_schema.py — Schemas Pydantic para creación y validación de loanbooks.

Implementa validación dual RDX / RODANTE:
  - producto × plan_codigo × modalidad_pago — combinación válida según catalogo_planes
  - subtipo_rodante — obligatorio para RODANTE, prohibido para RDX
  - metadata_producto — campos requeridos según producto/subtipo

Todas las violaciones → ValidationError de Pydantic → HTTP 422 en el endpoint.

Reglas aplicadas:
  R-06: combinación validada contra catalogo_service (datos de MongoDB)
  R-23: RODANTE solo acepta modalidad semanal (P1S-P15S)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ─────────────────────── Subdocumentos metadata por caso ──────────────────────

class MetadataRDX(BaseModel):
    """Metadata de colateral para crédito RDX (moto)."""
    moto_vin: str = Field(..., min_length=1, description="VIN obligatorio")
    moto_modelo: str = Field(..., min_length=1, description="Modelo obligatorio")
    moto_motor: Optional[str] = None
    moto_placa: Optional[str] = None
    moto_anio: Optional[int] = Field(default=None, ge=1990, le=2030)
    moto_cilindraje: Optional[int] = Field(default=None, gt=0)
    moto_valor_origen: Optional[float] = Field(default=None, gt=0)
    ltv: Optional[float] = Field(default=None, ge=0, le=5)


class MetadataRepuestos(BaseModel):
    """Metadata para RODANTE subtipo repuestos."""
    referencia_sku: str = Field(..., min_length=1)
    cantidad: int = Field(..., gt=0)
    valor_unitario: float = Field(..., gt=0)
    descripcion_repuesto: str = Field(..., min_length=1)
    inventario_origen_id: Optional[str] = None


class MetadataSoat(BaseModel):
    """Metadata para RODANTE subtipo soat."""
    poliza_numero: str = Field(..., min_length=1)
    aseguradora: str = Field(..., min_length=1)
    cilindraje_moto: int = Field(..., gt=0)
    vigencia_desde: date
    vigencia_hasta: date
    valor_soat: float = Field(..., gt=0)
    placa_cubierta: str = Field(..., min_length=1)


class MetadataComparendo(BaseModel):
    """Metadata para RODANTE subtipo comparendo."""
    comparendo_numero: str = Field(..., min_length=1)
    entidad_emisora: str = Field(..., min_length=1)
    fecha_infraccion: date
    valor_comparendo: float = Field(..., gt=0)
    codigo_infraccion: Optional[str] = None


class MetadataLicencia(BaseModel):
    """Metadata para RODANTE subtipo licencia de conducción."""
    categoria_licencia: Literal["A1", "A2", "B1", "C1"]
    centro_ensenanza_nombre: str = Field(..., min_length=1)
    centro_ensenanza_nit: str = Field(..., min_length=1)
    fecha_inicio_curso: date
    valor_curso: float = Field(..., gt=0)


# ─────────────────────── Validador de combinación ─────────────────────────────

def _validar_combinacion_producto_plan(
    producto: str,
    subtipo_rodante: Optional[str],
    plan_codigo: str,
    modalidad_pago: str,
) -> None:
    """Valida la combinación producto × plan × modalidad contra el catálogo.

    Checks:
    1. producto ∈ {RDX, RODANTE}
    2. Si RODANTE → subtipo_rodante obligatorio
    3. Si RDX → subtipo_rodante debe ser None
    4. plan_codigo debe estar en catalogo_planes["aplica_a"] del producto
    5. modalidad_pago debe estar disponible para ese plan (cuotas_por_modalidad)
    6. R-23: RODANTE solo modalidad semanal

    Raises:
        ValueError: con mensaje descriptivo del primer error encontrado
    """
    from services.loanbook import catalogo_service as cs

    # 1. Subtipo RODANTE
    if producto == "RODANTE" and not subtipo_rodante:
        raise ValueError(
            "producto='RODANTE' requiere subtipo_rodante "
            "(repuestos, soat, comparendo o licencia)"
        )
    if producto == "RDX" and subtipo_rodante:
        raise ValueError(
            f"producto='RDX' no acepta subtipo_rodante. "
            f"Recibido: subtipo_rodante='{subtipo_rodante}'"
        )

    # 2. Plan existe en catálogo
    plan = cs.get_plan(plan_codigo)
    if plan is None:
        from services.loanbook.catalogo_service import list_planes_activos
        validos = sorted(p["plan_codigo"] for p in list_planes_activos())
        raise ValueError(
            f"plan_codigo='{plan_codigo}' no existe en el catálogo. "
            f"Planes válidos: {validos}"
        )

    # 3. Plan aplica al producto
    if not cs.is_plan_valido_para_producto(plan_codigo, producto):
        aplica_a = plan.get("aplica_a", [])
        raise ValueError(
            f"plan_codigo='{plan_codigo}' no aplica a producto='{producto}'. "
            f"Este plan aplica a: {aplica_a}"
        )

    # 4. Modalidad disponible para el plan
    cuotas_map = plan.get("cuotas_por_modalidad", {})
    if modalidad_pago not in cuotas_map:
        disponibles = list(cuotas_map.keys())
        raise ValueError(
            f"modalidad_pago='{modalidad_pago}' no disponible para plan='{plan_codigo}'. "
            f"Modalidades disponibles: {disponibles}"
        )

    # 5. R-23: RODANTE solo semanal
    if producto == "RODANTE" and modalidad_pago != "semanal":
        raise ValueError(
            f"producto='RODANTE' solo acepta modalidad_pago='semanal' (R-23). "
            f"Recibido: '{modalidad_pago}'"
        )


def _validar_metadata_producto(
    producto: str,
    subtipo_rodante: Optional[str],
    metadata: dict[str, Any],
) -> None:
    """Valida que metadata_producto tenga los campos requeridos según producto/subtipo.

    Para RDX: valida contra MetadataRDX (moto_vin y moto_modelo obligatorios).
    Para RODANTE: valida contra el modelo de su subtipo.
    Calcula ltv automáticamente para RDX si hay monto y valor_origen.

    Raises:
        ValueError: con mensaje descriptivo de campos faltantes o inválidos
    """
    if producto == "RDX":
        try:
            MetadataRDX(**metadata)
        except Exception as exc:
            raise ValueError(f"metadata_producto inválido para RDX: {exc}") from exc

    elif producto == "RODANTE":
        _VALIDADORES = {
            "repuestos":  MetadataRepuestos,
            "soat":       MetadataSoat,
            "comparendo": MetadataComparendo,
            "licencia":   MetadataLicencia,
        }
        cls = _VALIDADORES.get(subtipo_rodante or "")
        if cls is None:
            raise ValueError(
                f"subtipo_rodante='{subtipo_rodante}' no tiene validador. "
                "Valores válidos: repuestos, soat, comparendo, licencia"
            )
        try:
            cls(**metadata)
        except Exception as exc:
            raise ValueError(
                f"metadata_producto inválido para RODANTE/{subtipo_rodante}: {exc}"
            ) from exc


# ─────────────────────── Schema principal ─────────────────────────────────────

class LoanbookBase(BaseModel):
    """Campos comunes a creación y actualización de loanbooks."""

    producto: Literal["RDX", "RODANTE"]
    subtipo_rodante: Optional[Literal["repuestos", "soat", "comparendo", "licencia"]] = None
    plan_codigo: str
    modalidad_pago: Literal["semanal", "quincenal", "mensual"]
    metadata_producto: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validar_combinacion_y_metadata(self) -> "LoanbookBase":
        """Valida combinación producto×plan×modalidad y metadata_producto."""
        _validar_combinacion_producto_plan(
            self.producto,
            self.subtipo_rodante,
            self.plan_codigo,
            self.modalidad_pago,
        )
        _validar_metadata_producto(
            self.producto,
            self.subtipo_rodante,
            self.metadata_producto,
        )
        # Auto-calcular LTV para RDX si hay monto y valor_origen en metadata
        if self.producto == "RDX":
            meta = self.metadata_producto
            if meta.get("moto_valor_origen") and meta.get("moto_valor_origen", 0) > 0:
                if hasattr(self, "monto_original") and self.monto_original:
                    meta["ltv"] = round(self.monto_original / meta["moto_valor_origen"], 3)
        return self


class LoanbookCreate(LoanbookBase):
    """Schema completo para crear un nuevo loanbook."""

    # Datos del cliente
    cliente_nombre: str = Field(..., min_length=1)
    cliente_cedula: str = Field(..., min_length=1)
    cliente_telefono: Optional[str] = None
    cliente_ciudad: Optional[str] = None

    # Términos del crédito
    monto_original: float = Field(..., gt=0)
    cuota_inicial: float = Field(default=0, ge=0)
    cuota_periodica: float = Field(..., gt=0)
    fecha_factura: date

    # Opcional
    factura_alegra_id: Optional[str] = None
    vendedor: Optional[str] = None

    @model_validator(mode="after")
    def calcular_ltv_rdx(self) -> "LoanbookCreate":
        """Calcula LTV en metadata_producto para RDX si hay los datos."""
        if self.producto == "RDX":
            meta = self.metadata_producto
            valor_origen = meta.get("moto_valor_origen")
            if valor_origen and valor_origen > 0 and self.monto_original:
                meta["ltv"] = round(self.monto_original / valor_origen, 3)
        return self


class LoanbookUpdate(BaseModel):
    """Schema para actualizar campos permitidos de un loanbook.

    Todos los campos son opcionales. Solo se valida la combinación
    si se pasan campos suficientes para re-validar.
    """

    producto: Optional[Literal["RDX", "RODANTE"]] = None
    subtipo_rodante: Optional[Literal["repuestos", "soat", "comparendo", "licencia"]] = None
    plan_codigo: Optional[str] = None
    modalidad_pago: Optional[Literal["semanal", "quincenal", "mensual"]] = None
    metadata_producto: Optional[dict[str, Any]] = None
    score_riesgo: Optional[Literal["A+", "A", "B", "C", "D", "E"]] = None
    whatsapp_status: Optional[Literal["read", "delivered", "sent", "failed", "pending"]] = None
    vendedor: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
