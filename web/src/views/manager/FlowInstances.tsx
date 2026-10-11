import { useEffect, useState } from 'react'
import { get, post, downloadFile, errMsg } from '../../lib/api'
import type { DeptOption, InstanceDetail, InstancePage, InstanceRow } from '../../types/api'
import { Card, Badge, Button, Input, Select } from '../../components/ui'
import FilterBar from '../../components/FilterBar'


const TONE: Record<string, 'blue' | 'green' | 'slate'> = { running: 'blue', done: 'green', cancelled: 'slate' }
const STAGE: Record<string, string> = { running: '办理中', done: '已完成', cancelled: '已取消' }

export default function FlowInstances() {
  const [rows, setRows] = useState<InstanceRow[]>([])
  const [depts, setDepts] = useState<DeptOption[]>([])
  const [filters, setFilters] = useState({ status: '', dept_no: '', start: '', end: '' })
  const [detail, setDetail] = useState<InstanceDetail | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const filterParams = () => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v) })
    return params
  }
  const load = async () => {
    const d = await get<InstancePage>(`/flow-admin/instances?${filterParams()}`)
    setRows(d.rows)
  }
  useEffect(() => { get<DeptOption[]>('/audit/depts').then(setDepts).catch(() => {}) }, [])
  useEffect(() => { load() }, [filters])
  const cancel = async (id: number) => {
    setMsg('')
    try { await post(`/flow-admin/instances/${id}/cancel`); await load(); setMsg(`实例 #${id} 已强制取消，该会话问答门控已解除`) }
    catch (e) { setMsg(errMsg(e, '取消失败')) }
  }
  const openDetail = async (id: number) => setDetail(await get<InstanceDetail>(`/flow-admin/instances/${id}`))
  const exportRows = async () => {
    setBusy(true)
    try {
      await downloadFile(`/flow-admin/export/instances?${filterParams()}`,
        `流程办理数据_${new Date().toISOString().slice(0, 10)}.xlsx`)
    } catch (e) { alert(errMsg(e, '导出失败')) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">流程实例</h1>
          <p className="mt-0.5 text-xs text-slate-400">
            办理实例运行状态与数据导出（含强制取消——取消后该会话问答门控解除；地市账号仅见本地市数据）
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={exportRows}>导出数据</Button>
        </div>
      </div>

      <FilterBar
        onQuery={load}
        items={[
          {
            label: '时间范围', value: filters.start || filters.end,
            node: (
              <div className="flex items-center gap-1.5">
                <Input type="date" className="w-full min-w-0" value={filters.start}
                  onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
                <span className="shrink-0 text-xs text-slate-300">至</span>
                <Input type="date" className="w-full min-w-0" value={filters.end}
                  onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
              </div>
            ),
          },
          {
            label: '机构', value: filters.dept_no,
            node: (
              <Select value={filters.dept_no}
                onChange={(e) => setFilters({ ...filters, dept_no: e.target.value })}>
                <option value="">全部机构</option>
                {depts.map((d) => <option key={d.dept_no} value={d.dept_no}>{d.dept_name}</option>)}
              </Select>
            ),
          },
          {
            label: '状态', value: filters.status,
            node: (
              <Select value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
                <option value="">全部状态</option>
                <option value="running">办理中</option>
                <option value="done">已完成</option>
                <option value="cancelled">已取消</option>
              </Select>
            ),
          },
        ]}
      />
      {msg && <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">{msg}</p>}
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>{['实例', '流程', '办理人', '机构', '状态', '当前/最后节点', '步数', '受理单号', '发起时间', '操作'].map(h => <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-3 py-2 text-slate-500">#{r.id}</td>
                <td className="px-3 py-2 text-slate-700">{r.flow_name || r.flow_key}</td>
                <td className="px-3 py-2">{r.user}</td>
                <td className="px-3 py-2 font-mono text-slate-400" title={r.dept_name}>{r.dept_no}</td>
                <td className="px-3 py-2"><Badge tone={TONE[r.status] || 'slate'}>{r.status_label || STAGE[r.status] || r.status}</Badge></td>
                <td className="px-3 py-2 font-mono text-[11px] text-slate-500">{r.current || '—'}</td>
                <td className="px-3 py-2">{r.steps}</td>
                <td className="px-3 py-2 font-mono text-[11px] text-emerald-600">{r.receipt_no || '—'}</td>
                <td className="px-3 py-2 text-slate-400">{r.created_at}</td>
                <td className="space-x-2 px-3 py-2">
                  <button className="text-brand hover:underline" onClick={() => openDetail(r.id)}>详情</button>
                  {r.status === 'running' && <button className="text-red-400 hover:underline" onClick={() => cancel(r.id)}>强制取消</button>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={10} className="px-3 py-6 text-center text-slate-400">暂无实例</td></tr>}
          </tbody>
        </table>
      </Card>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setDetail(null)}>
          <div onClick={e => e.stopPropagation()}>
          <Card className="max-h-[82vh] w-[720px] overflow-y-auto p-5">
            <div className="mb-3 flex items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-700">实例 #{detail.id} 办理轨迹</h3>
              <Badge tone={TONE[detail.status] || 'slate'}>{STAGE[detail.status] || detail.status}</Badge>
              <button className="ml-auto text-xs text-slate-400 hover:text-red-400" onClick={() => setDetail(null)}>关闭</button>
            </div>
            <div className="space-y-2">
              {detail.steps.map((s, i) => (
                <div key={i} className="rounded-lg border border-slate-100 px-3 py-2">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <span className="font-mono">{s.node_key}</span>
                    <Badge tone={s.node_type === 'auto' ? 'slate' : 'blue'}>{s.node_type}</Badge>
                    {s.actor && <span>操作：{s.actor}</span>}
                    {s.at && <span className="ml-auto text-slate-400">{s.at}</span>}
                  </div>
                  {s.result && <pre className="mt-1 whitespace-pre-wrap font-mono text-[10px] leading-4 text-slate-600">{s.result}</pre>}
                  {s.errors && <p className="mt-1 text-[10px] text-red-500">⚠️ {Object.values(s.errors).join('；')}</p>}
                </div>
              ))}
            </div>
            {detail.display?.sections?.some(sec => sec.type === 'result') && (
              <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs whitespace-pre-wrap text-emerald-700">
                {detail.display.sections.find(sec => sec.type === 'result')?.text}
              </div>
            )}
          </Card>
          </div>
        </div>
      )}
    </div>
  )
}
