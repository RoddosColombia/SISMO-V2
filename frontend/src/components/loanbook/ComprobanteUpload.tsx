import { useRef, useState } from "react";

interface ComprobanteUploadProps {
  loanbookId: string;
  numeroCuota: number;
  fechaProgramada: string; // ISO string yyyy-MM-dd
  tieneComprobante: boolean;
  onUploaded: () => void;
}

const FECHA_MINIMA = new Date("2026-04-22");

export default function ComprobanteUpload({
  loanbookId,
  numeroCuota,
  fechaProgramada,
  tieneComprobante,
  onUploaded,
}: ComprobanteUploadProps) {
  // Solo mostrar para cuotas >= 22 abril 2026
  const fechaCuota = new Date(fechaProgramada);
  if (fechaCuota < FECHA_MINIMA) return null;

  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setSubiendo(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const token = localStorage.getItem("token");
      const res = await fetch(
        `/api/loanbook/${loanbookId}/cuotas/${numeroCuota}/comprobante`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error al subir" }));
        throw new Error(err.detail || "Error al subir comprobante");
      }
      onUploaded();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubiendo(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="flex items-center gap-1">
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,application/pdf"
        className="hidden"
        onChange={handleUpload}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={subiendo}
        title={
          tieneComprobante
            ? "Comprobante cargado — click para reemplazar"
            : "Subir comprobante de pago (JPEG, PNG o PDF)"
        }
        className={`text-xs px-2 py-0.5 rounded border transition-colors disabled:opacity-50 ${
          tieneComprobante
            ? "bg-green-50 border-green-300 text-green-700 hover:bg-green-100"
            : "bg-gray-50 border-gray-300 text-gray-600 hover:bg-blue-50 hover:border-blue-300"
        }`}
      >
        {subiendo ? "Subiendo..." : tieneComprobante ? "📎 Comprobante" : "📎 Subir"}
      </button>
      {error && (
        <span
          className="text-xs text-red-500 max-w-[150px] truncate"
          title={error}
        >
          {error}
        </span>
      )}
    </div>
  );
}
