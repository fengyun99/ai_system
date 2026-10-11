import { clsx } from 'clsx'
import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from 'react'

export const cn = (...args: Parameters<typeof clsx>) => clsx(...args)

/* ---------------- shadcn/ui 风格基础组件（Tailwind 手写实现） ---------------- */

export function Button({
  className,
  variant = 'default',
  size = 'default',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'outline' | 'ghost' | 'destructive' | 'secondary'
  size?: 'default' | 'sm' | 'icon'
}) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 disabled:pointer-events-none disabled:opacity-50',
        variant === 'default' && 'bg-brand text-white hover:bg-brand-dark',
        variant === 'secondary' && 'bg-slate-100 text-slate-900 hover:bg-slate-200',
        variant === 'outline' && 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50',
        variant === 'ghost' && 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
        variant === 'destructive' && 'bg-red-500 text-white hover:bg-red-600',
        size === 'default' && 'h-9 px-4 py-2',
        size === 'sm' && 'h-8 px-3 text-xs',
        size === 'icon' && 'h-9 w-9',
        className,
      )}
      {...props}
    />
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn('rounded-lg border border-slate-200 bg-white shadow-sm', className)}>
      {children}
    </div>
  )
}

export function CardHeader({ title, desc, action }: { title: ReactNode; desc?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between border-b border-slate-100 px-5 py-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
        {desc && <p className="mt-0.5 text-xs text-slate-400">{desc}</p>}
      </div>
      {action}
    </div>
  )
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'flex h-9 w-full rounded-md border border-slate-200 bg-white px-3 py-1 text-sm shadow-sm transition-colors',
        'placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40',
        className,
      )}
      {...props}
    />
  )
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-sm shadow-sm',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'flex w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm',
        'placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40',
        className,
      )}
      {...props}
    />
  )
}

export type BadgeTone = 'slate' | 'green' | 'blue' | 'amber' | 'red' | 'violet'

export function Badge({
  className,
  tone = 'slate',
  children,
}: {
  className?: string
  tone?: BadgeTone
  children: ReactNode
}) {
  const tones: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-600',
    green: 'bg-emerald-50 text-emerald-600',
    blue: 'bg-blue-50 text-blue-600',
    amber: 'bg-amber-50 text-amber-600',
    red: 'bg-red-50 text-red-600',
    violet: 'bg-violet-50 text-violet-600',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Table({ headers, children, className }: { headers: string[]; children: ReactNode; className?: string }) {
  return (
    <div className={cn('w-full overflow-auto', className)}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 bg-slate-50/60 text-left text-xs text-slate-500">
            {headers.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-2.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">{children}</tbody>
      </table>
    </div>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = 'max-w-lg',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  width?: string
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        className={cn('w-full rounded-xl bg-white shadow-xl', width)}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          <button className="text-slate-400 hover:text-slate-600" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="max-h-[75vh] overflow-auto px-5 py-4">{children}</div>
      </div>
    </div>
  )
}

export function Empty({ text = '暂无数据' }: { text?: string }) {
  return <div className="py-16 text-center text-sm text-slate-300">{text}</div>
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-brand',
        className,
      )}
    />
  )
}
