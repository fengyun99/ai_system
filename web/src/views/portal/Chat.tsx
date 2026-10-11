import { useEffect, useRef, useState, useCallback } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { store, type RootState } from '../../store'
import { fetchInfo, logout } from '../../store/authSlice'
import { get, del, post, sse, sseGet, uploadFlowFile, errMsg } from '../../lib/api'
import type { ConversationDetailData, FlowCard, FlowCurrentData, StreamEvent } from '../../types/api'
import { Button, Badge, cn } from '../../components/ui'

marked.setOptions({ breaks: true, gfm: true })

interface StageEvent {
  stage_type: string
  name: string
  status?: string
  duration_ms?: number
  summary?: unknown
}

/** 阶段语义摘要载荷（各 stage_type 的动态字段，展示层按需取用）。 */
interface StageSummary {
  intent?: string
  is_external?: boolean
  region_name?: string
  target_dept_no?: string
  theme?: string
  sub_queries?: string[]
  routes?: { bm25_hits?: number; knn_hits?: number }[]
  fused?: number
  fallback?: boolean
  kept?: unknown[]
  can_answer?: boolean
  reason?: string
  count?: number
  discovered?: unknown[]
  visible?: unknown[]
  arguments?: Record<string, unknown>
  result?: string
  flows?: string[]
}

interface ToolCall {
  name: string
  arguments: Record<string, unknown>
  result?: string
}

/** 流程卡片（后端 flow_engine._node_card 契约，见 types/api.ts）。 */
type FlowCardDef = FlowCard

interface FlowSection {
  type: 'form' | 'confirm' | 'auto' | 'end' | 'cancelled' | 'form_summary' | 'note' | 'result'
  title?: string
  node_key?: string
  fields?: { name: string; label: string; value: string; error?: string }[]
  summary?: string
  result?: string
  text?: string
  attempts?: number
  prior_notes?: string[]
}

interface FlowUI {
  instanceId: number
  flowName: string
  status: 'running' | 'done' | 'cancelled'
  card: FlowCardDef | null
  autoResults: string[]
  errors?: Record<string, string>      // 后端字段级校验错误（红色提示）
  filled?: Record<string, string | number>   // 已提交值（历史还原展示）
  readonly?: boolean                   // 历史消息中的卡片只读展示
  sections?: FlowSection[]             // 历史还原：原始表单形态段落
  statusText?: string                  // 卡片内状态文案（流程文字不进对话流）
}

interface SourceItem {
  title: string
  source?: string          // kb | web
  url?: string
  engine?: string
  dept_name?: string
  knowledge_id?: number
  text?: string
  rerank_score?: number
}

interface FlowRec {
  flow_key: string
  name: string
  description?: string
  mode?: string            // embed=流程引擎嵌入 / redirect=复杂业务跳转页面
  url?: string
}

interface TurnMsg {
  id: number | null
  question: string
  answer: string
  status: 'streaming' | 'done' | 'error' | 'stopped'
  stages: StageEvent[]
  tools: ToolCall[]
  sources?: SourceItem[]
  flows?: FlowRec[]
  questions?: string[]
  flow?: FlowUI
  progress?: string
  at?: string
  feedback?: { rating: 'up' | 'down'; comment?: string }
}

interface ConversationItem {
  id: number
  title: string
  turn_count: number
  updated_at: string
}

const PROGRESS_TEXT: Record<string, string> = {
  understanding: '理解问题中…',
  searching: '检索知识库…',
  web_searching: '联网检索中…',
  generating: '生成回答中…',
}

const STAGE_ICON: Record<string, string> = {
  intent: '🎯',
  region: '📍',
  classify: '🏷️',
  decompose: '✂️',
  retrieve: '🔍',
  rerank: '📊',
  judge: '⚖️',
  web_search: '🌐',
  generate: '✍️',
  tool: '🔧',
  flow: '📋',
}

const INTENT_TEXT: Record<string, string> = {
  rag: '知识问答',
  business: '业务办理',
  chitchat: '闲聊',
}

function renderMd(text: string): string {
  return DOMPurify.sanitize(marked.parse(text || '') as string)
}
const THEME_TEXT: Record<string, string> = {
  deposit: '缴存',
  loan: '贷款',
  withdraw: '提取',
  other: '其他',
}

/** 阶段语义摘要（portal 侧不含 token/耗时——那些只在管理端审计展示）。 */
function stageSummary(s: StageEvent): string {
  const d = (s.summary || {}) as StageSummary
  switch (s.stage_type) {
    case 'intent':
      return (d.intent ? INTENT_TEXT[d.intent] : '') || d.intent || ''
    case 'region':
      if (d.is_external) return `外地区（${d.region_name || '—'}）→ 联网`
      return d.region_name ? `${d.region_name}${d.target_dept_no ? ' · ' + d.target_dept_no : ''}` : '本机构'
    case 'classify':
      return (d.theme ? THEME_TEXT[d.theme] : '') || d.theme || ''
    case 'decompose': {
      const subs: string[] = d.sub_queries || []
      return subs.length > 1 ? `${subs.length} 个子查询：${subs.join(' / ')}` : ''
    }
    case 'retrieve': {
      const routes = d.routes || []
      const bm = routes.reduce((n, r) => n + (r.bm25_hits || 0), 0)
      const kn = routes.reduce((n, r) => n + (r.knn_hits || 0), 0)
      return `BM25 ${bm} 命中 + 向量 ${kn} 命中 → RRF 融合 ${d.fused ?? 0} 条`
    }
    case 'rerank':
      return d.fallback ? '调用失败，已回退融合序' : `重排保留 ${(d.kept || []).length} 条`
    case 'judge':
      return d.can_answer ? '材料充分' : `材料不足${d.reason ? '：' + String(d.reason).slice(0, 40) : ''}`
    case 'web_search':
      return s.status === 'failed' ? '自建检索服务不可用' : `自建检索服务命中 ${d.count ?? 0} 条`
    case 'tool': {
      if (d.discovered) return `发现 ${(d.discovered || []).length} 个工具，本部门可见 ${(d.visible || []).length} 个`
      if (d.arguments) return Object.entries(d.arguments).map(([k, v]) => `${k}=${v}`).join('  ')
      if (d.result) return '已完成'
      return ''
    }
    case 'flow':
      if (d.flows) return `推荐：${(d.flows || []).join('、')}`
      return ''
    case 'generate':
      if (d.reason === 'external') return '外地区拒答'
      if (d.reason === 'web_empty') return '联网未获有效信息，拒答'
      if (d.reason === 'insufficient') return '知识不足，拒答'
      return ''
  }
  return ''
}

/** 纵向处理流程（自上而下）：轨道 = 已完成节点连线，末端为进行中节点。 */
function StageFlow({ msg }: { msg: TurnMsg }) {
  const active = msg.status === 'streaming'
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 shadow-sm">
      <p className="mb-2 text-[10px] font-medium tracking-wide text-slate-400">处理流程</p>
      <div>
        {msg.stages.map((s, i) => {
          const isLast = i === msg.stages.length - 1
          const failed = s.status === 'failed'
          return (
            <div key={i} className="flex gap-2.5">
              <div className="flex w-3 flex-col items-center">
                <span
                  className={cn(
                    'mt-[3px] h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white',
                    failed ? 'bg-amber-400' : 'bg-emerald-500',
                  )}
                />
                {(!isLast || active) && <span className="w-px flex-1 bg-slate-200" />}
              </div>
              <div className={cn('flex min-w-0 flex-1 items-baseline gap-2', (!isLast || active) && 'pb-2')}>
                <span className="shrink-0 text-[11px] font-medium text-slate-700">
                  <span className="mr-1">{STAGE_ICON[s.stage_type] || '·'}</span>
                  {s.name}
                </span>
                {failed && <span className="shrink-0 text-[10px] text-amber-500">已回退</span>}
                <span className="min-w-0 truncate text-[10px] text-slate-400" title={stageSummary(s)}>
                  {stageSummary(s)}
                </span>
              </div>
            </div>
          )
        })}
        {active && msg.progress && (
          <div className="flex gap-2.5">
            <div className="flex w-3 flex-col items-center">
              <span className="mt-[3px] h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-brand ring-2 ring-white" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-[11px] font-medium text-brand-dark">
                {PROGRESS_TEXT[msg.progress] || msg.progress}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Chat() {
  const dispatch = useDispatch<typeof store.dispatch>()
  const auth = useSelector((s: RootState) => s.auth)

  const [conversations, setConversations] = useState<ConversationItem[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<TurnMsg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [turnId, setTurnId] = useState<number | null>(null)
  const [gateHint, setGateHint] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const turnIdRef = useRef<number | null>(null)
  const stoppedRef = useRef(false)
  const streamingRef = useRef(false)
  const didInitRef = useRef(false)                 // StrictMode 双挂载防护
  const activeResumeRef = useRef<number | null>(null)  // 回放幂等锁：同轮只允许一路
  useEffect(() => {
    streamingRef.current = streaming
  }, [streaming])

  const runningFlow = messages.find((m) => m.flow?.status === 'running')?.flow ?? null

  useEffect(() => {
    if (didInitRef.current) return
    didInitRef.current = true
    if (!auth.user) dispatch(fetchInfo())
    loadConversations()
    // 断线重连①：刷新后自动回到最近会话（有则还原，无则保持新会话）
    const last = Number(localStorage.getItem('ai_last_conversation') || 0)
    if (last) loadConversation(last)
  }, [])

  useEffect(() => {
    if (conversationId) localStorage.setItem('ai_last_conversation', String(conversationId))
  }, [conversationId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadConversations = async () => {
    try {
      setConversations(await get<ConversationItem[]>('/conversations'))
    } catch {
      /* 静默 */
    }
  }

  const restoreFlow = async (cid: number) => {
    try {
      const st = await get<FlowCurrentData>(`/flow/current?conversation_id=${cid}`)
      if (st.running) {
        setMessages((prev) => [
          ...prev,
          {
            id: null, question: `[业务办理] ${st.flow_name}`, answer: '',
            status: 'done', stages: [], tools: [], sources: [],
            flow: {
              instanceId: st.instance_id ?? 0, flowName: st.flow_name ?? '',
              status: 'running', card: st.card ?? null, autoResults: [],
            },
          },
        ])
      }
    } catch {
      /* 静默 */
    }
  }

  const loadConversation = async (id: number) => {
    setConversationId(id)
    setGateHint('')
    try {
      const data = await get<ConversationDetailData>(`/conversations/${id}`)
      const turnMsgs: TurnMsg[] = (data.turns || []).map((t) => ({
        id: t.id,
        question: t.question,
        answer: t.answer,
        status: (t.status === 'interrupted' ? 'stopped' : t.status) as TurnMsg['status'],
        stages: t.stages || [],
        tools: t.tools || [],
        sources: t.sources && t.sources.length ? (t.sources as unknown as SourceItem[]) : undefined,
        questions: t.questions && t.questions.length ? (t.questions as string[]) : undefined,
        flows: t.recommend_flows && t.recommend_flows.length ? (t.recommend_flows as FlowRec[]) : undefined,
        at: t.created_at,
        feedback: t.feedback ? { ...t.feedback, rating: t.feedback.rating as 'up' | 'down' } : undefined,
      }))
      const flowMsgs: TurnMsg[] = (data.flows || []).map((f) => ({
        id: null,
        question: '',
        answer: '',
        status: 'done',
        stages: [],
        tools: [],
        at: f.created_at,
        flow: {
          instanceId: f.instance_id,
          flowName: f.flow_name,
          status: (f.status === 'running' ? 'done' : f.status) as FlowUI['status'],
          card: null,
          autoResults: [],
          sections: (f.sections || []) as FlowSection[],
          readonly: true,
        },
      }))
      const merged = [...turnMsgs, ...flowMsgs].sort((a, b) => String(a.at).localeCompare(String(b.at)))
      setMessages(merged)
      await restoreFlow(id)
      // 断线重连④：末轮仍在生成（刷新页面时）→ 自动续流补全后续内容
      const lastTurn = (data.turns || []).slice(-1)[0]
      if (lastTurn && lastTurn.status === 'generating'
          && activeResumeRef.current !== lastTurn.id) {
        resumeTurn(lastTurn.id)
      }
    } catch {
      /* 静默 */
    }
  }

  const newConversation = () => {
    setConversationId(null)
    localStorage.removeItem('ai_last_conversation')
    setMessages([])
    setGateHint('')
  }

  const removeConversation = async (id: number) => {
    await del(`/conversations/${id}`)
    if (conversationId === id) newConversation()
    loadConversations()
  }

  const patchLast = (patch: Partial<TurnMsg> | ((m: TurnMsg) => TurnMsg)) => {
    setMessages((prev) => {
      if (!prev.length) return prev
      const next = [...prev]
      const last = next[next.length - 1]
      next[next.length - 1] = typeof patch === 'function' ? patch(last) : { ...last, ...patch }
      return next
    })
  }

  /** 按轮次 id 定位更新（续流回放专用，不依赖"最后一条"）。 */
  const patchTurn = (turnId: number, patch: Partial<TurnMsg> | ((m: TurnMsg) => TurnMsg)) => {
    setMessages((prev) => prev.map((m) =>
      m.id === turnId ? (typeof patch === 'function' ? patch(m) : { ...m, ...patch }) : m))
  }

  /** 重连回放前重置该轮渲染（后台缓存整轮回归，不在半截内容上追加）。 */
  const resetTurnForResume = (turnId: number) => {
    setMessages((prev) => prev.map((m) => m.id === turnId ? {
      ...m, answer: '', stages: [], tools: [],
      sources: undefined, questions: undefined, flows: undefined,
      status: 'streaming', progress: 'understanding',
    } : m))
  }

  /** 轮次事件 → 渲染（发送/断线续流共用；targetId 存在时按轮次定位）。 */
  const applyTurnEvent = (ev: StreamEvent, targetId: number | null = null) => {
    const P = (patch: Partial<TurnMsg> | ((m: TurnMsg) => TurnMsg)) =>
      (targetId ? patchTurn(targetId, patch) : patchLast(patch))
    switch (ev.type) {
      case 'progress':
        P({ progress: ev.stage })
        break
      case 'stage':
        P((m: TurnMsg) => ({ ...m, stages: [...m.stages, ev] }))
        break
      case 'text':
        P((m: TurnMsg) => ({ ...m, answer: m.answer + ev.content }))
        break
      case 'tool':
        P((m: TurnMsg) => ({ ...m, tools: [...m.tools, { name: ev.name, arguments: ev.arguments }] }))
        break
      case 'tool_result':
        P((m: TurnMsg) => {
          const tools = [...m.tools]
          for (let i = tools.length - 1; i >= 0; i--) {
            if (tools[i].name === ev.name && !tools[i].result) {
              tools[i] = { ...tools[i], result: ev.result }
              break
            }
          }
          return { ...m, tools }
        })
        break
      case 'sources':
        P({ sources: ev.materials as unknown as SourceItem[] })
        break
      case 'recommend':
        P({ flows: ev.flows as FlowRec[] })
        break
      case 'question':
        P({ questions: ev.questions as string[] })
        break
      case 'error':
        P({ status: 'error', answer: `⚠️ ${ev.message}` })
        break
      case 'done':
        P((m: TurnMsg) => (m.status === 'error' ? m : { ...m, status: 'done' }))
        break
    }
  }

  /** 断线重连②：整轮回归——先重置该轮渲染，回放从缓存从头重绘（非追加）。
   *  幂等锁保证同一轮同时只有一路回放（StrictMode 双挂载/看门狗并发均不会交错）。 */
  const resumeTurn = useCallback(
    async (turnId: number) => {
      if (activeResumeRef.current === turnId) return
      activeResumeRef.current = turnId
      resetTurnForResume(turnId)
      setStreaming(true)
      try {
        await sseGet(`/chat/resume/${turnId}`, (ev) => {
          if (ev.type === 'meta') return
          applyTurnEvent(ev, turnId)
        })
      } catch {
        /* 续流失败：按已完成处理，回读历史兜底 */
        if (conversationId) loadConversation(conversationId)
      } finally {
        activeResumeRef.current = null
        setStreaming(false)
        loadConversations()
      }
    },
    [conversationId],
  )

  const send = useCallback(
    async (question: string) => {
      if (!question.trim() || streaming) return
      if (runningFlow) {
        setGateHint('流程办理中：请先完成或取消当前业务办理，再继续提问')
        return
      }
      setInput('')
      setGateHint('')
      setStreaming(true)
      stoppedRef.current = false
      const draft: TurnMsg = {
        id: null, question, answer: '', status: 'streaming',
        stages: [], tools: [], progress: 'understanding',
      }
      setMessages((prev) => [...prev, draft])
      const ctrl = new AbortController()
      abortRef.current = ctrl
      let lastEventAt = Date.now()

      // 断线重连③：空闲看门狗——15 秒无事件 → 查状态续流/回读
      const watchdog = setInterval(async () => {
        if (!streamingRef.current) return
        if (Date.now() - lastEventAt < 15000) return
        const tid = turnIdRef.current
        if (!tid) return
        try {
          const st = await get<{ running: boolean }>(`/chat/progress/${tid}`)
          if (st.running) {
            // 连接假死：断开当前读循环，转续流
            abortRef.current?.abort()
          } else {
            abortRef.current?.abort()
          }
        } catch {
          /* 忽略 */
        }
      }, 5000)

      try {
        await sse(
          '/chat/stream',
          { question, conversation_id: conversationId },
          (ev) => {
            lastEventAt = Date.now()
            if (ev.type === 'meta') {
              if (conversationId == null) setConversationId(ev.conversation_id)
              setTurnId(ev.turn_id)
              turnIdRef.current = ev.turn_id
              patchLast({ id: ev.turn_id })
              return
            }
            applyTurnEvent(ev, turnIdRef.current)
          },
          ctrl.signal,
        )
      } catch {
        if (stoppedRef.current) {
          patchLast((m) => ({ ...m, status: 'stopped' }))
        } else {
          // 断线/假死恢复：查状态 → 运行中则续流，否则回读历史兜底
          const tid = turnIdRef.current
          let resumed = false
          if (tid) {
            try {
              const st = await get<{ running: boolean }>(`/chat/progress/${tid}`)
              if (st.running) {
                setStreaming(false)
                await resumeTurn(tid)
                resumed = true
              }
            } catch {
              /* 落到回读 */
            }
          }
          if (!resumed) {
            if (conversationId) await loadConversation(conversationId)
            else patchLast({ status: 'error', answer: '⚠️ 连接中断，请重试' })
          }
        }
      } finally {
        clearInterval(watchdog)
        setStreaming(false)
        abortRef.current = null
        loadConversations()
      }
    },
    [conversationId, streaming, runningFlow],
  )

  const stop = async () => {
    stoppedRef.current = true
    if (turnId) {
      try {
        await post('/chat/stop', { turn_id: turnId })
      } catch {
        /* 尽力 */
      }
    }
    abortRef.current?.abort()
  }

  /** 发起业务办理（办理中门控由后端 + 前端双重保证）。 */
  const startFlow = async (flowKey: string, flowName: string) => {
    if (runningFlow) return
    setStreaming(true)
    setMessages((prev) => [
      ...prev,
      {
        id: null, question: '', answer: '',
        status: 'streaming', stages: [], tools: [], progress: 'understanding',
        flow: { instanceId: 0, flowName, status: 'running', card: null, autoResults: [],
                statusText: '办理中…' },
      },
    ])
    try {
      await sse('/flow/start', { flow_key: flowKey, conversation_id: conversationId }, (ev) => {
        if (ev.type === 'meta') {
          if (conversationId == null) setConversationId(ev.conversation_id)
          patchLast({ id: ev.turn_id })
        } else if (ev.type === 'flow_start') {
          patchLast((m) => ({
            ...m,
            flow: {
              instanceId: ev.instance_id, flowName: ev.flow_name, status: 'running',
              card: ev.card ?? null, autoResults: [],
            },
          }))
        } else if (ev.type === 'done') {
          patchLast((m) => ({ ...m, status: 'done' }))
        }
      })
    } catch (e) {
      const msg = errMsg(e, '未知原因')
      patchLast((m) => (m.flow
        ? { ...m, status: 'error', flow: { ...m.flow, statusText: `启动失败：${msg}` } }
        : { ...m, status: 'error', answer: `⚠️ ${msg}` }))
    } finally {
      setStreaming(false)
      loadConversations()
    }
  }

  /** 提交流程节点（表单/确认）。 */
  const submitFlow = async (instanceId: number, nodeKey: string, data: Record<string, unknown>) => {
    if (streaming) return
    setStreaming(true)
    try {
      await sse('/flow/submit', { instance_id: instanceId, node_key: nodeKey, data }, (ev) => {
        if (ev.type === 'form_error') {
          // 后端模拟校验失败：字段级错误就地展示，流程停留当前节点
          patchLast((m) => (m.flow ? {
            ...m, flow: { ...m.flow, errors: ev.errors,
                          statusText: '表单校验未通过，请按提示修改后重新提交' },
          } : m))
        } else if (ev.type === 'card') {
          patchLast((m) => (m.flow ? { ...m, flow: { ...m.flow, card: ev.card, errors: {} } } : m))
        } else if (ev.type === 'flow_auto') {
          patchLast((m) => (m.flow ? {
            ...m, flow: { ...m.flow, autoResults: [...m.flow.autoResults, ev.result ?? ''] },
          } : m))
        } else if (ev.type === 'flow_complete') {
          patchLast((m) => m.flow ? {
            ...m,
            flow: { ...m.flow, status: 'done', card: null, statusText: ev.text },
          } : m)
        } else if (ev.type === 'done' && ev.flow_display
                   && ev.flow_display.status !== 'running'
                   && (ev.flow_display.sections || []).length) {
          // 完成/取消：切换为"最后一态的表单数据"（服务端紧凑三段式，全脱敏）
          const fd = ev.flow_display
          patchLast((m) => m.flow ? {
            ...m,
            flow: {
              ...m.flow,
              sections: fd.sections as FlowSection[],
              status: fd.status === 'cancelled' ? 'cancelled'
                : fd.status === 'done' ? 'done' : m.flow.status,
              autoResults: [],
              readonly: true,
            },
          } : m)
        } else if (ev.type === 'flow_cancelled') {
          patchLast((m) => m.flow ? {
            ...m,
            flow: { ...m.flow, status: 'cancelled', card: null, statusText: ev.text },
          } : m)
        } else if (ev.type === 'done') {
          patchLast((m) => ({ ...m, status: 'done' }))
        }
      })
    } catch (e) {
      setGateHint(errMsg(e, '流程提交失败'))
    } finally {
      setStreaming(false)
    }
  }

  const cancelFlow = async (instanceId: number) => {
    if (streaming) return
    if (!confirm('确定取消当前业务办理？取消后可继续提问。')) return
    setStreaming(true)
    try {
      await sse('/flow/cancel', { instance_id: instanceId }, (ev) => {
        if (ev.type === 'flow_cancelled') {
          patchLast((m) => m.flow ? {
            ...m,
            flow: { ...m.flow, status: 'cancelled', card: null, statusText: ev.text },
          } : m)
        } else if (ev.type === 'done' && ev.flow_display
                   && ev.flow_display.status !== 'running'
                   && (ev.flow_display.sections || []).length) {
          const fd = ev.flow_display
          patchLast((m) => m.flow ? {
            ...m,
            flow: {
              ...m.flow,
              sections: fd.sections as FlowSection[],
              status: 'cancelled', autoResults: [], card: null, readonly: true,
            },
          } : m)
        }
      })
    } finally {
      setStreaming(false)
      loadConversations()
    }
  }

  const u = auth.user

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-white">🏛️</div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-800">AI 智能客服</p>
            <p className="truncate text-[10px] text-slate-400">{u ? `${u.nick_name} · ${u.dept_name}` : ''}</p>
          </div>
        </div>
        <div className="px-3">
          <Button className="w-full" onClick={newConversation}>＋ 新会话</Button>
        </div>
        <div className="mt-3 flex-1 space-y-0.5 overflow-auto px-2 pb-3">
          {conversations.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-slate-300">暂无历史会话</p>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={cn(
                'group flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-2 text-xs hover:bg-slate-100',
                conversationId === c.id && 'bg-brand/10 text-brand-dark hover:bg-brand/10',
              )}
              onClick={() => loadConversation(c.id)}
            >
              <span className="shrink-0 opacity-60">💬</span>
              <span className="min-w-0 flex-1 truncate">{c.title}</span>
              <button
                className="hidden shrink-0 text-slate-300 hover:text-red-400 group-hover:block"
                onClick={(e) => {
                  e.stopPropagation()
                  removeConversation(c.id)
                }}
              >
                🗑
              </button>
            </div>
          ))}
        </div>
        <div className="border-t border-slate-100 p-3">
          {auth.roles.includes('admin') || auth.roles.includes('manager') ? (
            <Button variant="outline" size="sm" className="w-full"
              onClick={() => (window.location.href = '/manager')}>
              ⚙️ 管理后台
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" className="mt-1 w-full text-slate-400"
            onClick={() => dispatch(logout())}>
            退出登录
          </Button>
        </div>
      </aside>

      <main className="relative flex min-w-0 flex-1 flex-col bg-slate-50">
        <HandoffButton conversationId={conversationId} />
        <div className="border-b border-slate-200 bg-white/80 px-6 py-3 backdrop-blur">
          <p className="text-sm font-medium text-slate-700">
            公积金智能问答
            <span className="ml-2 text-xs font-normal text-slate-400">
              LangGraph Agentic RAG · 流程阶段全程可见
            </span>
          </p>
        </div>

        <div className="flex-1 overflow-auto px-6 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.length === 0 && <Welcome onAsk={(q) => send(q)} />}
            {messages.map((m, i) => (
              <TurnBlock
                key={i}
                msg={m}
                onStartFlow={startFlow}
                onSubmitFlow={submitFlow}
                onCancelFlow={cancelFlow}
                onAsk={(q) => send(q)}
                busy={streaming}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* 流程门控横幅：办理中禁止提问 */}
        {runningFlow && (
          <div className="border-t border-amber-200 bg-amber-50 px-6 py-2.5">
            <div className="mx-auto flex max-w-3xl items-center gap-2 text-xs text-amber-700">
              <span>📋</span>
              <span>
                正在办理「{runningFlow.flowName}」——流程办理期间问答已暂停，请完成当前步骤或
              </span>
              <button
                className="rounded-md border border-amber-300 bg-white px-2 py-0.5 text-amber-700 hover:bg-amber-100"
                onClick={() => runningFlow && cancelFlow(runningFlow.instanceId)}
              >
                取消流程
              </button>
            </div>
          </div>
        )}

        <div className="border-t border-slate-200 bg-white px-6 py-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea
              className={cn(
                'max-h-32 min-h-[44px] flex-1 resize-none rounded-xl border px-4 py-2.5 text-sm shadow-sm outline-none focus:ring-2 focus:ring-brand/30',
                runningFlow ? 'cursor-not-allowed border-amber-200 bg-amber-50/50' : 'border-slate-200',
              )}
              placeholder={runningFlow ? '流程办理中，完成或取消流程后可继续提问…' : '输入公积金相关问题，Enter 发送（Shift+Enter 换行）'}
              value={input}
              rows={1}
              disabled={!!runningFlow}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(input)
                }
              }}
            />
            {streaming ? (
              <Button variant="destructive" className="h-[44px] rounded-xl px-5" onClick={stop}>
                ■ 停止
              </Button>
            ) : (
              <Button className="h-[44px] rounded-xl px-5" disabled={!input.trim() || !!runningFlow}
                onClick={() => send(input)}>
                发送 ↑
              </Button>
            )}
          </div>
          {gateHint && <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-amber-600">{gateHint}</p>}
          <p className="mx-auto mt-2 max-w-3xl text-center text-[10px] text-slate-300">
            回答由大模型基于知识库生成，政策口径以当地公积金中心公告为准
          </p>
        </div>
      </main>
    </div>
  )
}

/** 转人工入口（右下角浮动）：登记转接请求并给出坐席/热线提示。 */
function HandoffButton({ conversationId }: { conversationId: number | null }) {
  const [open, setOpen] = useState(false)
  const [sent, setSent] = useState('')
  const [reason, setReason] = useState('')

  const submit = async () => {
    try {
      const r = await post<{ text: string }>('/chat/handoff', {
        conversation_id: conversationId, reason,
      })
      setSent(r.text)
    } catch {
      setSent('提交失败，请直接拨打 12329 服务热线。')
    }
  }

  return (
    <>
      <button
        className="absolute bottom-24 right-6 z-40 flex items-center gap-1.5 rounded-full bg-white px-3.5 py-2 text-xs font-medium text-slate-600 shadow-lg ring-1 ring-slate-200 transition-all hover:text-brand-dark hover:ring-brand/40"
        onClick={() => setOpen(true)}
      >
        🎧 转人工
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => { setOpen(false); setSent('') }}>
          <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-slate-800">🎧 转接人工坐席</h3>
            {sent ? (
              <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2.5 text-xs leading-5 text-emerald-700">{sent}</p>
            ) : (
              <>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  在线坐席服务时间 9:00-17:00；也可直接拨打服务热线 <b>12329</b>。
                </p>
                <input
                  className="mt-3 h-9 w-full rounded-md border border-slate-200 px-3 text-sm"
                  placeholder="简要描述您的问题（可选）"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => { setOpen(false); setSent('') }}>
                {sent ? '关闭' : '取消'}
              </Button>
              {!sent && <Button size="sm" onClick={submit}>提交转接请求</Button>}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Welcome({ onAsk }: { onAsk: (q: string) => void }) {
  const samples = [
    '福州公积金贷款最高能贷多少？',
    '我在冲还贷，想做装修提取需要先停冲吗？',
    '帮我查一下我的公积金账户余额',
    '我要办理租房提取',
  ]
  return (
    <div className="py-10 text-center">
      <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-3xl bg-brand text-3xl shadow-xl shadow-brand/20">
        🏛️
      </div>
      <h2 className="text-lg font-semibold text-slate-800">您好，我是公积金智能客服「小金」</h2>
      <p className="mt-1.5 text-xs text-slate-400">政策知识问答 · 个人业务办理 · 全省跨机构服务</p>
      <div className="mx-auto mt-6 grid max-w-xl grid-cols-2 gap-2.5">
        {samples.map((q) => (
          <button
            key={q}
            className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-left text-xs text-slate-600 shadow-sm transition-all hover:border-brand/40 hover:text-brand-dark"
            onClick={() => onAsk(q)}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

function TurnBlock({
  msg, onStartFlow, onSubmitFlow, onCancelFlow, onAsk, busy,
}: {
  msg: TurnMsg
  onStartFlow: (key: string, name: string) => void
  onSubmitFlow: (instanceId: number, nodeKey: string, data: Record<string, unknown>) => void
  onCancelFlow: (instanceId: number) => void
  onAsk: (q: string) => void
  busy: boolean
}) {
  return (
    <div className="space-y-4">
      {msg.question && (
        <div className="flex justify-end">
          <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm text-white shadow-sm">
            {msg.question}
          </div>
        </div>
      )}

      <div className="space-y-3">
        {(msg.stages.length > 0 || (msg.status === 'streaming' && !msg.flow)) && <StageFlow msg={msg} />}

        {/* 流程卡片（业务办理） */}
        {msg.flow && (
          <FlowCardView flow={msg.flow} busy={busy} onSubmit={onSubmitFlow} onCancel={onCancelFlow} />
        )}

        {msg.tools.map((t, i) => (
          <ToolCard key={i} tool={t} />
        ))}

        {(msg.answer || (msg.status === 'streaming' && !msg.flow)) && (
          <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white px-5 py-4 shadow-sm">
            {msg.answer ? (
              <div className="md-body" dangerouslySetInnerHTML={{ __html: renderMd(msg.answer) }} />
            ) : (
              <span className="inline-flex gap-1">
                <Dot delay="0ms" /><Dot delay="150ms" /><Dot delay="300ms" />
              </span>
            )}
            {msg.status === 'stopped' && <p className="mt-2 text-[10px] text-slate-400">— 回答已停止 —</p>}
          </div>
        )}

        {/* 回答反馈：点赞/差评 + 修改意见（进入管理端 RAG 审计差评口径） */}
        {msg.id != null && msg.status === 'done' && msg.answer && (
          <FeedbackBar turnId={msg.id} initial={msg.feedback} />
        )}

        {/* 办理推荐：简单业务 → 流程引擎嵌入会话；复杂业务 → 跳转业务页面 */}
        {msg.flows && msg.flows.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-medium text-slate-400">🖱 相关业务办理</p>
            <div className="flex flex-wrap gap-2">
              {msg.flows.map((f) =>
                f.mode === 'redirect' ? (
                  <button
                    key={f.flow_key}
                    className="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100"
                    title={f.url}
                    onClick={() => f.url && window.open(f.url, '_blank')}
                  >
                    🔗 {f.name} <span className="text-[10px] font-normal opacity-70">（跳转业务系统）</span>
                  </button>
                ) : (
                  <button
                    key={f.flow_key}
                    disabled={busy}
                    className="rounded-lg border border-brand/30 bg-brand/5 px-3 py-1.5 text-xs font-medium text-brand-dark transition-colors hover:bg-brand/10 disabled:opacity-50"
                    onClick={() => onStartFlow(f.flow_key, f.name)}
                  >
                    ▶ {f.name} <span className="text-[10px] font-normal opacity-70">（在线办理）</span>
                  </button>
                ),
              )}
            </div>
          </div>
        )}

        {/* 引用来源（混合展示：知识库点开查看内容 / 联网跳转原文；显示机构名称） */}
        {msg.sources && msg.sources.length > 0 && (
          <SourceList sources={msg.sources} />
        )}

        {/* 可能相关问题推荐（点击即追问） */}
        {msg.questions && msg.questions.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-medium text-slate-400">💡 您可能还想问</p>
            <div className="flex flex-wrap gap-2">
              {msg.questions.map((q, i) => (
                <button
                  key={i}
                  disabled={busy}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 shadow-sm transition-colors hover:border-brand/40 hover:text-brand-dark disabled:opacity-50"
                  onClick={() => onAsk(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/** 流程卡片表单值：字段值（fields）+ 已传文件（files）+ 上传错误提示。 */
interface FlowCardValues {
  fields: Record<string, string | number>
  files?: Record<string, { filename: string; size: number } | undefined>
  _uploadError?: string
}

/** 流程卡片：form 表单 / confirm 确认 / 完成态。 */
function FlowCardView({
  flow, busy, onSubmit, onCancel,
}: {
  flow: FlowUI
  busy: boolean
  onSubmit: (instanceId: number, nodeKey: string, data: Record<string, unknown>) => void
  onCancel: (instanceId: number) => void
}) {
  const [values, setValues] = useState<FlowCardValues>({ fields: {} })
  const card = flow.card
  const errors = flow.errors || {}
  const readonly = !!flow.readonly
  const sections: FlowSection[] = flow.sections || []

  useEffect(() => {
    // 历史/错误回显：优先展示后端返回的已提交值；切换节点时清空
    setValues(flow.filled && flow.card ? { fields: { ...flow.filled } } : { fields: {} })
  }, [card?.node_key, flow.filled])

  const tone = flow.status === 'running' ? 'brand' : flow.status === 'done' ? 'emerald' : 'slate'
  const toneCls: Record<string, string> = {
    brand: 'border-brand/30 bg-brand/[0.03]',
    emerald: 'border-emerald-200 bg-emerald-50/50',
    slate: 'border-slate-200 bg-slate-50/50',
  }

  return (
    <div className={cn('overflow-hidden rounded-xl border', toneCls[tone])}>
      <div className="flex items-center gap-2 px-4 py-2.5">
        <span>📋</span>
        <span className="text-xs font-semibold text-slate-700">{flow.flowName}</span>
        {card?.progress && <Badge tone="blue">步骤 {card.progress}</Badge>}
        <span className="ml-auto text-[10px] text-slate-400">
          {flow.status === 'running' && !readonly
            ? '办理中 · 问答已暂停'
            : flow.status === 'cancelled'
              ? '已取消'
              : '已完成'}
        </span>
      </div>

      {/* 历史还原：按"原始表单形态"逐节点渲染（表单字段/确认摘要/核验结果/完成文案） */}
      {sections.length > 0 && (
        <div className="space-y-3 border-t border-slate-100 px-4 py-3">
          {sections.map((sec, i) => (
            <div key={i}>
              {sec.type === 'form' && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-600">{sec.title}</p>
                  {(sec.fields || []).map((f) => (
                    <div key={f.name} className="flex items-baseline gap-2 text-xs">
                      <span className="w-36 shrink-0 text-slate-400">{f.label}</span>
                      <span className={cn('break-all', f.error ? 'text-red-500' : 'text-slate-700')}>
                        {f.value || '—'}
                      </span>
                    </div>
                  ))}
                  {(sec.fields || []).some((f) => f.error) && (
                    <div className="rounded-md bg-red-50 px-2.5 py-1.5">
                      {(sec.fields || []).filter((f) => f.error).map((f) => (
                        <p key={f.name} className="text-[11px] leading-4 text-red-500">⚠️ {f.error}</p>
                      ))}
                    </div>
                  )}
                  {(sec.prior_notes || []).length > 0 && (
                    <div className="rounded-md bg-amber-50 px-2.5 py-1.5">
                      <p className="text-[10px] leading-4 text-amber-600">
                        此前 {sec.attempts ? sec.attempts - 1 : 1} 次提交未通过校验（已修正）：
                        {(sec.prior_notes || []).join('；')}
                      </p>
                    </div>
                  )}
                </div>
              )}
              {sec.type === 'confirm' && (
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-600">{sec.title}</p>
                  <pre className="whitespace-pre-wrap rounded-lg bg-white p-2.5 font-sans text-xs leading-5 text-slate-600">
                    {sec.summary}
                  </pre>
                </div>
              )}
              {sec.type === 'auto' && (
                <div>
                  <p className="mb-0.5 text-[10px] font-medium text-slate-400">⚙️ {sec.title}</p>
                  <pre className="whitespace-pre-wrap font-mono text-[10px] leading-4 text-slate-500">{sec.result || '—'}</pre>
                </div>
              )}
              {sec.type === 'form_summary' && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-600">{sec.title || '办理信息'}</p>
                  <div className="rounded-lg bg-white px-3 py-2">
                    {(sec.fields || []).map((f, j) => (
                      <div key={j} className="flex items-baseline gap-2 py-0.5 text-xs">
                        <span className="w-32 shrink-0 text-slate-400">{f.label}</span>
                        <span className="break-all text-slate-700">{f.value || '—'}</span>
                      </div>
                    ))}
                    {(sec.fields || []).length === 0 && (
                      <p className="text-xs text-slate-400">（暂无表单数据）</p>
                    )}
                  </div>
                </div>
              )}
              {sec.type === 'note' && (
                <p className="rounded-md bg-amber-50 px-2.5 py-1.5 text-[11px] leading-4 text-amber-600">
                  ⚠️ {sec.text}
                </p>
              )}
              {sec.type === 'result' && (
                <p className={cn(
                  'whitespace-pre-wrap rounded-lg px-3 py-2 text-xs leading-5',
                  flow.status === 'cancelled' ? 'bg-slate-100 text-slate-500' : 'bg-emerald-50 text-emerald-700',
                )}>
                  {sec.text}
                </p>
              )}
              {sec.type === 'end' && sec.text && (
                <p className="rounded-lg bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-700">{sec.text}</p>
              )}
              {sec.type === 'cancelled' && (
                <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs leading-5 text-slate-500">{sec.text}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {card && flow.status === 'running' && !readonly && (
        <div className="border-t border-slate-100 px-4 py-3">
          <p className="mb-2 text-xs font-medium text-slate-600">{card.title}</p>

          {card.node_type === 'form' && (
            <div className="space-y-2.5">
                {(card.fields || []).map((f) => (
                  <div key={f.name}>
                    <label className="mb-1 block text-[11px] text-slate-500">
                      {f.label} {f.required && <span className="text-red-400">*</span>}
                    </label>
                    {f.type === 'select' ? (
                      <select
                        className={cn(
                          'h-9 w-full rounded-md border bg-white px-2 text-sm',
                          errors[f.name] ? 'border-red-300 ring-1 ring-red-200' : 'border-slate-200',
                        )}
                        value={values.fields[f.name] ?? ''}
                        onChange={(e) => setValues({ ...values, fields: { ...values.fields, [f.name]: e.target.value } })}
                      >
                        <option value="">请选择</option>
                        {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input
                        className={cn(
                          'h-9 w-full rounded-md border bg-white px-3 text-sm',
                          errors[f.name] ? 'border-red-300 ring-1 ring-red-200' : 'border-slate-200',
                        )}
                        type={f.type === 'number' ? 'number' : 'text'}
                        placeholder={f.placeholder || ''}
                        value={values.fields[f.name] ?? ''}
                        onChange={(e) => setValues({ ...values, fields: { ...values.fields, [f.name]: e.target.value } })}
                      />
                    )}
                    {errors[f.name] && (
                      <p className="mt-1 flex items-start gap-1 text-[11px] leading-4 text-red-500">
                        <span>⚠️</span>
                        {errors[f.name]}
                      </p>
                    )}
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    disabled={busy || (card.fields || []).some((f) => f.required && !String(values.fields[f.name] ?? '').trim())}
                    onClick={() => onSubmit(flow.instanceId, card.node_key, values.fields)}
                  >
                    下一步 →
                  </Button>
                  <button
                    className="text-[11px] text-slate-400 hover:text-red-400"
                    disabled={busy}
                    onClick={() => onCancel(flow.instanceId)}
                  >
                    取消流程
                  </button>
                </div>
              </div>
          )}

          {card.node_type === 'upload' && (
            <div className="space-y-2.5">
              {(card.files || []).map((f) => {
                const got = (values.files || {})[f.name] || f.uploaded
                return (
                  <div key={f.name}>
                    <label className="mb-1 block text-[11px] text-slate-500">
                      {f.label} {f.required && <span className="text-red-400">*</span>}
                    </label>
                    {got ? (
                      <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-700">
                        <span>✅</span>
                        <span className="break-all">{got.filename}</span>
                        <span className="text-slate-400">（{Math.max(1, Math.round(got.size / 1024))}KB）</span>
                        <button
                          className="ml-auto text-[11px] text-slate-400 hover:text-red-400"
                          onClick={() => setValues({ ...values, files: { ...(values.files || {}), [f.name]: undefined } })}
                        >移除</button>
                      </div>
                    ) : (
                      <label className={cn(
                        'flex h-9 cursor-pointer items-center justify-center rounded-md border border-dashed text-xs',
                        errors[f.name] ? 'border-red-300 bg-red-50/40 text-red-400' : 'border-slate-300 text-slate-500 hover:border-brand/50 hover:text-brand',
                      )}>
                        <input
                          type="file" className="hidden" accept={f.accept || 'image/*,application/pdf'}
                          onChange={async (e) => {
                            const file = e.target.files?.[0]
                            e.target.value = ''
                            if (!file) return
                            try {
                              const r = await uploadFlowFile(flow.instanceId, f.name, file)
                              setValues({ ...values, files: { ...(values.files || {}), [f.name]: { filename: r.filename, size: r.size } } })
                            } catch (err) {
                              setValues({ ...values, _uploadError: errMsg(err, '上传失败') })
                            }
                          }}
                        />
                        📎 点击选择文件（jpg / png / pdf，≤10MB）
                      </label>
                    )}
                    {errors[f.name] && (
                      <p className="mt-1 flex items-start gap-1 text-[11px] leading-4 text-red-500">
                        <span>⚠️</span>{errors[f.name]}
                      </p>
                    )}
                  </div>
                )
              })}
              {values._uploadError && (
                <p className="text-[11px] text-red-500">⚠️ {values._uploadError}</p>
              )}
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  disabled={busy || (card.files || []).some((f) => f.required && !((values.files || {})[f.name] || f.uploaded))}
                  onClick={() => onSubmit(flow.instanceId, card.node_key, {
                    files: Object.fromEntries(
                      (card.files || [])
                        .map((f) => [f.name, (values.files || {})[f.name] || f.uploaded])
                        .filter(([, v]) => !!v),
                    ),
                  })}
                >
                  下一步 →
                </Button>
                <button
                  className="text-[11px] text-slate-400 hover:text-red-400"
                  disabled={busy}
                  onClick={() => onCancel(flow.instanceId)}
                >
                  取消流程
                </button>
              </div>
            </div>
          )}

          {card.node_type === 'confirm' && (
            <div className="space-y-3">
              <pre className="whitespace-pre-wrap rounded-lg bg-white p-3 font-sans text-xs leading-5 text-slate-600">
                {card.summary}
              </pre>
              {!readonly && (
                <div className="flex gap-2">
                  <Button size="sm" disabled={busy} onClick={() => onSubmit(flow.instanceId, card.node_key, { agree: true })}>
                    ✅ 确认提交
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => onSubmit(flow.instanceId, card.node_key, { agree: false })}>
                    放弃办理
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!readonly && flow.autoResults.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-2.5">
          <p className="mb-1 text-[10px] font-medium text-slate-400">⚙️ 业务系统自动校验</p>
          {flow.autoResults.map((r, i) => (
            <pre key={i} className="whitespace-pre-wrap font-mono text-[10px] leading-4 text-slate-500">{r}</pre>
          ))}
        </div>
      )}

      {/* 流程状态文案（发起/校验失败/完成/取消）——只在卡片内展示，不落对话流；
         已有"结果行"（最终表单视图）时不再重复 */}
      {flow.statusText && !sections.some((x) => x.type === 'result') && (
        <div className={cn(
          'border-t px-4 py-2.5 text-xs leading-5',
          flow.status === 'done'
            ? 'border-emerald-100 bg-emerald-50/60 text-emerald-700'
            : flow.status === 'cancelled'
              ? 'border-slate-100 bg-slate-50 text-slate-500'
              : 'border-brand/20 bg-brand/[0.03] text-slate-600',
        )}>
          {flow.statusText}
        </div>
      )}
    </div>
  )
}

/** 引用来源列表：混合展示知识库与联网来源，均可点击查看。 */
function SourceList({ sources }: { sources: SourceItem[] }) {
  const [viewing, setViewing] = useState<SourceItem | null>(null)
  const kb = sources.filter((s) => s.source !== 'web')
  const web = sources.filter((s) => s.source === 'web')

  const chip = (s: SourceItem, i: number) =>
    s.source === 'web' ? (
      <a
        key={`w${i}`}
        href={s.url || '#'}
        target="_blank"
        rel="noreferrer"
        title={`联网来源：${s.url}
搜索引擎：${s.engine || '—'}`}
        className="inline-flex max-w-[300px] items-center gap-1 rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-medium text-sky-600 hover:bg-sky-100"
      >
        🌐 <span className="truncate">{s.title}</span>
        <span className="shrink-0 text-[9px] opacity-60">联网</span>
      </a>
    ) : (
      <button
        key={`k${i}`}
        title="查看知识库原文"
        className="inline-flex max-w-[300px] items-center gap-1 rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-600 hover:bg-violet-100"
        onClick={() => setViewing(s)}
      >
        📖 <span className="truncate">{s.title}</span>
        {s.dept_name && <span className="shrink-0 text-[9px] opacity-70">{s.dept_name}</span>}
        {s.rerank_score != null && (
          <span className="shrink-0 text-[9px] opacity-60">{s.rerank_score.toFixed(2)}</span>
        )}
      </button>
    )

  return (
    <div className="space-y-1">
      <p className="text-[10px] font-medium text-slate-400">
        📎 引用来源
        {web.length > 0 && kb.length > 0 && (
          <span className="ml-1 text-sky-500">（知识库 {kb.length} 条 + 联网 {web.length} 条）</span>
        )}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {web.map((s, i) => chip(s, i))}
        {kb.map((s, i) => chip(s, i))}
      </div>

      {/* 知识库知识查看弹层 */}
      {viewing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setViewing(null)}
        >
          <div
            className="max-h-[70vh] w-full max-w-xl overflow-auto rounded-xl bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold text-slate-800">{viewing.title}</h3>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {viewing.dept_name || '知识库'}
                  {viewing.rerank_score != null && ` · 相关性 ${viewing.rerank_score.toFixed(2)}`}
                </p>
              </div>
              <button className="text-slate-400 hover:text-slate-600" onClick={() => setViewing(null)}>
                ✕
              </button>
            </div>
            <pre className="whitespace-pre-wrap px-5 py-4 font-sans text-xs leading-6 text-slate-600">
              {viewing.text || '（该来源未附带正文，可在管理端知识库查看）'}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-brand/60"
      style={{ animationDelay: delay }}
    />
  )
}

/** 回答反馈条：👍 立即提交；👎 展开修改意见输入后提交；重评覆盖，历史还原已反馈态。 */
function FeedbackBar({ turnId, initial }: {
  turnId: number
  initial?: { rating: 'up' | 'down'; comment?: string }
}) {
  const [rating, setRating] = useState<'up' | 'down' | ''>(initial?.rating || '')
  const [comment, setComment] = useState(initial?.comment || '')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (r: 'up' | 'down', withComment: boolean) => {
    setBusy(true)
    try {
      await post('/chat/feedback', {
        turn_id: turnId, rating: r,
        comment: withComment ? comment : (rating === r ? comment : ''),
      })
      setRating(r)
      setEditing(false)
    } catch {
      /* 静默：反馈失败不打断对话 */
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
      <button
        className={cn('rounded-full px-2.5 py-1 transition-colors',
          rating === 'up' ? 'bg-emerald-50 text-emerald-600' : 'hover:bg-slate-100 hover:text-slate-600')}
        disabled={busy}
        onClick={() => submit('up', false)}
        title="回答有帮助"
      >
        👍 有帮助
      </button>
      <button
        className={cn('rounded-full px-2.5 py-1 transition-colors',
          rating === 'down' ? 'bg-rose-50 text-rose-500' : 'hover:bg-slate-100 hover:text-slate-600')}
        disabled={busy}
        onClick={() => setEditing(editing ? false : true)}
        title="回答有问题，提交修改意见"
      >
        👎 待改进
      </button>
      {rating && !editing && <span className="text-[10px]">已反馈，可点击修改</span>}
      {editing && (
        <span className="flex w-full flex-wrap items-center gap-2">
          <input
            className="h-8 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-3 text-xs shadow-sm outline-none focus:ring-2 focus:ring-brand/30"
            placeholder="修改意见（哪里不对/应补充什么，选填）…"
            value={comment}
            maxLength={500}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit('down', true) }}
          />
          <Button size="sm" disabled={busy} onClick={() => submit('down', true)}>
            {busy ? '提交中…' : '提交差评'}
          </Button>
          <button className="text-[11px] text-slate-300 hover:text-slate-500" onClick={() => setEditing(false)}>
            取消
          </button>
        </span>
      )}
    </div>
  )
}

function ToolCard({ tool }: { tool: ToolCall }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="overflow-hidden rounded-xl border border-amber-200 bg-amber-50/50">
      <div className="flex items-center gap-2 px-3.5 py-2">
        <span className="text-sm">🔧</span>
        <span className="font-mono text-xs font-semibold text-amber-700">{tool.name}</span>
        <Badge tone="amber" className="font-mono !text-[9px]">MCP</Badge>
        <span className="ml-auto text-[10px] text-slate-400">
          {tool.result ? '已完成' : '执行中…'}
        </span>
        <button className="text-[10px] text-slate-400 hover:text-slate-600" onClick={() => setOpen(!open)}>
          {open ? '收起' : '展开'}
        </button>
      </div>
      <div className="border-t border-amber-100 px-3.5 py-2">
        <p className="font-mono text-[10px] leading-4 text-slate-500">
          {Object.entries(tool.arguments || {}).map(([k, v]) => (
            <span key={k} className="mr-3">
              <span className="text-amber-600">{k}</span>=
              <span className="text-slate-600">{String(v)}</span>
            </span>
          ))}
        </p>
        {open && tool.result && (
          <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-white/70 p-2.5 font-mono text-[10px] leading-4 text-slate-600">
            {tool.result}
          </pre>
        )}
      </div>
    </div>
  )
}
