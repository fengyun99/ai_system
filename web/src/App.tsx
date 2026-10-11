import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { store, type RootState } from './store'
import { fetchInfo } from './store/authSlice'
import Login from './views/Login'
import Chat from './views/portal/Chat'
import ManagerLayout from './views/manager/Layout'
import Dashboard from './views/manager/Dashboard'
import Turns from './views/manager/Turns'
import Knowledge from './views/manager/Knowledge'
import Users from './views/manager/Users'
import Roles from './views/manager/Roles'
import Depts from './views/manager/Depts'
import Menus from './views/manager/Menus'
import Tools from './views/manager/Tools'
import FlowDefs from './views/manager/FlowDefs'
import FlowInstances from './views/manager/FlowInstances'
import RagAudit from './views/manager/RagAudit'

function Guard({ children, manager = false }: { children: React.ReactNode; manager?: boolean }) {
  const { token, roles, user } = useSelector((s: RootState) => s.auth)
  if (!token) return <Navigate to="/login" replace />
  // 整页刷新后 getInfo 尚未返回：先等待，避免用空角色误判越权而重定向
  if (!user) {
    return <div className="flex h-full items-center justify-center text-sm text-slate-400">加载中…</div>
  }
  if (manager && !roles.includes('admin') && !roles.includes('manager')) {
    return <Navigate to="/portal" replace />
  }
  return <>{children}</>
}

export default function App() {
  const dispatch = useDispatch<typeof store.dispatch>()
  const token = useSelector((s: RootState) => s.auth.token)

  useEffect(() => {
    if (token) dispatch(fetchInfo())
  }, [token])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/portal"
          element={
            <Guard>
              <Chat />
            </Guard>
          }
        />
        <Route
          path="/manager"
          element={
            <Guard manager>
              <ManagerLayout />
            </Guard>
          }
        >
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="turns" element={<Turns />} />
          <Route path="rag-audit" element={<RagAudit />} />
          <Route path="knowledge" element={<Knowledge />} />
          <Route path="users" element={<Users />} />
          <Route path="roles" element={<Roles />} />
          <Route path="depts" element={<Depts />} />
          <Route path="menus" element={<Menus />} />
          <Route path="flows" element={<FlowDefs />} />
          <Route path="flow-instances" element={<FlowInstances />} />
          <Route path="tools" element={<Tools />} />
        </Route>
        <Route path="*" element={<Navigate to="/portal" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
