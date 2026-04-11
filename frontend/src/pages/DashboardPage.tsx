export default function DashboardPage() {
  const cards = [
    { label: 'Journals hoy', value: '—', sub: 'Conectar Alegra' },
    { label: 'Backlog pendiente', value: '—', sub: 'Movimientos sin causar' },
    { label: 'Cartera activa', value: '—', sub: 'Loanbooks activos' },
    { label: 'Ultimo sync', value: '—', sub: 'Alegra API' },
  ]

  return (
    <div className="flex flex-col h-full bg-surface">
      <div className="px-6 pt-6 pb-4">
        <h1 className="font-display text-lg font-bold text-on-surface">Dashboard</h1>
        <p className="text-sm text-on-surface-variant mt-1">Resumen operativo</p>
      </div>

      <div className="px-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card) => (
          <div key={card.label} className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-5 py-4">
            <div className="text-xs text-on-surface-variant uppercase tracking-wider">{card.label}</div>
            <div className="font-display text-3xl font-bold text-on-surface mt-1">{card.value}</div>
            <div className="text-xs text-on-surface-variant mt-1">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="px-6 mt-6 flex-1">
        <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg p-6 h-full max-h-64 flex items-center justify-center">
          <p className="text-on-surface-variant text-sm">Graficos y metricas en tiempo real — por implementar</p>
        </div>
      </div>
    </div>
  )
}
