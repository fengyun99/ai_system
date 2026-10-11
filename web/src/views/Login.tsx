import { useState } from 'react'
import { useDispatch } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { setToken, fetchInfo } from '../store/authSlice'
import { sm3Hex } from '../lib/sm3'
import { post, ApiError } from '../lib/api'
import { store } from '../store'
import { Button, Input, Card } from '../components/ui'

export default function Login() {
  const dispatch = useDispatch<typeof store.dispatch>()
  const nav = useNavigate()
  const [username, setUsername] = useState('fzzx')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError('')
    setLoading(true)
    try {
      // 登录协议：明文不出浏览器，传输 sm3(明文) 摘要（与原 Java 前端一致）
      const data = await post<{ token: string }>('/login', {
        username,
        password: sm3Hex(password),
      })
      dispatch(setToken(data.token))
      await dispatch(fetchInfo())
      nav('/portal')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请检查网络')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-gradient-to-br from-slate-100 via-indigo-50 to-slate-200">
      <div className="w-[380px]">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand text-2xl shadow-lg shadow-brand/30">
            🏛️
          </div>
          <h1 className="text-xl font-semibold text-slate-800">AI 智能客服系统</h1>
          <p className="mt-1 text-xs text-slate-400">
            Python · LangGraph · MCP · 混合检索 RAG
          </p>
        </div>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-500">账号</label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="请输入账号" autoComplete="username" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-500">密码</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码（传输前已做 SM3 国密摘要）"
                autoComplete="current-password"
              />
            </div>
            {error && <p className="text-xs text-red-500">{error}</p>}
            <Button className="w-full" disabled={loading || !username || !password}>
              {loading ? '登录中…' : '登 录'}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}
