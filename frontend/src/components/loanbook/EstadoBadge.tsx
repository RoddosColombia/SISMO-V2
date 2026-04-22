/**
 * EstadoBadge — Badge visual para los 9 estados oficiales del loanbook.
 *
 * Colores según .planning/LOANBOOK_MAESTRO_v1.1.md tabla 2.1.
 * Muestra DPD y sub-bucket opcionales para contexto adicional.
 *
 * Uso:
 *   <EstadoBadge estado="Late Delinquency" dpd={20} subBucket="Critical" />
 *   <EstadoBadge estado="Current" compact />
 */

import React from "react";

// ─────────────────────── Tipos ────────────────────────────────────────────────

export type EstadoLoanbook =
  | "Aprobado"
  | "Current"
  | "Early Delinquency"
  | "Mid Delinquency"
  | "Late Delinquency"
  | "Default"
  | "Charge-Off"
  | "Modificado"
  | "Pagado";

interface EstadoConfig {
  bg: string;
  label: string;
}

// ─────────────────────── Paleta de colores oficiales ─────────────────────────

const ESTADO_STYLES: Record<EstadoLoanbook, EstadoConfig> = {
  Aprobado:            { bg: "bg-blue-100 text-blue-700",     label: "Sin Entregar" },
  Current:             { bg: "bg-green-100 text-green-700",   label: "Al Día" },
  "Early Delinquency": { bg: "bg-yellow-100 text-yellow-800", label: "Atraso Leve" },
  "Mid Delinquency":   { bg: "bg-orange-100 text-orange-700", label: "Atraso Moderado" },
  "Late Delinquency":  { bg: "bg-red-100 text-red-700",       label: "Atraso Grave" },
  Default:             { bg: "bg-red-800 text-white",         label: "Default" },
  "Charge-Off":        { bg: "bg-black text-white",           label: "Castigado" },
  Modificado:          { bg: "bg-purple-100 text-purple-700", label: "Reestructurado" },
  Pagado:              { bg: "bg-gray-200 text-gray-600",     label: "Pagado" },
};

// ─────────────────────── Props ────────────────────────────────────────────────

interface EstadoBadgeProps {
  /** Uno de los 9 estados oficiales del loanbook. */
  estado: EstadoLoanbook | string;
  /** Sub-bucket semanal (Grace, Warning, Alert, Critical, Severe, Pre-default, Default). */
  subBucket?: string | null;
  /** Días de atraso (DPD). Mostrado solo si > 0 y no compact. */
  dpd?: number | null;
  /** Oculta DPD y sub-bucket — solo muestra el label del estado. */
  compact?: boolean;
  /** Clase CSS adicional para el contenedor. */
  className?: string;
}

// ─────────────────────── Componente ──────────────────────────────────────────

export default function EstadoBadge({
  estado,
  subBucket,
  dpd,
  compact = false,
  className = "",
}: EstadoBadgeProps) {
  const config =
    ESTADO_STYLES[estado as EstadoLoanbook] ?? ESTADO_STYLES["Aprobado"];

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${config.bg} ${className}`}
      title={estado}
    >
      <span>{config.label}</span>

      {!compact && dpd != null && dpd > 0 && (
        <span className="opacity-60 font-normal">{dpd}d</span>
      )}

      {!compact && subBucket && (
        <span className="opacity-60 font-normal">· {subBucket}</span>
      )}
    </span>
  );
}

// ─────────────────────── Export auxiliar ─────────────────────────────────────

/** Lista de todos los estados válidos para validación en formularios. */
export const ESTADOS_VALIDOS: EstadoLoanbook[] = [
  "Aprobado",
  "Current",
  "Early Delinquency",
  "Mid Delinquency",
  "Late Delinquency",
  "Default",
  "Charge-Off",
  "Modificado",
  "Pagado",
];
