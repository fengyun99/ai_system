import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { MenuRow } from '../../types/api'
import type { BadgeTone } from '../../components/ui'
import { Card, Table, Badge, Button, Modal, Input, Empty } from '../../components/ui'
import { Field } from './Knowledge'

/** 菜单编辑表单体（MenuBody 请求形态）。 */
interface MenuForm {
  id?: number
  menu_name: string
  parent_id: number
  path: string
  component: string
  perms: string
  menu_type: string
  icon: string
  sort: number
  visible: number
}

export default function Menus() {
  const [rows, setRows] = useState<MenuRow[]>([])
  const [editing, setEditing] = useState<MenuForm | null>(null)

  const load = async () => setRows(await get<MenuRow[]>('/system/menus'))
  useEffect(() => { load() }, [])

  const save = async () => {
    if (!editing) return
    try {
      if (editing.id) await put(`/system/menus/${editing.id}`, editing)
      else await post('/system/menus', editing)
      setEditing(null)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const remove = async (m: MenuRow) => {
    if (!confirm(`确认删除菜单「${m.menu_name}」？`)) return
    try {
      await del(`/system/menus/${m.id}`)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const TYPE_LABEL: Record<string, [string, BadgeTone]> = {
    M: ['目录', 'violet'], C: ['菜单', 'blue'], F: ['按钮', 'amber'],
  }

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">菜单管理</h1>
          <p className="mt-0.5 text-xs text-slate-400">目录(M)/菜单(C)/按钮(F) 三级结构；按钮 perms 为接口级权限标识</p>
        </div>
        <Button size="sm" onClick={() => setEditing({ menu_name: '', parent_id: 0, path: '', component: '', perms: '', menu_type: 'C', icon: '', sort: 0, visible: 1 })}>
          ＋ 新增菜单
        </Button>
      </div>

      <Card>
        <Table headers={['名称', '类型', '路由', '组件', '权限标识', '排序', '']}>
          {rows.length === 0 && <tr><td colSpan={7}><Empty /></td></tr>}
          {rows.map((m) => {
            const [label, tone] = TYPE_LABEL[m.menu_type] || ['?', 'slate']
            const depth = m.parent_id === 0 ? 0 : 1
            return (
              <tr key={m.id} className="text-xs text-slate-600 hover:bg-slate-50/70">
                <td className="px-4 py-2.5 font-medium" style={{ paddingLeft: `${16 + depth * 20}px` }}>
                  {depth > 0 && <span className="mr-1 text-slate-300">└</span>}
                  {m.menu_name}
                </td>
                <td className="px-4 py-2.5"><Badge tone={tone}>{label}</Badge></td>
                <td className="px-4 py-2.5 font-mono text-[11px]">{m.path || '—'}</td>
                <td className="px-4 py-2.5 font-mono text-[11px] text-slate-400">{m.component || '—'}</td>
                <td className="px-4 py-2.5">
                  {m.perms ? <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px]">{m.perms}</code> : '—'}
                </td>
                <td className="px-4 py-2.5 font-mono">{m.sort}</td>
                <td className="whitespace-nowrap px-4 py-2.5">
                  <Button size="sm" variant="ghost" onClick={() => setEditing({ ...m })}>编辑</Button>
                  <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(m)}>删除</Button>
                </td>
              </tr>
            )
          })}
        </Table>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing?.id ? '编辑菜单' : '新增菜单'}>
        {editing && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-2 gap-3">
              <Field label="名称">
                <Input value={editing.menu_name} onChange={(e) => setEditing({ ...editing, menu_name: e.target.value })} />
              </Field>
              <Field label="类型">
                <select className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                  value={editing.menu_type} onChange={(e) => setEditing({ ...editing, menu_type: e.target.value })}>
                  <option value="M">目录</option>
                  <option value="C">菜单</option>
                  <option value="F">按钮</option>
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="上级菜单">
                <select className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                  value={editing.parent_id} onChange={(e) => setEditing({ ...editing, parent_id: Number(e.target.value) })}>
                  <option value={0}>（根）</option>
                  {rows.filter((r) => r.menu_type !== 'F' && r.id !== editing.id).map((r) => (
                    <option key={r.id} value={r.id}>{r.menu_name}</option>
                  ))}
                </select>
              </Field>
              <Field label="排序">
                <Input type="number" value={editing.sort} onChange={(e) => setEditing({ ...editing, sort: Number(e.target.value) })} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="路由地址（C/M）">
                <Input value={editing.path} onChange={(e) => setEditing({ ...editing, path: e.target.value })} />
              </Field>
              <Field label="权限标识（F 常用）">
                <Input value={editing.perms} onChange={(e) => setEditing({ ...editing, perms: e.target.value })} placeholder="如 kb:add" />
              </Field>
            </div>
            <Field label="前端组件路径（C）">
              <Input value={editing.component} onChange={(e) => setEditing({ ...editing, component: e.target.value })} placeholder="如 kb/Knowledge" />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button disabled={!editing.menu_name} onClick={save}>保存</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
