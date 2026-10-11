import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { MenuRow, RoleRow } from '../../types/api'
import { Card, Table, Badge, Button, Input, Select, Modal, Empty } from '../../components/ui'
import { Field } from './Knowledge'

/** 菜单树节点（列表行 + 前端组树）。 */
interface MenuNode extends MenuRow {
  children?: MenuNode[]
}

/** 角色编辑表单体。 */
interface RoleForm {
  id?: number
  role_name: string
  role_key: string
  data_scope: number
  status: string
  remark: string
  menu_ids: number[]
}

export default function Roles() {
  const [rows, setRows] = useState<RoleRow[]>([])
  const [menus, setMenus] = useState<MenuRow[]>([])
  const [editing, setEditing] = useState<RoleForm | null>(null)

  const load = async () => setRows(await get<RoleRow[]>('/system/roles'))
  useEffect(() => {
    load()
    get<MenuRow[]>('/system/menus').then(setMenus).catch(() => {})
  }, [])

  const save = async () => {
    if (!editing) return
    try {
      if (editing.id) await put(`/system/roles/${editing.id}`, editing)
      else await post('/system/roles', editing)
      setEditing(null)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const remove = async (r: RoleRow) => {
    if (!confirm(`确认删除角色「${r.role_name}」？`)) return
    try {
      await del(`/system/roles/${r.id}`)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const renderMenuCheck = (m: MenuNode, depth = 0) => (
    <div key={m.id}>
      <label className="flex items-center gap-1.5 py-1 text-xs text-slate-600" style={{ paddingLeft: depth * 18 }}>
        <input
          type="checkbox"
          checked={editing?.menu_ids?.includes(m.id)}
          onChange={(e) => editing && setEditing({
            ...editing,
            menu_ids: e.target.checked ? [...editing.menu_ids, m.id] : editing.menu_ids.filter((i) => i !== m.id),
          })}
        />
        {m.menu_type === 'F' ? '▪️' : m.menu_type === 'M' ? '📂' : '📄'} {m.menu_name}
        {m.perms && <code className="ml-1 rounded bg-slate-100 px-1 text-[9px] text-slate-400">{m.perms}</code>}
      </label>
      {m.children?.map((c) => renderMenuCheck(c, depth + 1))}
    </div>
  )

  const menuTree = (() => {
    const build = (parent = 0): MenuNode[] =>
      menus.filter((m) => m.parent_id === parent).map((m) => ({ ...m, children: build(m.id) }))
    return build()
  })()

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">角色管理</h1>
          <p className="mt-0.5 text-xs text-slate-400">RBAC 权限体系：角色绑定菜单/按钮权限 + 数据范围（全部/本部门及以下）</p>
        </div>
        <Button size="sm" onClick={() => setEditing({ role_name: '', role_key: '', data_scope: 2, status: '0', remark: '', menu_ids: [] })}>
          ＋ 新增角色
        </Button>
      </div>

      <Card>
        <Table headers={['ID', '角色名', '权限字符', '数据范围', '菜单权限数', '状态', '备注', '']}>
          {rows.length === 0 && <tr><td colSpan={8}><Empty /></td></tr>}
          {rows.map((r) => (
            <tr key={r.id} className="text-xs text-slate-600 hover:bg-slate-50/70">
              <td className="px-4 py-2.5 font-mono text-slate-400">{r.id}</td>
              <td className="px-4 py-2.5 font-medium">{r.role_name}</td>
              <td className="px-4 py-2.5"><code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px]">{r.role_key}</code></td>
              <td className="px-4 py-2.5">
                <Badge tone={r.data_scope === 1 ? 'green' : 'blue'}>
                  {r.data_scope === 1 ? '全部数据' : '本部门及以下'}
                </Badge>
              </td>
              <td className="px-4 py-2.5 font-mono">{r.menu_ids.length}</td>
              <td className="px-4 py-2.5">
                <Badge tone={r.status === '0' ? 'green' : 'red'}>{r.status === '0' ? '正常' : '停用'}</Badge>
              </td>
              <td className="px-4 py-2.5 text-slate-400">{r.remark || '—'}</td>
              <td className="whitespace-nowrap px-4 py-2.5">
                <Button size="sm" variant="ghost" onClick={() => setEditing({
                  id: r.id, role_name: r.role_name, role_key: r.role_key, data_scope: r.data_scope,
                  status: r.status, remark: r.remark, menu_ids: r.menu_ids,
                })}>编辑</Button>
                <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(r)}>删除</Button>
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing?.id ? '编辑角色' : '新增角色'}>
        {editing && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-2 gap-3">
              <Field label="角色名称">
                <Input value={editing.role_name} onChange={(e) => setEditing({ ...editing, role_name: e.target.value })} />
              </Field>
              <Field label="权限字符">
                <Input value={editing.role_key} disabled={!!editing.id} onChange={(e) => setEditing({ ...editing, role_key: e.target.value })} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="数据范围">
                <Select value={editing.data_scope} onChange={(e) => setEditing({ ...editing, data_scope: Number(e.target.value) })}>
                  <option value={1}>全部数据</option>
                  <option value={2}>本部门及以下</option>
                </Select>
              </Field>
              <Field label="状态">
                <Select value={editing.status} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                  <option value="0">正常</option>
                  <option value="1">停用</option>
                </Select>
              </Field>
            </div>
            <Field label="备注">
              <Input value={editing.remark} onChange={(e) => setEditing({ ...editing, remark: e.target.value })} />
            </Field>
            <Field label="菜单与按钮权限">
              <div className="max-h-64 overflow-auto rounded-md border border-slate-200 p-2.5">
                {menuTree.map((m) => renderMenuCheck(m))}
              </div>
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button disabled={!editing.role_name || !editing.role_key} onClick={save}>保存</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
