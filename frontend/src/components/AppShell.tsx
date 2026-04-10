import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '@/lib/auth'

const NAV_ITEMS = [
  { to: '/chat', label: 'Chat' },
  { to: '/backlog', label: 'Conciliacion' },
  { to: '/dashboard', label: 'Dashboard' },
]

export default function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="flex h-screen bg-neutral-50">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-neutral-200 flex flex-col">
        <div className="px-4 py-4 border-b border-neutral-200">
          <div className="font-semibold text-neutral-900 text-sm">SISMO V2</div>
          <div className="text-xs text-neutral-500 mt-0.5">{user?.name}</div>
        </div>

        <nav className="flex-1 py-2">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm ${
                  isActive
                    ? 'bg-neutral-100 text-neutral-900 font-medium'
                    : 'text-neutral-600 hover:bg-neutral-50'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-neutral-200 p-4">
          <button
            onClick={logout}
            className="text-xs text-neutral-500 hover:text-neutral-700"
          >
            Cerrar sesion
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
