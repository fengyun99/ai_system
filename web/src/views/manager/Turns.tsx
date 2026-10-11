import { useEffect, useState } from 'react'
import { get, downloadFile, errMsg } from '../../lib/api'
import type { DeptOption, StageRow, TurnDetailData, TurnPage, TurnRow } from '../../types/api'
import { Card, Table, Badge, Button, Input, Select, Modal, Empty, cn } from '../../components/ui'
import type { BadgeTone } from '../../components/ui'
import FilterBar from '../../components/FilterBar'

const STATUS_TONE: Record<string, BadgeTone> = {
  done: 'green', generating: 'amber', interrupted: 'slate', error: 'red',
}

export default function Turns() {
  const [rows, setRows] = useState<TurnRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [depts, setDepts] = useState<DeptOption[]>([])
  const [filters, setFilters] = useState({
    intent: '', status: '', keyword: '', dept_no: '', source: '', start: '', end: '',
  })
  const [detail, setDetail] = useState<TurnDetailData | null>(null)
  const [busy, setBusy] = useState(false)
  const pageSize = 15

  const filterParams = () => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v) })
    return params
  }

  const load = async () => {
    const params = filterParams()
    params.set('page', String(page)); params.set('page_size', String(pageSize))
    const data = await get<TurnPage>(`/audit/turns?${params}`)
    setRows(data.rows)
    setTotal(data.total)
  }

  useEffect(() => { get<DeptOption[]>('/audit/depts').then(setDepts).catch(() => {}) }, [])
  useEffect(() => { load() }, [page])

  const openDetail = async (id: number) => {
    const d = await get<TurnDetailData>(`/audit/turns/${id}`)
    setDetail(d)
  }

  const doExport = async (kind: 'turns' | 'qa') => {
    setBusy(true)
    try {
      await downloadFile(`/audit/export/${kind}?${filterParams()}`,
        `意图识别数据_${new Date().toISOString().slice(0, 10)}.xlsx`)
    } catch (e) { alert(errMsg(e, '导出失败')) } finally { setBusy(false) }
  }

  const pages = Math.max(Math.ceil(total / pageSize), 1)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">轮次审计</h1>
          <p className="mt-0.5 text-xs text-slate-400">
            每轮问答的阶段流水（意图/区域/分类/分化/检索/重排/生成/工具）与 token/耗时登记
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => doExport('turns')}>导出意图</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => doExport('qa')}>导出QA</Button>
        </div>
      </div>

      <FilterBar
        onQuery={() => { setPage(1); load() }}
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
            label: '意图', value: filters.intent,
            node: (
              <Select value={filters.intent}
                onChange={(e) => setFilters({ ...filters, intent: e.target.value })}>
                <option value="">全部意图</option>
                <option value="rag">知识问答</option>
                <option value="business">业务办理</option>
                <option value="chitchat">寒暄闲聊</option>
                <option value="off_topic">无关话题</option>
                <option value="handoff">转人工</option>
              </Select>
            ),
          },
          {
            label: '状态', value: filters.status,
            node: (
              <Select value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
                <option value="">全部状态</option>
                <option value="done">完成</option>
                <option value="interrupted">已停止</option>
                <option value="error">错误</option>
              </Select>
            ),
          },
          {
            label: '来源', value: filters.source,
            node: (
              <Select value={filters.source}
                onChange={(e) => setFilters({ ...filters, source: e.target.value })}>
                <option value="">全部来源</option>
                <option value="portal">门户</option>
                <option value="open">开放接口</option>
              </Select>
            ),
          },
          {
            label: '问题关键词', value: filters.keyword,
            node: (
              <Input placeholder="问题包含…" value={filters.keyword}
                onChange={(e) => setFilters({ ...filters, keyword: e.target.value })}
                onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); load() } }} />
            ),
          },
        ]}
      />

      <Card>
        <Table headers={['轮次', '用户', '机构', '问题', '意图', '区域', '主题', '来源', '状态', 'Token(入/出)', 'TTFT', '总耗时', '成本', 'TraceID', '时间', '']}>
          {rows.length === 0 && (
            <tr><td colSpan={16}><Empty /></td></tr>
          )}
          {rows.map((t) => (
            <tr key={t.id} className="text-xs text-slate-600 hover:bg-slate-50/70">
              <td className="px-4 py-2.5 font-mono text-slate-400">#{t.id}</td>
              <td className="whitespace-nowrap px-4 py-2.5">{t.user}</td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono">{t.dept_no}</td>
              <td className="max-w-[240px] truncate px-4 py-2.5" title={t.question}>{t.question}</td>
              <td className="whitespace-nowrap px-4 py-2.5">
                {t.intent && <Badge tone="blue">{t.intent_label || t.intent}</Badge>}
              </td>
              <td className="whitespace-nowrap px-4 py-2.5">{t.region || '—'}</td>
              <td className="whitespace-nowrap px-4 py-2.5">{t.theme_label || t.theme || '—'}</td>
              <td className="whitespace-nowrap px-4 py-2.5 text-slate-500">
                {t.source_type === 'open' ? '开放接口' : '门户'}
              </td>
              <td className="whitespace-nowrap px-4 py-2.5">
                <Badge tone={STATUS_TONE[t.status]}>{t.status}</Badge>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px]">
                {t.tokens_in}/{t.tokens_out}
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px]">{t.ttft_ms}ms</td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px]">{t.total_ms}ms</td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px] text-emerald-600">
                {`¥${t.cost.toFixed(4)}`}
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px] text-slate-400" title={t.trace_id}>
                {t.trace_id ? `${t.trace_id.slice(0, 8)}…` : '—'}
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 text-slate-400">{t.created_at}</td>
              <td className="px-4 py-2.5">
                <Button size="sm" variant="ghost" onClick={() => openDetail(t.id)}>详情</Button>
              </td>
            </tr>
          ))}
        </Table>
        <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-400">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
            <span>{page} / {pages}</span>
            <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</Button>
          </div>
        </div>
      </Card>

      <TurnDetail detail={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

const STAGE_TONE: Record<string, BadgeTone> = {
  intent: 'violet', region: 'amber', classify: 'blue', decompose: 'blue',
  retrieve: 'green', rerank: 'green', generate: 'slate', tool: 'amber',
  handoff: 'amber',
}
const STAGE_LABEL: Record<string, string> = {
  intent: '意图识别', region: '区域识别', classify: '问题分类', decompose: '问题分化',
  retrieve: '混合检索', rerank: '重排序', generate: '回答生成', tool: 'MCP 工具',
  handoff: '人工转接',
}

function TurnDetail({ detail, onClose }: { detail: TurnDetailData | null; onClose: () => void }) {
  if (!detail) return null
  return (
    <Modal open onClose={onClose} title={`轮次 #${detail.id} 审计详情`} width="max-w-3xl">
      <div className="space-y-4">
        <div className="grid grid-cols-4 gap-2.5">
          {[
            ['意图', detail.intent_label || detail.intent || '—'],
            ['区域', detail.region || '—'],
            ['主题', detail.theme_label || detail.theme || '—'],
            ['状态', detail.status],
            ['Token(入/出)', `${detail.tokens_in} / ${detail.tokens_out}`],
            ['首字延迟', `${detail.ttft_ms} ms`],
            ['整轮耗时', `${detail.total_ms} ms`],
            ['成本', `¥${detail.cost.toFixed(4)}`],
            ['TraceId', detail.trace_id || '—'],
            ['快照', detail.snapshot_id ? `${detail.snapshot_id.slice(0, 10)}…` : '—'],
          ].map(([k, v]) => (
            <div key={k as string} className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-[10px] text-slate-400">{k}</p>
              <p className="mt-0.5 truncate font-mono text-xs font-medium text-slate-700">{v}</p>
            </div>
          ))}
        </div>

        <div>
          <p className="mb-1.5 text-xs font-semibold text-slate-500">用户问题</p>
          <div className="rounded-lg bg-slate-50 px-3.5 py-2.5 text-sm text-slate-700">{detail.question}</div>
        </div>
        <div>
          <p className="mb-1.5 text-xs font-semibold text-slate-500">回答全文</p>
          <div className="max-h-44 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 px-3.5 py-2.5 text-xs leading-5 text-slate-600">
            {detail.answer || '（空）'}
          </div>
        </div>

        <StageTimeline stages={detail.stages} />

        <div>
          <p className="mb-2 text-xs font-semibold text-slate-500">
            阶段流水 <span className="font-normal text-slate-400">（{detail.stages.length} 个阶段）</span>
          </p>
          {detail.error_detail && (
            <pre className="mb-2 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-red-50 px-3 py-2 font-mono text-[10px] leading-relaxed text-red-500">{detail.error_detail}</pre>
          )}
          <div className="space-y-2">
            {detail.stages.map((s) => (
              <details key={s.stage_no} className="group rounded-lg border border-slate-100">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs hover:bg-slate-50">
                  <span className="font-mono text-slate-300">{String(s.stage_no).padStart(2, '0')}</span>
                  <Badge tone={STAGE_TONE[s.stage_type]}>{STAGE_LABEL[s.stage_type] || s.stage_type}</Badge>
                  <span className="text-slate-500">{s.name}</span>
                  <span className={cn('ml-auto font-mono text-[10px]', s.status === 'failed' ? 'text-red-400' : 'text-slate-400')}>
                    {s.model && <span className="mr-2">{s.model}</span>}
                    {(s.tokens_in || s.tokens_out) && (
                      <span className="mr-2">
                        {s.tokens_in}+{s.tokens_out}tok
                        {s.tokens_estimated === 1 && (
                          <span title="本行含字符估算口径（供应商未返回 usage）" className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-600">估</span>
                        )}
                      </span>
                    )}
                    {s.cost !== 0 && <span className="mr-2 text-emerald-600">¥{s.cost.toFixed(4)}</span>}
                    {s.duration_ms}ms
                    {s.status === 'failed' && ' · 已回退'}
                  </span>
                </summary>
                <div className="grid grid-cols-2 gap-3 border-t border-slate-50 px-3 py-2.5">
                  <JsonBlock title="输入" data={s.input} />
                  <JsonBlock title="输出" data={s.output} />
                  {s.error_detail && (
                    <pre className="col-span-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-red-50 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-red-500">{s.error_detail}</pre>
                  )}
                </div>
              </details>
            ))}
            {detail.stages.length === 0 && <Empty text="无阶段记录" />}
          </div>
        </div>
      </div>
    </Modal>
  )
}

/** 阶段时间线（票据 07）：条形按起止墙钟相对轮起点排布，并行分叉一眼可见。
 *
 * 起止时间来自票据 06 的 DATETIME(6)（"YYYY-MM-DD HH:MM:SS.ffffff"）；存量历史
 * 轮次无起止（空串）不绘条形，以脚注说明。
 */
function parseTs(s: string): number | null {
  if (!s) return null
  const iso = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  const t = new Date(iso).getTime()
  return Number.isNaN(t) ? null : t
}

function clockOf(ms: number): string {
  const d = new Date(ms)
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}

function StageTimeline({ stages }: { stages: StageRow[] }) {
  const rows = stages
    .map((s) => ({ s, start: parseTs(s.started_at), end: parseTs(s.finished_at) }))
    .filter((r): r is { s: StageRow; start: number; end: number } =>
      r.start !== null && r.end !== null)
  if (rows.length === 0) {
    return stages.length > 0 ? (
      <p className="text-[10px] text-slate-300">存量历史轮次无阶段起止时间，时间线不可用</p>
    ) : null
  }
  const t0 = Math.min(...rows.map((r) => r.start))
  const t1 = Math.max(...rows.map((r) => r.end))
  const span = Math.max(t1 - t0, 1)
  const skipped = stages.length - rows.length
  return (
    <div>
      <div className="mb-1 flex items-center justify-between pl-[11.5rem] pr-16 font-mono text-[9px] text-slate-300">
        <span>{clockOf(t0)}</span>
        <span>跨度 {span} ms</span>
        <span>{clockOf(t1)}</span>
      </div>
      <div className="space-y-1">
        {rows.map(({ s, start, end }) => {
          const left = ((start - t0) / span) * 100
          const rawWidth = ((end - start) / span) * 100
          const width = Math.max(rawWidth, 0.8)
          const invalid = end < start   // 起止倒置的异常行：clamp 到最小宽并标红
          const tok = s.tokens_in || s.tokens_out
          const tip = [
            s.name,
            `${clockOf(start)} → ${clockOf(end)}`,
            `${s.duration_ms}ms` +
              (tok ? ` · ${s.tokens_in}+${s.tokens_out}tok${s.tokens_estimated === 1 ? '（估）' : ''}` : '') +
              (s.cost !== 0 ? ` · ¥${s.cost.toFixed(4)}` : '') +
              (s.status === 'failed' ? ' · 已回退' : ''),
          ].join('\n')
          return (
            <div key={s.stage_no} className="flex items-center gap-2">
              <span className="w-44 shrink-0 truncate text-right text-[10px] text-slate-400" title={s.name}>
                <span className="font-mono text-slate-300">{String(s.stage_no).padStart(2, '0')}</span>{' '}
                {STAGE_LABEL[s.stage_type] || s.stage_type}
              </span>
              <div className="relative h-4 flex-1 rounded bg-slate-50">
                <div
                  className={cn('absolute inset-y-0.5 rounded',
                    (s.status === 'failed' || invalid) ? 'bg-red-400' : 'bg-brand/60')}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={tip}
                />
              </div>
              <span className="w-14 shrink-0 text-right font-mono text-[10px] text-slate-400">{s.duration_ms}ms</span>
            </div>
          )
        })}
      </div>
      {skipped > 0 && (
        <p className="mt-1 text-[10px] text-slate-300">另有 {skipped} 个阶段无起止时间（存量历史轮次），未绘制</p>
      )}
    </div>
  )
}

function JsonBlock({ title, data }: { title: string; data: unknown }) {
  return (
    <div>
      <p className="mb-1 text-[10px] font-medium text-slate-400">{title}</p>
      <pre className="max-h-40 overflow-auto rounded-md bg-slate-50 p-2.5 font-mono text-[10px] leading-4 text-slate-500">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}
