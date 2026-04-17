import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from '@/lib/auth'
import ProtectedRoute from '@/components/ProtectedRoute'
import AppShell from '@/components/AppShell'
import LoginPage from '@/pages/LoginPage'
import ChatPage from '@/pages/ChatPage'
import BacklogPage from '@/pages/BacklogPage'
import DashboardPage from '@/pages/DashboardPage'
import InventarioPage from '@/pages/InventarioPage'
import LoanbookPage from '@/pages/LoanbookPage'
import LoanDetailPage from '@/pages/LoanDetailPage'
import CrmPage from '@/pages/CrmPage'
import ClientDetailPage from '@/pages/ClientDetailPage'
import PlanSeparePage from '@/pages/PlanSeparePage'
import HomePage from '@/pages/HomePage'

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<HomePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/backlog" element={<BacklogPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/inventario" element={<InventarioPage />} />
            <Route path="/loanbook" element={<LoanbookPage />} />
            <Route path="/loanbook/:id" element={<LoanDetailPage />} />
            <Route path="/crm" element={<CrmPage />} />
            <Route path="/clientes/:cedula" element={<ClientDetailPage />} />
            <Route path="/plan-separe" element={<PlanSeparePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
