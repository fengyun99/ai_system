import { Outlet } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { store, type RootState } from '../../store'
import { logout } from '../../store/authSlice'
import { cn } from '../../components/ui'

const NAV = [
  { title: '运营审计', items: [
    { path: '/manager/dashboard', icon: '📊', label: '仪表盘' },
    { path: '/manager/turns', icon: '📋', label: '轮次审计' },
    { path: '/manager/rag-audit', icon: '🧪', label: 'RAG 审计' },
  ]},
  { title: '知识库', items: [
    { path: '/manager/knowledge', icon: '📚', label: '知识条目' },
  ]},
  { title: '系统管理', items: [
    { path: '/manager/users', icon: '👥', label: '用户管理' },
    { path: '/manager/roles', icon: '🛡️', label: '角色管理' },
    { path: '/manager/depts', icon: '🏢', label: '部门管理' },
    { path: '/manager/menus', icon: '📜', label: '菜单管理' },
  ]},
  { title: '业务配置', items: [
    { path: '/manager/flows', icon: '🧩', label: '流程定义' },
    { path: '/manager/flow-instances', icon: '📄', label: '流程实例' },
  ]},
  { title: '工具', items: [
    { path: '/manager/tools', icon: '🔧', label: 'MCP 工具' },
  ]},
]

export default function ManagerLayout() {
  const dispatch = useDispatch<typeof store.dispatch>()
  const auth = useSelector((s: RootState) => s.auth)
  const path = window.location.pathname

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-white">⚙️</div>
          <div>
            <p className="text-sm font-semibold text-slate-800">管理后台</p>
            <p className="text-[10px] text-slate-400">AI 智能客服系统</p>
          </div>
        </div>
        <nav className="flex-1 space-y-4 overflow-auto px-3 py-2">
          {NAV.map((group) => (
            <div key={group.title}>
              <p className="px-2.5 pb-1.5 text-[10px] font-semibold tracking-wider text-slate-300">
                {group.title}
              </p>
              {group.items.map((item) => (
                <a
                  key={item.path}
                  href={item.path}
                  className={cn(
                    'mb-0.5 flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors',
                    path === item.path
                      ? 'bg-brand/10 font-medium text-brand-dark'
                      : 'text-slate-600 hover:bg-slate-100',
                  )}
                >
                  <span>{item.icon}</span> {item.label}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-3">
          <a href="/portal" className="mb-1 block rounded-lg px-2.5 py-2 text-xs text-slate-500 hover:bg-slate-100">
            💬 返回问答门户
          </a>
          <div className="flex items-center gap-2 px-2.5 py-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-brand/10 text-xs text-brand-dark">
              {auth.user?.nick_name?.[0] || '?'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-700">{auth.user?.nick_name}</p>
              <p className="truncate text-[10px] text-slate-400">{auth.roleNames.join(' · ')}</p>
            </div>
            <button className="text-xs text-slate-400 hover:text-red-400" onClick={() => dispatch(logout())}>
              退出
            </button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
