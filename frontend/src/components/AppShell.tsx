import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth'

// ═══════════════════════════════════════════
// Sidebar persistence key
// ═══════════════════════════════════════════

const SIDEBAR_STATE_KEY = 'sismo:sidebar:open'

function readInitialSidebarState(): boolean {
  try {
    const raw = localStorage.getItem(SIDEBAR_STATE_KEY)
    if (raw === null) return true
    return raw === '1'
  } catch {
    return true
  }
}

// ═══════════════════════════════════════════
// LEGACY_NAV — preserved for reversibility
// ═══════════════════════════════════════════
// const LEGACY_NAV = [
//   { to: '/chat', label: 'Chat' }, { to: '/backlog', label: 'Conciliacion' },
//   { to: '/loanbook', label: 'Creditos' }, { to: '/inventario', label: 'Inventario' },
//   { to: '/crm', label: 'Clientes' }, { to: '/dashboard', label: 'Dashboard' },
// ]

// ═══════════════════════════════════════════
// NAV_AREAS — grouped by business area
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
    iconPath:
      'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
    items: [
      { to: '/chat', label: 'Agente Contador' },
      { to: '/conciliacion', label: 'Subir extracto' },
      { to: '/backlog', label: 'Backlog movimientos' },
      { to: '/cierres', label: 'Cierres Contables' },
      { to: '/inventario', label: 'Inventario' },
    ],
  },
  {
    id: 'finanzas',
    label: 'Finanzas',
    iconPath:
      'M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941',
    items: [
      { to: '/dashboard', label: 'Dashboard' },
      { to: '/cierre-q1', label: 'Cierre Q1 2026' },
    ],
  },
  {
    id: 'originacion',
    label: 'Originación',
    iconPath:
      'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99',
    items: [{ to: '/loanbook', label: 'Créditos' }],
  },
  {
    id: 'cartera',
    label: 'Cartera',
    iconPath:
      'M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0V12a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 12V5.25',
    items: [
      { to: '/cartera-legacy', label: 'Cartera Legacy' },
      { to: '#', label: 'RADAR (Phase 8)', disabled: true },
    ],
  },
  {
    id: 'comercial',
    label: 'Comercial',
    iconPath:
      'M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z',
    items: [
      { to: '/crm', label: 'CRM / Clientes' },
      { to: '/plan-separe', label: 'Plan Separe' },
    ],
  },
  {
    id: 'rrhh',
    label: 'RRHH',
    iconPath:
      'M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z',
    items: [{ to: '#', label: 'En construcción', disabled: true }],
  },
]

const INITIAL_EXPANDED = new Set(['contabilidad', 'cartera'])

// ═══════════════════════════════════════════
// Component
// ═══════════════════════════════════════════

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [sidebarOpen, setSidebarOpen] = useState<boolean>(readInitialSidebarState)
  const [expanded, setExpanded] = useState<Set<string>>(INITIAL_EXPANDED)

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_STATE_KEY, sidebarOpen ? '1' : '0')
    } catch { /* ignore */ }
  }, [sidebarOpen])

  const toggleArea = (id: string) => {
    if (!sidebarOpen) {
      // Expanding an area while collapsed — open the sidebar first
      setSidebarOpen(true)
      setExpanded(prev => new Set(prev).add(id))
      return
    }
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
      <aside
        className={`bg-surface-container-low flex flex-col transition-[width] duration-200 ease-out ${
          sidebarOpen ? 'w-60' : 'w-[68px]'
        }`}
      >
        {/* Logo — clickable → navigates to / */}
        <button
          onClick={() => navigate('/')}
          aria-label="Ir a inicio"
          className={`flex items-center gap-3 px-4 py-5 hover:bg-surface-container-lowest/60 transition-colors text-left ${
            sidebarOpen ? '' : 'justify-center px-3'
          }`}
        >
          <img src="/logo-roddos.jpeg" alt="RODDOS" className="h-7 shrink-0 rounded-sm" />
          {sidebarOpen && (
            <span className="font-display font-bold text-on-surface text-sm tracking-tight">
              SISMO
            </span>
          )}
        </button>

        {/* Toggle button */}
        <button
          onClick={() => setSidebarOpen(o => !o)}
          aria-label={sidebarOpen ? 'Contraer navegación' : 'Expandir navegación'}
          className={`mx-2 mb-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-on-surface-variant hover:bg-surface-container-lowest/60 transition-colors ${
            sidebarOpen ? 'justify-start' : 'justify-center'
          }`}
        >
          <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            {sidebarOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            )}
          </svg>
          {sidebarOpen && <span>Contraer</span>}
        </button>

        <nav className="flex-1 px-2 py-1 space-y-0.5 overflow-y-auto overflow-x-hidden">
          {NAV_AREAS.map(area => {
            const isOpen = sidebarOpen && expanded.has(area.id)
            return (
              <div key={area.id}>
                <button
                  onClick={() => toggleArea(area.id)}
                  title={!sidebarOpen ? area.label : undefined}
                  className={`w-full flex items-center gap-3 rounded-md text-xs font-semibold uppercase tracking-wider text-on-surface-variant hover:bg-surface-container-lowest/60 transition-colors ${
                    sidebarOpen ? 'px-3 py-2' : 'justify-center px-2 py-2'
                  }`}
                >
                  <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d={area.iconPath} />
                  </svg>
                  {sidebarOpen && (
                    <>
                      <span className="flex-1 text-left">{area.label}</span>
                      <svg
                        className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                        fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                    </>
                  )}
                </button>

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

        {/* User footer */}
        <div className={`${sidebarOpen ? 'px-5 py-4' : 'px-2 py-3'}`}>
          {sidebarOpen ? (
            <>
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
            </>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <div
                title={user?.name || ''}
                className="w-8 h-8 rounded-md bg-primary/10 flex items-center justify-center text-primary text-xs font-bold"
              >
                {user?.name?.charAt(0) || '?'}
              </div>
              <button
                onClick={logout}
                aria-label="Cerrar sesión"
                className="w-8 h-8 flex items-center justify-center rounded-md text-on-surface-variant hover:text-error hover:bg-surface-container-lowest/60 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                </svg>
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-hidden flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}
