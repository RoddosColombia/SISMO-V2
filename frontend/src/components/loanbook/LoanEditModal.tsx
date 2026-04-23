import { useEffect, useState } from "react";

interface LoanEditModalProps {
  loanbook: any;
  isOpen: boolean;
  onClose: () => void;
  onSaved: (updated: any) => void;
}

const SECCIONES = [
  {
    titulo: "Cliente",
    campos: [
      { key: "cliente.nombre", label: "Nombre" },
      { key: "cliente.cedula", label: "Cédula" },
      { key: "cliente.telefono", label: "Teléfono" },
      { key: "cliente.ciudad", label: "Ciudad" },
    ],
  },
  {
    titulo: "Moto / Colateral",
    soloRDX: true,
    campos: [
      { key: "moto_vin", label: "VIN" },
      { key: "moto_modelo", label: "Modelo" },
      { key: "moto_motor", label: "Motor" },
      { key: "moto_placa", label: "Placa" },
      { key: "moto_anio", label: "Año" },
      { key: "moto_cilindraje", label: "Cilindraje" },
      { key: "moto_valor_origen", label: "Valor de origen" },
    ],
  },
  {
    titulo: "Plan y Montos",
    campos: [
      { key: "plan_codigo", label: "Código de plan" },
      { key: "tasa_ea", label: "Tasa EA" },
      { key: "monto_original", label: "Monto original" },
      { key: "cuota_inicial", label: "Cuota inicial" },
      { key: "cuota_periodica", label: "Cuota periódica" },
      { key: "total_cuotas", label: "Total cuotas" },
      { key: "vendedor", label: "Vendedor" },
    ],
  },
  {
    titulo: "Seguimiento",
    campos: [
      { key: "factura_alegra_id", label: "ID factura Alegra" },
      { key: "score_riesgo", label: "Score de riesgo" },
    ],
  },
];

function initForm(lb: any): Record<string, any> {
  if (!lb) return {};
  const mp = lb.metadata_producto || {};
  const moto = lb.moto || {};
  const cliente = lb.cliente || {};
  return {
    "cliente.nombre": cliente.nombre || lb.cliente_nombre || "",
    "cliente.cedula": cliente.cedula || lb.cliente_cedula || "",
    "cliente.telefono": cliente.telefono || lb.cliente_telefono || "",
    "cliente.ciudad": cliente.ciudad || lb.cliente_ciudad || "",
    moto_vin: mp.moto_vin || moto.vin || lb.vin || "",
    moto_modelo: mp.moto_modelo || moto.modelo || lb.modelo || "",
    moto_motor: mp.moto_motor || moto.motor || lb.motor || "",
    moto_placa: mp.moto_placa || moto.placa || lb.placa || "",
    moto_anio: mp.moto_anio || moto.anio || "",
    moto_cilindraje: mp.moto_cilindraje || moto.cilindraje || "",
    moto_valor_origen: mp.moto_valor_origen || moto.valor_origen || "",
    plan_codigo: lb.plan_codigo || lb.plan?.codigo || "",
    tasa_ea: lb.tasa_ea ?? lb.plan?.tasa ?? "",
    monto_original: lb.monto_original || lb.valor_total || "",
    cuota_inicial: lb.cuota_inicial || "",
    cuota_periodica: lb.cuota_periodica || lb.cuota_monto || "",
    total_cuotas: lb.total_cuotas || lb.num_cuotas || "",
    vendedor: lb.vendedor || "",
    factura_alegra_id: lb.factura_alegra_id || lb.alegra_factura_id || "",
    score_riesgo: lb.score_riesgo || "",
  };
}

export default function LoanEditModal({ loanbook, isOpen, onClose, onSaved }: LoanEditModalProps) {
  const [form, setForm] = useState<Record<string, any>>({});
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (loanbook) setForm(initForm(loanbook));
  }, [loanbook]);

  const esRDX =
    loanbook?.tipo_producto === "RDX" ||
    loanbook?.producto === "RDX" ||
    loanbook?.plan_codigo?.startsWith("RDX");

  const handleChange = (key: string, val: string) => {
    setForm((prev) => ({ ...prev, [key]: val }));
  };

  const handleGuardar = async () => {
    setGuardando(true);
    setError(null);
    try {
      const token = localStorage.getItem("token");
      const codigo = loanbook?.loanbook_id || loanbook?.loanbook_codigo;
      const res = await fetch(`/api/loanbook/${codigo}/editar`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error desconocido" }));
        throw new Error(err.detail || "Error al guardar");
      }
      const data = await res.json();
      onSaved(data.loanbook);
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGuardando(false);
    }
  };

  const inputClass = (val: any) =>
    `w-full border rounded px-2 py-1 text-sm ${
      val === "" || val === null || val === undefined
        ? "bg-yellow-50 border-yellow-300"
        : "bg-white border-gray-300"
    } focus:outline-none focus:ring-1 focus:ring-blue-400`;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
        {/* Header */}
        <div className="flex justify-between items-center mb-5">
          <div>
            <h2 className="text-lg font-bold text-gray-800">Editar crédito</h2>
            <p className="text-xs text-gray-400">
              {loanbook?.loanbook_id} — campos vacíos en amarillo
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">
            ×
          </button>
        </div>

        {/* Secciones */}
        {SECCIONES.map((seccion) => {
          if (seccion.soloRDX && !esRDX) return null;
          return (
            <div key={seccion.titulo} className="mb-5">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 border-b pb-1">
                {seccion.titulo}
              </h3>
              <div className="grid grid-cols-2 gap-3">
                {seccion.campos.map(({ key, label }) => (
                  <div key={key}>
                    <label className="block text-xs text-gray-500 mb-0.5">{label}</label>
                    <input
                      className={inputClass(form[key])}
                      value={form[key] ?? ""}
                      onChange={(e) => handleChange(key, e.target.value)}
                    />
                  </div>
                ))}
              </div>
            </div>
          );
        })}

        {/* Error */}
        {error && (
          <p className="text-red-500 text-sm mb-3 bg-red-50 p-2 rounded">{error}</p>
        )}

        {/* Acciones */}
        <div className="flex gap-3 justify-end pt-2 border-t">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 border rounded hover:bg-gray-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleGuardar}
            disabled={guardando}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {guardando ? "Guardando..." : "Guardar cambios"}
          </button>
        </div>
      </div>
    </div>
  );
}
