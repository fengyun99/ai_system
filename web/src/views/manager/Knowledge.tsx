import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { IngestLogRow, KnowledgeForm, KnowledgePage, KnowledgeRow, ReconcileData, SyncAllData } from '../../types/api'
import { Card, Table, Badge, Button, Input, Select, Modal, Textarea, Empty } from '../../components/ui'
import type { BadgeTone } from '../../components/ui'

const BIZ_LABEL: Record<string, string> = { qa: '问答', doc: '文档', common: '常识' }
const THEME_LABEL: Record<string, string> = {
  deposit: '缴存', loan: '贷款', withdraw: '提取', other: '其他',
}
const SYNC_TONE: Record<number, BadgeTone> = { 0: 'amber', 1: 'green', 2: 'red' }
const SYNC_LABEL: Record<number, string> = { 0: '未同步', 1: '已同步', 2: '同步失败' }

const EMPTY_FORM = {
  dept_no: '', biz_type: 'qa', title: '', question: '', answer: '',
  content: '', theme: 'other', is_public: 0,
}

export default function Knowledge() {
  const [rows, setRows] = useState<KnowledgeRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({ biz_type: '', keyword: '' })
  const [editing, setEditing] = useState<KnowledgeForm | null>(null)
  const [logs, setLogs] = useState<{ title: string; list: IngestLogRow[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const pageSize = 12

  const load = async () => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (filters.biz_type) params.set('biz_type', filters.biz_type)
    if (filters.keyword) params.set('keyword', filters.keyword)
    const data = await get<KnowledgePage>(`/knowledge/list?${params}`)
    setRows(data.rows)
    setTotal(data.total)
  }

  useEffect(() => {
    load()
  }, [page])

  const save = async () => {
    if (!editing) return
    setBusy(true)
    try {
      if (editing.id) await put(`/knowledge/${editing.id}`, editing)
      else await post('/knowledge', editing)
      setEditing(null)
      load()
    } catch (e) {
      alert(errMsg(e))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (row: KnowledgeRow) => {
    if (!confirm(`确认删除「${row.title}」？索引将同步清除`)) return
    await del(`/knowledge/${row.id}`)
    load()
  }

  const syncAll = async () => {
    setBusy(true)
    try {
      const r = await post<SyncAllData>('/knowledge/sync_all')
      alert(`批量同步完成：成功 ${r.ok} · 失败 ${r.fail}`)
      load()
    } finally {
      setBusy(false)
    }
  }

  const reconcile = async () => {
    if (!confirm('执行全量对账（库有索引无补推 / 库无索引有删除）？')) return
    setBusy(true)
    try {
      const r = await post<ReconcileData>('/knowledge/reconcile')
      alert(`对账完成：补推 ${r.pushed} · 清除 ${r.dropped}`)
      load()
    } finally {
      setBusy(false)
    }
  }

  const syncOne = async (id: number) => {
    try {
      await post(`/knowledge/sync/${id}`)
      load()
    } catch (e) {
      alert(errMsg(e))
      load()
    }
  }

  const showLogs = async (r: KnowledgeRow) => {
    const list = await get<IngestLogRow[]>(`/knowledge/ingest-logs/${r.id}`)
    setLogs({ title: r.title, list })
  }

  const pages = Math.max(Math.ceil(total / pageSize), 1)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">知识库管理</h1>
          <p className="mt-0.5 text-xs text-slate-400">
            问答/文档/常识统一管理 · 保存即切块向量化写入 ES（未同步行显形，可重试/对账）
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select className="w-24" value={filters.biz_type} onChange={(e) => setFilters({ ...filters, biz_type: e.target.value })}>
            <option value="">全部类型</option>
            <option value="qa">问答</option>
            <option value="doc">文档</option>
            <option value="common">常识</option>
          </Select>
          <Input className="w-40" placeholder="标题关键词…" value={filters.keyword}
            onChange={(e) => setFilters({ ...filters, keyword: e.target.value })}
            onKeyDown={(e) => e.key === 'Enter' && (setPage(1), load())} />
          <Button size="sm" variant="outline" onClick={() => { setPage(1); load() }}>查询</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={syncAll}>批量同步</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={reconcile}>全量对账</Button>
          <Button size="sm" onClick={() => setEditing({ ...EMPTY_FORM })}>＋ 新增</Button>
        </div>
      </div>

      <Card>
        <Table headers={['ID', '机构', '类型', '标题', '问法', '主题', '公开', '同步状态', '更新时间', '']}>
          {rows.length === 0 && <tr><td colSpan={10}><Empty /></td></tr>}
          {rows.map((r) => (
            <tr key={r.id} className="text-xs text-slate-600 hover:bg-slate-50/70">
              <td className="px-4 py-2.5 font-mono text-slate-400">{r.id}</td>
              <td className="px-4 py-2.5 font-mono">{r.dept_no}</td>
              <td className="px-4 py-2.5"><Badge tone="blue">{BIZ_LABEL[r.biz_type]}</Badge></td>
              <td className="max-w-[180px] truncate px-4 py-2.5 font-medium" title={r.title}>{r.title}</td>
              <td className="max-w-[180px] truncate px-4 py-2.5 text-slate-400">{r.question || '—'}</td>
              <td className="px-4 py-2.5">{THEME_LABEL[r.theme] || r.theme}</td>
              <td className="px-4 py-2.5">{r.is_public ? <Badge tone="green">公开</Badge> : <Badge>私有</Badge>}</td>
              <td className="px-4 py-2.5">
                <span title={r.sync_error}>
                  <Badge tone={SYNC_TONE[r.sync_status]}>{SYNC_LABEL[r.sync_status]}</Badge>
                </span>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 text-slate-400">{r.created_at}</td>
              <td className="whitespace-nowrap px-4 py-2.5">
                {r.sync_status !== 1 && (
                  <Button size="sm" variant="ghost" onClick={() => syncOne(r.id)}>同步</Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => showLogs(r)}>记录</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing({
                  dept_no: r.dept_no, biz_type: r.biz_type, title: r.title, question: r.question,
                  answer: (r as KnowledgeRow & Partial<KnowledgeForm>).answer ?? '',
                  content: (r as KnowledgeRow & Partial<KnowledgeForm>).content ?? '',
                  theme: r.theme,
                  is_public: r.is_public, id: r.id,
                })}>编辑</Button>
                <Button size="sm" variant="ghost" className="text-red-400 hover:text-red-500" onClick={() => remove(r)}>删除</Button>
              </td>
            </tr>
          ))}
        </Table>
        <Pager page={page} pages={pages} total={total} onPage={setPage} />
      </Card>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id ? `编辑知识 #${editing.id}` : '新增知识'}
      >
        {editing && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-3 gap-3">
              <Field label="归属机构号">
                <Input value={editing.dept_no} onChange={(e) => setEditing({ ...editing, dept_no: e.target.value })} placeholder="如 35002" />
              </Field>
              <Field label="类型">
                <Select value={editing.biz_type} onChange={(e) => setEditing({ ...editing, biz_type: e.target.value })}>
                  <option value="qa">问答</option>
                  <option value="doc">文档</option>
                  <option value="common">常识</option>
                </Select>
              </Field>
              <Field label="主题">
                <Select value={editing.theme} onChange={(e) => setEditing({ ...editing, theme: e.target.value })}>
                  <option value="deposit">缴存</option>
                  <option value="loan">贷款</option>
                  <option value="withdraw">提取</option>
                  <option value="other">其他</option>
                </Select>
              </Field>
            </div>
            <Field label="标题">
              <Input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
            </Field>
            {editing.biz_type === 'qa' ? (
              <>
                <Field label="标准问法">
                  <Input value={editing.question} onChange={(e) => setEditing({ ...editing, question: e.target.value })} />
                </Field>
                <Field label="标准答案">
                  <Textarea rows={6} value={editing.answer} onChange={(e) => setEditing({ ...editing, answer: e.target.value })} />
                </Field>
              </>
            ) : (
              <Field label="正文内容">
                <Textarea rows={8} value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })} />
              </Field>
            )}
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" checked={!!editing.is_public} onChange={(e) => setEditing({ ...editing, is_public: e.target.checked ? 1 : 0 })} />
              对下级机构公开（祖先链可见）
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button disabled={busy || !editing.title || !editing.dept_no} onClick={save}>
                {busy ? '保存并同步中…' : '保存（切块+向量化+写ES）'}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={logs !== null} onClose={() => setLogs(null)} title={`入库记录 · ${logs?.title ?? ''}`}>
        {logs && (
          <div className="max-h-[60vh] overflow-y-auto">
            <p className="mb-2 text-xs text-slate-400">
              每次同步（成功/失败）各一行：切块数 / token（真值或估算）/ 成本 / 耗时 / 结果——入库不是轮次，与问答成本分开记账
            </p>
            <Table headers={['时间', '状态', '切块', 'Token(入)', '成本', '耗时', '操作者', '错误']}>
              {logs.list.length === 0 && <tr><td colSpan={8}><Empty text="暂无入库记录" /></td></tr>}
              {logs.list.map((lg) => (
                <tr key={lg.id} className="text-xs text-slate-600">
                  <td className="whitespace-nowrap px-3 py-2 text-slate-400">{lg.created_at}</td>
                  <td className="px-3 py-2">
                    <Badge tone={lg.status === 'done' ? 'green' : 'red'}>{lg.status === 'done' ? '成功' : '失败'}</Badge>
                  </td>
                  <td className="px-3 py-2 font-mono">{lg.chunk_count}</td>
                  <td className="px-3 py-2 font-mono">
                    {lg.tokens_in}
                    {lg.tokens_estimated === 1 && (
                      <span title="本行含字符估算口径（供应商未返回 usage）" className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-600">估</span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-emerald-600">¥{lg.cost.toFixed(4)}</td>
                  <td className="px-3 py-2 font-mono">{lg.duration_ms}ms</td>
                  <td className="px-3 py-2 font-mono text-slate-400">{lg.operator_user_id === 0 ? '系统' : `#${lg.operator_user_id}`}</td>
                  <td className="max-w-[200px] truncate px-3 py-2 text-red-400" title={lg.error}>{lg.error || '—'}</td>
                </tr>
              ))}
            </Table>
          </div>
        )}
      </Modal>
    </div>
  )
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-slate-500">{label}</label>
      {children}
    </div>
  )
}

export function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-400">
      <span>共 {total} 条</span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</Button>
        <span>{page} / {pages}</span>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</Button>
      </div>
    </div>
  )
}
