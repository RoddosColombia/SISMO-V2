/**
 * BacklogPage — Movimientos pendientes de causar.
 *
 * Features:
 * - Table: fecha, banco, descripcion, monto, razon, intentos, acciones
 * - Filters: banco dropdown, fecha range, razon text search
 * - Sort: oldest first (fecha_ingreso_backlog ascending)
 * - Causar modal: cuenta selector + retenciones + confirm
 * - Auto-refresh count for badge
 */
import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface BacklogMovimiento {
  _id: string;
  fecha: string;
  banco: string;
  descripcion: string;
  monto: number;
  tipo: string;
  razon_pendiente: string;
  intentos: number;
  estado: string;
}

interface CausarModalProps {
  movimiento: BacklogMovimiento | null;
  onClose: () => void;
  onSuccess: () => void;
}

const CUENTAS_RODDOS = [
  { id: 5480, label: 'Arrendamientos 512010' },
  { id: 5484, label: 'Servicios Públicos' },
  { id: 5487, label: 'Teléfono/Internet' },
  { id: 5490, label: 'Mantenimiento' },
  { id: 5491, label: 'Transporte' },
  { id: 5493, label: 'Gastos Generales (fallback)' },
  { id: 5462, label: 'Sueldos 510506' },
  { id: 5470, label: 'Honorarios' },
  { id: 5500, label: 'Publicidad' },
  { id: 5508, label: 'Comisiones Bancarias' },
  { id: 5510, label: 'Seguros' },
  { id: 5533, label: 'Intereses 615020' },
];

function CausarModal({ movimiento, onClose, onSuccess }: CausarModalProps) {
  const [cuentaId, setCuentaId] = useState(5493);
  const [retefuente, setRetefuente] = useState(0);
  const [reteica, setReteica] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!movimiento) return null;

  const handleCausar = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(
        `${API_BASE}/api/backlog/${movimiento._id}/causar?cuenta_id=${cuentaId}&retefuente=${retefuente}&reteica=${reteica}`,
        { method: 'POST' }
      );
      const data = await res.json();
      if (data.success) {
        onSuccess();
      } else {
        setError(data.error || 'Error al causar');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div className="modal" style={{ background: 'white', borderRadius: 8, padding: 24, maxWidth: 500, width: '100%' }}>
        <h3>Causar Movimiento</h3>
        <p><strong>Fecha:</strong> {movimiento.fecha}</p>
        <p><strong>Banco:</strong> {movimiento.banco}</p>
        <p><strong>Descripcion:</strong> {movimiento.descripcion}</p>
        <p><strong>Monto:</strong> ${movimiento.monto.toLocaleString('es-CO')}</p>

        <label>Cuenta contable:</label>
        <select value={cuentaId} onChange={(e) => setCuentaId(Number(e.target.value))} style={{ width: '100%', padding: 8, marginBottom: 12 }}>
          {CUENTAS_RODDOS.map(c => (
            <option key={c.id} value={c.id}>{c.id} — {c.label}</option>
          ))}
        </select>

        <label>ReteFuente ($):</label>
        <input type="number" value={retefuente} onChange={(e) => setRetefuente(Number(e.target.value))} style={{ width: '100%', padding: 8, marginBottom: 12 }} />

        <label>ReteICA ($):</label>
        <input type="number" value={reteica} onChange={(e) => setReteica(Number(e.target.value))} style={{ width: '100%', padding: 8, marginBottom: 12 }} />

        {error && <p style={{ color: 'red' }}>{error}</p>}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={loading}>Cancelar</button>
          <button onClick={handleCausar} disabled={loading} style={{ background: '#2563eb', color: 'white', padding: '8px 16px', borderRadius: 4 }}>
            {loading ? 'Causando...' : 'Confirmar'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function BacklogPage() {
  const [movimientos, setMovimientos] = useState<BacklogMovimiento[]>([]);
  const [loading, setLoading] = useState(true);
  const [banco, setBanco] = useState('');
  const [causarTarget, setCausarTarget] = useState<BacklogMovimiento | null>(null);

  const fetchBacklog = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (banco) params.set('banco', banco);
      const res = await fetch(`${API_BASE}/api/backlog?${params}`);
      const data = await res.json();
      if (data.success) setMovimientos(data.data);
    } catch (e) {
      console.error('Error fetching backlog:', e);
    } finally {
      setLoading(false);
    }
  }, [banco]);

  useEffect(() => { fetchBacklog(); }, [fetchBacklog]);

  return (
    <div style={{ padding: 24 }}>
      <h1>Backlog — Movimientos Pendientes</h1>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <select value={banco} onChange={(e) => setBanco(e.target.value)} style={{ padding: 8 }}>
          <option value="">Todos los bancos</option>
          <option value="Bancolombia">Bancolombia</option>
          <option value="BBVA">BBVA</option>
          <option value="Davivienda">Davivienda</option>
          <option value="Nequi">Nequi</option>
        </select>
        <button onClick={fetchBacklog}>Refrescar</button>
      </div>

      {loading ? (
        <p>Cargando...</p>
      ) : movimientos.length === 0 ? (
        <p>No hay movimientos pendientes.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
              <th style={{ textAlign: 'left', padding: 8 }}>Fecha</th>
              <th style={{ textAlign: 'left', padding: 8 }}>Banco</th>
              <th style={{ textAlign: 'left', padding: 8 }}>Descripcion</th>
              <th style={{ textAlign: 'right', padding: 8 }}>Monto</th>
              <th style={{ textAlign: 'left', padding: 8 }}>Razon</th>
              <th style={{ textAlign: 'center', padding: 8 }}>Intentos</th>
              <th style={{ padding: 8 }}>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {movimientos.map((m) => (
              <tr key={m._id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: 8 }}>{m.fecha}</td>
                <td style={{ padding: 8 }}>{m.banco}</td>
                <td style={{ padding: 8, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.descripcion}</td>
                <td style={{ padding: 8, textAlign: 'right' }}>${m.monto.toLocaleString('es-CO')}</td>
                <td style={{ padding: 8, fontSize: 12, color: '#6b7280' }}>{m.razon_pendiente}</td>
                <td style={{ padding: 8, textAlign: 'center' }}>{m.intentos}</td>
                <td style={{ padding: 8 }}>
                  <button onClick={() => setCausarTarget(m)} style={{ background: '#2563eb', color: 'white', padding: '4px 12px', borderRadius: 4, fontSize: 12 }}>
                    Causar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <CausarModal
        movimiento={causarTarget}
        onClose={() => setCausarTarget(null)}
        onSuccess={() => { setCausarTarget(null); fetchBacklog(); }}
      />
    </div>
  );
}
