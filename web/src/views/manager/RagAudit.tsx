import { useEffect, useState } from 'react'
import { get, post, downloadFile, errMsg } from '../../lib/api'
import type {
  DeptOption, KnowledgeForm, KnowledgeReportPage, KnowledgeReportRow,
  KnowledgeReportSummary, LabelOption, KnowledgeSaveData,
  RagTurnDetailData, RagTurnPage, RagTurnRow,
} from '../../types/api'
import { Card, Badge, Button, Input, Select, Modal, Textarea, Empty, cn } from '../../components/ui'
import type { BadgeTone } from '../../components/ui'
import FilterBar from '../../components/FilterBar'
import { Field, Pager } from './Knowledge'

const THEME_OPTIONS = [
  { value: 'deposit', label: '缴存' },
  { value: 'loan', label: '贷款' },
  { value: 'withdraw', label: '提取' },
  { value: 'other', label: '其他' },
]

/** 一键转知识预填表单（KnowledgeBody + 来源轮次）。 */
interface ToKbForm extends KnowledgeForm {
  turn_id: number
}

function RagTurnsTab() {
  const [rows, setRows] = useState<RagTurnRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [depts, setDepts] = useState<DeptOption[]>([])
  const [flags, setFlags] = useState<LabelOption[]>([])
  const [filters, setFilters] = useState({
    intent: 'rag', dept_no: '', flag: '', start: '', end: '', user_rating: '',
  })
  const [detail, setDetail] = useState<RagTurnDetailData | null>(null)
  const [busy, setBusy] = useState(false)
  const [toKb, setToKb] = useState<ToKbForm | null>(null)
  const pageSize = 15

  const filterParams = () => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v) })
    return params
  }

  const load = async () => {
    const params = filterParams()
    params.set('page', String(page)); params.set('page_size', String(pageSize))
    const data = await get<RagTurnPage>(`/rag-audit/turns?${params}`)
    setRows(data.rows)
    setTotal(data.total)
  }

  useEffect(() => {
    get<DeptOption[]>('/audit/depts').then(setDepts).catch(() => {})
    get<LabelOption[]>('/rag-audit/flags').then(setFlags).catch(() => {})
  }, [])
  useEffect(() => { load() }, [page])

  const openDetail = async (id: number) => setDetail(await get<RagTurnDetailData>(`/rag-audit/turns/${id}`))

  const exportBadcase = async () => {
    setBusy(true)
    try {
      await downloadFile(`/rag-audit/export/badcase?${filterParams()}`,
        `RAG_badcase_${new Date().toISOString().slice(0, 10)}.xlsx`)
    } catch (e) { alert(errMsg(e, '导出失败')) } finally { setBusy(false) }
  }

  const openToKb = (d: RagTurnDetailData) => setToKb({
    dept_no: d.dept_no, biz_type: 'qa', theme: THEME_OPTIONS.some(t => t.value === d.theme) ? d.theme : 'other',
    title: d.question.slice(0, 60), question: d.question, answer: d.answer || '',
    content: '', is_public: 0, turn_id: d.id,
  })

  const saveToKb = async () => {
    setBusy(true)
    try {
      const r = await post<KnowledgeSaveData>('/knowledge', toKb)
      alert(`已入库：知识 #${r.id}（同步状态 ${r.sync_status === 1 ? '已向量化' : '待同步/失败'}）`)
      setToKb(null)
    } catch (e) { alert(errMsg(e, '入库失败')) } finally { setBusy(false) }
  }

  const pages = Math.max(Math.ceil(total / pageSize), 1)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <Button size="sm" variant="outline" disabled={busy} onClick={exportBadcase}>导出 badcase</Button>
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
                <option value="off_topic">无关话题</option>
              </Select>
            ),
          },
          {
            label: '质检标记', value: filters.flag,
            node: (
              <Select value={filters.flag}
                onChange={(e) => setFilters({ ...filters, flag: e.target.value })}>
                <option value="">全部标记</option>
                {flags.map((f) => <option key={f.code} value={f.code}>{f.label}</option>)}
              </Select>
            ),
          },
          {
            label: '用户反馈', value: filters.user_rating,
            node: (
              <Select value={filters.user_rating}
                onChange={(e) => setFilters({ ...filters, user_rating: e.target.value })}>
                <option value="">全部反馈</option>
                <option value="down">有差评</option>
                <option value="up">有点赞</option>
              </Select>
            ),
          },
        ]}
      />

      <Card>
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>{['轮次', '时间', '用户', '机构', '问题', '意图', '主题', '召回(候选/保留)', '质检标记', '用户反馈', '标记人', '操作'].map(h =>
              <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className="border-t border-slate-100 text-slate-600 hover:bg-slate-50/70">
                <td className="px-3 py-2.5 font-mono text-slate-400">#{t.id}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-slate-400">{t.created_at}</td>
                <td className="whitespace-nowrap px-3 py-2.5">{t.user}</td>
                <td className="whitespace-nowrap px-3 py-2.5 font-mono">{t.dept_no}</td>
                <td className="max-w-[260px] truncate px-3 py-2.5" title={t.question}>{t.question}</td>
                <td className="whitespace-nowrap px-3 py-2.5"><Badge tone="blue">{t.intent_label}</Badge></td>
                <td className="whitespace-nowrap px-3 py-2.5">{t.theme_label}</td>
                <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[11px]">
                  {t.recall_count} / <span className="text-emerald-600">{t.kept_count}</span>
                </td>
                <td className="max-w-[160px] truncate px-3 py-2.5" title={t.rag_note}>
                  {t.rag_flag_label
                    ? <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">{t.rag_flag_label}</span>
                    : <span className="text-slate-300">—</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5" title={t.fb_comment || ''}>
                  {t.fb_rating === 'down'
                    ? <span className="rounded bg-rose-50 px-1.5 py-0.5 text-rose-500">👎 差评</span>
                    : t.fb_rating === 'up'
                      ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-600">👍 点赞</span>
                      : <span className="text-slate-300">—</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-slate-400">
                  {t.rag_flag_by_name}{t.rag_flag_at ? ` · ${t.rag_flag_at}` : ''}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5">
                  <Button size="sm" variant="ghost" onClick={() => openDetail(t.id)}>详情</Button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={12} className="px-3 py-6"><Empty text="暂无检索型轮次（发起知识问答后产生）" /></td></tr>}
          </tbody>
        </table>
        <Pager page={page} pages={pages} total={total} onPage={setPage} />
      </Card>

      {detail && <RagDetail detail={detail} flags={flags} onClose={() => setDetail(null)}
        onSaved={load} onToKb={openToKb} />}
      {toKb && (
        <Modal open onClose={() => setToKb(null)} title={`轮次 #${toKb.turn_id} 一键转知识`} width="max-w-xl">
          <div className="space-y-3.5">
            <p className="rounded-md bg-amber-50 px-3 py-2 text-[11px] text-amber-700">
              已按该轮问答预填为「问答」类型知识，确认后保存将自动切块 + 向量化写入 ES。
            </p>
            <div className="grid grid-cols-3 gap-3">
              <Field label="归属机构号">
                <Input value={toKb.dept_no} onChange={(e) => setToKb({ ...toKb, dept_no: e.target.value })} />
              </Field>
              <Field label="类型">
                <Select value={toKb.biz_type} onChange={(e) => setToKb({ ...toKb, biz_type: e.target.value })}>
                  <option value="qa">问答</option>
                </Select>
              </Field>
              <Field label="主题">
                <Select value={toKb.theme} onChange={(e) => setToKb({ ...toKb, theme: e.target.value })}>
                  {THEME_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="标题">
              <Input value={toKb.title} onChange={(e) => setToKb({ ...toKb, title: e.target.value })} />
            </Field>
            <Field label="标准问法">
              <Input value={toKb.question} onChange={(e) => setToKb({ ...toKb, question: e.target.value })} />
            </Field>
            <Field label="标准答案（可修正后入库）">
              <Textarea rows={8} value={toKb.answer} onChange={(e) => setToKb({ ...toKb, answer: e.target.value })} />
            </Field>
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" checked={!!toKb.is_public}
                onChange={(e) => setToKb({ ...toKb, is_public: e.target.checked ? 1 : 0 })} />
              对下级机构公开（祖先链可见）
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setToKb(null)}>取消</Button>
              <Button disabled={busy || !toKb.title || !toKb.dept_no || !toKb.question || !toKb.answer} onClick={saveToKb}>
                {busy ? '入库中…' : '确认入库（切块+向量化）'}
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

function RagDetail({ detail, flags, onClose, onSaved, onToKb }: {
  detail: RagTurnDetailData
  flags: LabelOption[]
  onClose: () => void
  onSaved: () => void
  onToKb: (d: RagTurnDetailData) => void
}) {
  const [checked, setChecked] = useState<string[]>(
    detail.rag_flag ? detail.rag_flag.split(',').filter(Boolean) : [])
  const [note, setNote] = useState(detail.rag_note || '')
  const [busy, setBusy] = useState(false)

  const saveFlag = async () => {
    setBusy(true)
    try {
      await post(`/rag-audit/turns/${detail.id}/flag`, { flags: checked, note })
      const d = await get(`/rag-audit/turns/${detail.id}`)
      Object.assign(detail, d)
      onSaved()
      onClose()
    } catch (e) { alert(errMsg(e, '保存失败')) } finally { setBusy(false) }
  }

  return (
    <Modal open onClose={onClose} title={`轮次 #${detail.id} RAG 审计`} width="max-w-3xl">
      <div className="space-y-4">
        <div className="grid grid-cols-4 gap-2.5">
          {[
            ['意图', detail.intent_label], ['主题', detail.theme_label],
            ['区域', detail.region || '—'], ['机构', detail.dept_no],
            ['候选/保留', `${detail.recalls.length} / ${detail.recalls.filter((r) => r.kept).length}`],
            ['来源', detail.source_type === 'open' ? '开放接口' : '门户'],
            ['状态', detail.status], ['时间', detail.created_at],
            ['用户反馈', detail.feedback
              ? (detail.feedback.rating === 'down' ? '👎 差评' : '👍 点赞')
              : '—'],
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
          <div className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 px-3.5 py-2.5 text-xs leading-5 text-slate-600">
            {detail.answer || '（空）'}
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold text-slate-500">
            召回明细 <span className="font-normal text-slate-400">（RRF 融合名次 · 灰色行=被重排丢弃）</span>
          </p>
          <div className="overflow-hidden rounded-lg border border-slate-100">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>{['名次', '知识ID', '标题', '融合得分', '重排去留'].map(h =>
                  <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {detail.recalls.map((r) => (
                  <tr key={r.fused_rank} className={cn('border-t border-slate-50',
                    r.kept ? 'text-slate-600' : 'text-slate-300')}>
                    <td className="px-3 py-1.5 font-mono">{r.fused_rank}</td>
                    <td className="px-3 py-1.5 font-mono">#{r.knowledge_id}</td>
                    <td className="max-w-[320px] truncate px-3 py-1.5" title={r.title}>{r.title}</td>
                    <td className="px-3 py-1.5 font-mono">{r.fused_score}</td>
                    <td className="px-3 py-1.5">
                      {r.kept ? <Badge tone="green">保留</Badge> : <Badge tone="slate">丢弃</Badge>}
                    </td>
                  </tr>
                ))}
                {detail.recalls.length === 0 && (
                  <tr><td colSpan={5} className="px-3 py-4 text-center text-slate-300">无召回明细（存量历史轮次或非检索轮次）</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {detail.sources?.length > 0 && (
            <p className="mt-1.5 text-[10px] text-slate-400">
              展示来源：{detail.sources.map((s) => s.title).join('；')}
            </p>
          )}
        </div>

        <div className="rounded-lg border border-amber-100 bg-amber-50/40 p-3">
          <p className="mb-2 text-xs font-semibold text-slate-600">质检标记（最后写入覆盖）</p>
          <div className="flex flex-wrap gap-3">
            {flags.map((f) => (
              <label key={f.code} className="flex items-center gap-1.5 text-xs text-slate-600">
                <input type="checkbox" checked={checked.includes(f.code)}
                  onChange={(e) => setChecked(e.target.checked
                    ? [...checked, f.code]
                    : checked.filter((c) => c !== f.code))} />
                {f.label}
              </label>
            ))}
          </div>
          <Textarea className="mt-2" rows={2} placeholder="备注（哪里不准/该补什么知识…）"
            value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" disabled={busy} onClick={saveFlag}>{busy ? '保存中…' : '保存标记'}</Button>
            <Button size="sm" variant="outline" onClick={() => onToKb(detail)}>转为知识（预填入库）</Button>
            <span className="ml-auto text-[10px] text-slate-400">
              {detail.rag_flag_at ? `最近标记：${detail.rag_flag_at}` : '未标记'}
            </span>
          </div>
          {detail.feedback?.comment && (
            <p className="mt-2 rounded-md bg-rose-50 px-2.5 py-1.5 text-[11px] leading-4 text-rose-600">
              👎 用户修改意见：{detail.feedback.comment}
            </p>
          )}
        </div>
      </div>
    </Modal>
  )
}

const THEME_OPTIONS_REPORT = [
  { value: 'deposit', label: '缴存' }, { value: 'loan', label: '贷款' },
  { value: 'withdraw', label: '提取' }, { value: 'other', label: '其他' },
]
const SYNC_TONE_REPORT: Record<number, BadgeTone> = { 0: 'amber', 1: 'green', 2: 'red' }

function KnowledgeReportTab() {
  const [rows, setRows] = useState<KnowledgeReportRow[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<KnowledgeReportSummary | null>(null)
  const [page, setPage] = useState(1)
  const [depts, setDepts] = useState<DeptOption[]>([])
  const [filters, setFilters] = useState({
    dept_no: '', theme: '', biz_type: '', start: '', end: '',
    only_recalled: false, only_flagged: false,
  })
  const [busy, setBusy] = useState(false)
  const pageSize = 20

  const filterParams = () => {
    const params = new URLSearchParams()
    if (filters.start) params.set('start', filters.start)
    if (filters.end) params.set('end', filters.end)
    if (filters.dept_no) params.set('dept_no', filters.dept_no)
    if (filters.theme) params.set('theme', filters.theme)
    if (filters.biz_type) params.set('biz_type', filters.biz_type)
    if (filters.only_recalled) params.set('only_recalled', 'true')
    if (filters.only_flagged) params.set('only_flagged', 'true')
    return params
  }

  const load = async () => {
    const params = filterParams()
    params.set('page', String(page)); params.set('page_size', String(pageSize))
    const data = await get<KnowledgeReportPage>(`/rag-audit/knowledge-report?${params}`)
    setRows(data.rows); setTotal(data.total); setSummary(data.summary)
  }
  useEffect(() => { get<DeptOption[]>('/audit/depts').then(setDepts).catch(() => {}) }, [])
  useEffect(() => { load() }, [page])

  const doExport = async () => {
    setBusy(true)
    try {
      await downloadFile(`/rag-audit/export/knowledge-report?${filterParams()}`,
        `知识命中报表_${new Date().toISOString().slice(0, 10)}.xlsx`)
    } catch (e) { alert(errMsg(e, '导出失败')) } finally { setBusy(false) }
  }

  const pages = Math.max(Math.ceil(total / pageSize), 1)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <Button size="sm" variant="outline" disabled={busy} onClick={doExport}>导出报表</Button>
      </div>

      <FilterBar
        onQuery={() => { setPage(1); load() }}
        items={[
          {
            label: '提问时间范围', value: filters.start || filters.end,
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
            label: '类型', value: filters.biz_type,
            node: (
              <Select value={filters.biz_type}
                onChange={(e) => setFilters({ ...filters, biz_type: e.target.value })}>
                <option value="">全部类型</option>
                <option value="qa">问答</option>
                <option value="doc">文档</option>
                <option value="common">常识</option>
              </Select>
            ),
          },
          {
            label: '主题', value: filters.theme,
            node: (
              <Select value={filters.theme}
                onChange={(e) => setFilters({ ...filters, theme: e.target.value })}>
                <option value="">全部主题</option>
                {THEME_OPTIONS_REPORT.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </Select>
            ),
          },
          {
            label: '召回视角', value: filters.only_recalled,
            node: (
              <label className="flex h-8 items-center gap-1.5 text-xs text-slate-600">
                <input type="checkbox" checked={filters.only_recalled}
                  onChange={(e) => setFilters({ ...filters, only_recalled: e.target.checked })} />
                仅被召回过的知识
              </label>
            ),
          },
          {
            label: '差评视角', value: filters.only_flagged,
            node: (
              <label className="flex h-8 items-center gap-1.5 text-xs text-slate-600">
                <input type="checkbox" checked={filters.only_flagged}
                  onChange={(e) => setFilters({ ...filters, only_flagged: e.target.checked })} />
                仅有差评关联
              </label>
            ),
          },
        ]}
      />

      {summary && (
        <div className="flex flex-wrap gap-2 text-xs">
          {[
            ['知识条目', summary.kb_total, 'text-slate-600'],
            ['有召回', summary.recalled, 'text-emerald-600'],
            ['从未召回', summary.never_recalled, 'text-slate-400'],
            ['差评关联', summary.flagged_linked, 'text-amber-600'],
          ].map(([label, v, cls]) => (
            <span key={label as string} className="rounded-full bg-slate-50 px-3 py-1">
              {label as string}：<span className={cn('font-mono font-semibold', cls as string)}>{v as number}</span>
            </span>
          ))}
          <span className="self-center text-[10px] text-slate-300">
            差评关联 = 该知识被保留进入生成且该轮次打了质检标记
          </span>
        </div>
      )}

      <Card className="overflow-x-auto p-0">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>{['知识ID', '标题', '机构', '类型', '主题', '同步', '被召回轮次', '平均名次', '平均得分',
              '保留次数', '保留率', '差评关联', '用户差评', '差评率', '最后召回'].map(h =>
              <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={cn('border-t border-slate-100 text-slate-600',
                r.flagged_count > 0 && 'bg-amber-50/40')}>
                <td className="px-3 py-2 font-mono text-slate-400">#{r.id}</td>
                <td className="max-w-[240px] truncate px-3 py-2 font-medium" title={r.title}>{r.title}</td>
                <td className="whitespace-nowrap px-3 py-2 font-mono" title={r.dept_name}>{r.dept_no}</td>
                <td className="px-3 py-2">{r.biz_type_label}</td>
                <td className="px-3 py-2">{r.theme_label}</td>
                <td className="px-3 py-2"><Badge tone={SYNC_TONE_REPORT[r.sync_status]}>
                  {r.sync_status === 1 ? '已同步' : r.sync_status === 2 ? '失败' : '未同步'}</Badge></td>
                <td className="px-3 py-2 font-mono">{r.recall_turns}</td>
                <td className="px-3 py-2 font-mono">{r.avg_rank ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-[11px]">{r.avg_score ?? '—'}</td>
                <td className="px-3 py-2 font-mono">{r.kept_count}</td>
                <td className="px-3 py-2 font-mono">{r.kept_rate != null ? `${Math.round(r.kept_rate * 100)}%` : '—'}</td>
                <td className="px-3 py-2 font-mono">
                  {r.flagged_count > 0
                    ? <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">{r.flagged_count}</span>
                    : <span className="text-slate-300">0</span>}
                </td>
                <td className="px-3 py-2 font-mono">
                  {r.user_down > 0
                    ? <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-600">{r.user_down}</span>
                    : <span className="text-slate-300">0</span>}
                </td>
                <td className="px-3 py-2 font-mono">{r.flag_rate != null ? `${Math.round(r.flag_rate * 100)}%` : '—'}</td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-400">{r.last_recalled_at || '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={15} className="px-3 py-6 text-center text-slate-400">无匹配知识（或所选时间范围内无召回记录）</td></tr>
            )}
          </tbody>
        </table>
        <Pager page={page} pages={pages} total={total} onPage={setPage} />
      </Card>
    </div>
  )
}

function TabBtn({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      className={cn('rounded-lg px-3 py-1.5 text-xs transition-colors',
        active ? 'bg-brand/10 font-medium text-brand-dark' : 'text-slate-500 hover:bg-slate-100')}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

export default function RagAudit() {
  const [tab, setTab] = useState<'turns' | 'report'>('turns')
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">RAG 审计</h1>
        <p className="mt-0.5 text-xs text-slate-400">
          检索型轮次的召回明细（融合名次/得分/重排去留）· 质检标记驱动知识库持续优化 · 知识命中报表定位低质量与闲置知识
        </p>
      </div>
      <div className="flex gap-2 border-b border-slate-100 pb-2">
        <TabBtn active={tab === 'turns'} onClick={() => setTab('turns')}>轮次审计</TabBtn>
        <TabBtn active={tab === 'report'} onClick={() => setTab('report')}>知识命中报表</TabBtn>
      </div>
      {tab === 'turns' ? <RagTurnsTab /> : <KnowledgeReportTab />}
    </div>
  )
}
