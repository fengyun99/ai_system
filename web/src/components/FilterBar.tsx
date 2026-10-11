import { useEffect, useRef, useState } from 'react'
import { Button, cn } from './ui'

export interface FilterItem {
  label: string
  node: React.ReactNode
  value?: string | boolean          // 当前值（折叠区已选条件的角标计数）
}

const active = (v: string | boolean | undefined) =>
  typeof v === 'boolean' ? v : !!v

/** 过滤区通用布局：紧凑流式排布（控件按内容取宽，下拉框上限≈20 个汉字），
 *  默认最多展示两行，超出折叠——按控件真实行数测量（offsetTop 分组），
 *  末位固定放 查询 + 更多筛选（隐藏区有已选值时显示角标计数）。
 *  页面级动作（导出等）放各自标题行右侧，不占过滤区预算。 */
export default function FilterBar({ items, onQuery, className }: {
  items: FilterItem[]
  onQuery: () => void
  className?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const [overflowable, setOverflowable] = useState(false)
  const [hiddenActive, setHiddenActive] = useState(0)
  const boxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const measure = () => {
      // 子元素按 top 坐标分组即真实行数；max-height 截断不改变流式布局，两种状态都可测
      const kids = Array.from(el.children) as HTMLElement[]
      const tops = kids.map((k) => k.offsetTop)
      const rows = [...new Set(tops)]
      setOverflowable(rows.length > 2)
      if (rows.length > 2) {
        const cut = rows[2]      // 第三行起的元素被折叠隐藏
        const hiddenIdx = tops.map((t, i) => [t, i] as const)
          .filter(([t]) => t >= cut).map(([, i]) => i)
          .filter((i) => i < items.length)
        setHiddenActive(hiddenIdx.filter((i) => active(items[i]?.value)).length)
      } else {
        setHiddenActive(0)
      }
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  })            // 每次渲染后重测（items 每页为字面量数组，无稳定引用可用）

  return (
    <div
      ref={boxRef}
      className={cn(
        'flex flex-wrap items-end gap-x-3 gap-y-2.5',
        '[&_select]:min-w-[6.5rem] [&_select]:max-w-[20rem]',   // 下拉框按内容取宽，上限≈20 个汉字
        !expanded && 'max-h-32 overflow-hidden',                 // 折叠态：两行（128px）截断
        className,
      )}
    >
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <label className="mb-1 block text-[11px] font-medium text-slate-400">{it.label}</label>
          {it.node}
        </div>
      ))}
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={onQuery}>查询</Button>
        {overflowable && (
          <button
            className="whitespace-nowrap text-xs text-slate-400 transition-colors hover:text-brand"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? '收起 ▴' : `更多筛选${hiddenActive ? ` ·${hiddenActive}` : ''} ▾`}
          </button>
        )}
      </div>
    </div>
  )
}
