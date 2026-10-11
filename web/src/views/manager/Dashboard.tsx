import { useEffect, useState } from 'react'
import { get } from '../../lib/api'
import type { DashboardData } from '../../types/api'
import { Card, CardHeader, Badge } from '../../components/ui'
import type { BadgeTone } from '../../components/ui'

export default function Dashboard() {
  const [d, setD] = useState<DashboardData | null>(null)

  useEffect(() => {
    get<DashboardData>('/audit/dashboard').then(setD).catch(() => {})
    const t = setInterval(() => get<DashboardData>('/audit/dashboard').then(setD).catch(() => {}), 15000)
    return () => clearInterval(t)
  }, [])

  if (!d) return <p className="text-sm text-slate-400">加载中…</p>

  const cards = [
    { label: '会话数', value: d.conversation_count, unit: '个' },
    { label: '问答轮次', value: d.turn_count, unit: '轮' },
    { label: 'Token 消耗(入)', value: d.tokens_in.toLocaleString(), unit: 'tok' },
    { label: 'Token 消耗(出)', value: d.tokens_out.toLocaleString(), unit: 'tok' },
    { label: '平均首字延迟', value: d.avg_ttft_ms, unit: 'ms' },
    { label: '平均整轮耗时', value: d.avg_total_ms, unit: 'ms' },
    { label: '今日成本', value: `¥${d.cost_today.toFixed(4)}`, unit: '元' },
    { label: '累计成本', value: `¥${d.cost_total.toFixed(4)}`, unit: '元' },
    { label: '入库成本(今日)', value: `¥${d.ingest_cost_today.toFixed(4)}`, unit: '元' },
    { label: '入库成本(累计)', value: `¥${d.ingest_cost_total.toFixed(4)}`, unit: '元' },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">运营仪表盘</h1>
        <p className="mt-0.5 text-xs text-slate-400">对话/轮次/token/耗时/成本——轮次审计流水实时汇总（15s 自动刷新）</p>
      </div>

      <div className="grid grid-cols-4 gap-4 xl:grid-cols-8">
        {cards.map((c) => (
          <Card key={c.label} className="p-4">
            <p className="text-[11px] text-slate-400">{c.label}</p>
            <p className="mt-1.5 font-mono text-xl font-semibold text-slate-800">
              {typeof c.value === 'number' ? c.value.toLocaleString() : c.value}
              <span className="ml-1 text-[10px] font-normal text-slate-300">{c.unit}</span>
            </p>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <DistCard title="意图分布" dist={d.intent_dist} tones={['blue', 'violet', 'green', 'amber', 'slate']} />
        <DistCard title="主题分布" dist={d.theme_dist} tones={['amber', 'blue', 'green', 'slate']} />
      </div>

      {Object.keys(d.daily || {}).length > 0 && (
        <Card>
          <CardHeader title="今日轮次" desc="按小时统计" />
          <div className="flex h-32 items-end gap-2 px-5 py-4">
            {Object.entries(d.daily).map(([h, n]) => {
              const max = Math.max(...Object.values<number>(d.daily))
              return (
                <div key={h} className="flex flex-1 flex-col items-center gap-1">
                  <div
                    className="w-full max-w-10 rounded-t-md bg-brand/70 transition-all hover:bg-brand"
                    style={{ height: `${Math.max((Number(n) / max) * 100, 6)}%` }}
                    title={`${n} 轮`}
                  />
                  <span className="text-[9px] text-slate-400">{h}</span>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}

/** 分布卡：数据来自后端单一中文标签源（[{code,label,count}]，按 count 降序）。 */
function DistCard({
  title, dist, tones,
}: {
  title: string
  dist: { code: string; label: string; count: number }[]
  tones: BadgeTone[]
}) {
  const total = (dist || []).reduce((s, e) => s + e.count, 0) || 1
  return (
    <Card>
      <CardHeader title={title} desc={`共 ${total} 轮`} />
      <div className="space-y-3 px-5 py-4">
        {(!dist || dist.length === 0) && <p className="text-xs text-slate-300">暂无数据</p>}
        {dist?.map((e, i) => (
          <div key={e.code}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <Badge tone={tones[i % tones.length] || 'slate'}>{e.label || e.code}</Badge>
              <span className="font-mono text-slate-400">
                {e.count} · {((e.count / total) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-brand/60"
                style={{ width: `${(e.count / total) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}
