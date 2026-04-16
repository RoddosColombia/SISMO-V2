import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '@/lib/auth'

// ═══════════════════════════════════════════
// LEGACY_NAV — preserved for reversibility (pre-Phase 8)
// ═══════════════════════════════════════════
// const LEGACY_NAV = [
//   { to: '/chat', label: 'Chat' },
//   { to: '/backlog', label: 'Conciliacion' },
//   { to: '/loanbook', label: 'Creditos' },
//   { to: '/inventario', label: 'Inventario' },
//   { to: '/crm', label: 'Clientes' },
//   { to: '/dashboard', label: 'Dashboard' },
// ]

// ═══════════════════════════════════════════
// NAV_AREAS — grouped by business area (Phase 8 prep)
// ═══════════════════════════════════════════

interface NavItem {
  to: string
  label: string
  disabled?: boolean
}

interface NavArea {
  id: string
  label: string
  iconPath: string
  items: NavItem[]
}

const NAV_AREAS: NavArea[] = [
  {
    id: 'contabilidad',
    label: 'Contabilidad',
    // calculator
    iconPath: 'M15.75 15.75l-2.489-2.489m0 0a3.375 3.375 0 10-4.773-4.773 3.375 3.375 0 004.774 4.774zM21 12a9 9 0 11-18 0 9 9 0 0118 0z',
    items: [
      { to: '/chat', label: 'Agente Contador' },
      { to: '/backlog', label: 'Conciliación' },
      { to: '/inventario', label: 'Inventario' },
    ],
  },
  {
    id: 'finanzas',
    label: 'Finanzas',
    // chart
    iconPath: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
    items: [
      { to: '/dashboard', label: 'Dashboard' },
      { to: '#', label: 'En construcción', disabled: true },
    ],
  },
  {
    id: 'originacion',
    label: 'Originación',
    // file-plus / clipboard
    iconPath: 'M9 12h6m-6 3h6m-3-9v18m9-9a9 9 0 11-18 0 9 9 0 0118 0z',
    items: [
      { to: '/loanbook', label: 'Créditos' },
    ],
  },
  {
    id: 'cartera',
    label: 'Cartera',
    // radar / shield
    iconPath: 'M12 2.25c-2.5 0-5 1-7.5 3C3.75 6 3 6.75 3 9c0 6 4.5 10.5 9 12.75 4.5-2.25 9-6.75 9-12.75 0-2.25-.75-3-1.5-3.75-2.5-2-5-3-7.5-3z',
    items: [
      { to: '#', label: 'RADAR (Phase 8)', disabled: true },
    ],
  },
  {
    id: 'comercial',
    label: 'Comercial',
    // shopping-bag
    iconPath: 'M16.5 6v.75A.75.75 0 0015.75 6H8.25a.75.75 0 00-.75.75V6m9 0V4.5A2.25 2.25 0 0014.25 2.25h-4.5A2.25 2.25 0 007.5 4.5V6m9 0H20.25A1.5 1.5 0 0121.75 7.5v11.25A1.5 1.5 0 0120.25 20.25H3.75A1.5 1.5 0 012.25 18.75V7.5A1.5 1.5 0 013.75 6H7.5',
    items: [
      { to: '/crm', label: 'CRM / Clientes' },
      { to: '#', label: 'En construcción', disabled: true },
    ],
  },
  {
    id: 'rrhh',
    label: 'RRHH',
    // user-check
    iconPath: 'M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z',
    items: [
      { to: '#', label: 'En construcción', disabled: true },
    ],
  },
]

// Only "Contabilidad" expanded on first load
const INITIAL_EXPANDED = new Set(['contabilidad'])

export default function AppShell() {
  const { user, logout } = useAuth()
  const [expanded, setExpanded] = useState<Set<string>>(INITIAL_EXPANDED)

  const toggleArea = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="flex h-screen bg-surface">
      {/* Sidebar */}
      <aside className="w-60 bg-surface-container-low flex flex-col">
        <div className="px-5 py-5 flex items-center gap-3">
          <img src="/logo-roddos.jpeg" alt="RODDOS" className="h-7" />
          <span className="font-display font-bold text-on-surface text-sm tracking-tight">SISMO</span>
        </div>

        <nav className="flex-1 px-2 py-2 space-y-0.5 overflow-y-auto">
          {NAV_AREAS.map(area => {
            const isOpen = expanded.has(area.id)
            return (
              <div key={area.id}>
                {/* Area header (collapsible) */}
                <button
                  onClick={() => toggleArea(area.id)}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-xs font-semibold uppercase tracking-wider text-on-surface-variant hover:bg-surface-container-lowest/60 transition-colors"
                >
                  <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d={area.iconPath} />
                  </svg>
                  <span className="flex-1 text-left">{area.label}</span>
                  <svg
                    className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                  </svg>
                </button>

                {/* Items */}
                {isOpen && (
                  <div className="mt-0.5 mb-1 space-y-0.5">
                    {area.items.map((item, idx) => {
                      if (item.disabled) {
                        return (
                          <div
                            key={`${area.id}-${idx}`}
                            className="flex items-center gap-2 ml-6 px-3 py-2 rounded-md text-xs text-on-surface-variant/50 cursor-not-allowed"
                            title="En construcción"
                          >
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                            </svg>
                            {item.label}
                          </div>
                        )
                      }
                      return (
                        <NavLink
                          key={item.to}
                          to={item.to}
                          className={({ isActive }) =>
                            `flex items-center gap-2 ml-6 px-3 py-2 rounded-md text-xs transition-colors ${
                              isActive
                                ? 'bg-primary/10 text-primary font-medium'
                                : 'text-on-surface-variant hover:bg-surface-container-lowest/60'
                            }`
                          }
                        >
                          {item.label}
                        </NavLink>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        <div className="px-5 py-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-md bg-primary/10 flex items-center justify-center text-primary text-xs font-bold">
              {user?.name?.charAt(0) || '?'}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium text-on-surface truncate">{user?.name}</div>
              <div className="text-xs text-on-surface-variant truncate">{user?.role}</div>
            </div>
          </div>
          <button
            onClick={logout}
            className="text-xs text-on-surface-variant hover:text-error transition-colors"
          >
            Cerrar sesión
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-hidden flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}
