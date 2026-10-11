import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { DeptRow, RoleRow, UserRow } from '../../types/api'
import { Card, Table, Badge, Button, Input, Select, Modal, Empty } from '../../components/ui'
import { Field } from './Knowledge'

/** 用户编辑表单体（UserBody 请求 + 列表行编辑态共用）。 */
interface UserForm {
  id?: number
  user_name: string
  nick_name: string
  password: string
  dept_id: number | undefined
  phone: string
  status: string
  role_ids: number[]
}

export default function Users() {
  const [rows, setRows] = useState<UserRow[]>([])
  const [depts, setDepts] = useState<DeptRow[]>([])
  const [roles, setRoles] = useState<RoleRow[]>([])
  const [editing, setEditing] = useState<UserForm | null>(null)

  const load = async () => setRows(await get<UserRow[]>('/system/users'))
  useEffect(() => {
    load()
    get<DeptRow[]>('/system/depts').then(setDepts).catch(() => {})
    get<RoleRow[]>('/system/roles').then(setRoles).catch(() => {})
  }, [])

  const save = async () => {
    if (!editing) return
    try {
      if (editing.id) await put(`/system/users/${editing.id}`, editing)
      else await post('/system/users', editing)
      setEditing(null)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const remove = async (u: UserRow) => {
    if (!confirm(`确认删除用户「${u.nick_name}」？`)) return
    try {
      await del(`/system/users/${u.user_id}`)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">用户管理</h1>
          <p className="mt-0.5 text-xs text-slate-400">
            口令按原 Java 国密协议入库（$1a + SM3 双重摘要，前后端同算法互认）
          </p>
        </div>
        <Button size="sm" onClick={() => setEditing({ user_name: '', nick_name: '', password: '', dept_id: depts[0]?.id, phone: '', status: '0', role_ids: [] })}>
          ＋ 新增用户
        </Button>
      </div>

      <Card>
        <Table headers={['ID', '账号', '昵称', '所属机构', '角色', '状态', '最后登录', '']}>
          {rows.length === 0 && <tr><td colSpan={8}><Empty /></td></tr>}
          {rows.map((u) => (
            <tr key={u.user_id} className="text-xs text-slate-600 hover:bg-slate-50/70">
              <td className="px-4 py-2.5 font-mono text-slate-400">{u.user_id}</td>
              <td className="px-4 py-2.5 font-mono font-medium">{u.user_name}</td>
              <td className="px-4 py-2.5">{u.nick_name}</td>
              <td className="whitespace-nowrap px-4 py-2.5">
                {u.dept_name} <span className="font-mono text-slate-400">{u.dept_no}</span>
              </td>
              <td className="px-4 py-2.5">
                <div className="flex gap-1">
                  {u.roles.map((r) => <Badge key={r.id} tone="violet">{r.role_name}</Badge>)}
                </div>
              </td>
              <td className="px-4 py-2.5">
                <Badge tone={u.status === '0' ? 'green' : 'red'}>{u.status === '0' ? '正常' : '停用'}</Badge>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5 text-slate-400">{u.last_login_at || '—'}</td>
              <td className="whitespace-nowrap px-4 py-2.5">
                <Button size="sm" variant="ghost" onClick={() => setEditing({
                  id: u.user_id, user_name: u.user_name, nick_name: u.nick_name, password: '',
                  dept_id: depts.find((d) => d.dept_no === u.dept_no)?.id, phone: u.phone,
                  status: u.status, role_ids: u.roles.map((r) => r.id),
                })}>编辑</Button>
                <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(u)}>删除</Button>
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing?.id ? '编辑用户' : '新增用户'}>
        {editing && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-2 gap-3">
              <Field label="登录账号">
                <Input value={editing.user_name} disabled={!!editing.id}
                  onChange={(e) => setEditing({ ...editing, user_name: e.target.value })} />
              </Field>
              <Field label="昵称">
                <Input value={editing.nick_name} onChange={(e) => setEditing({ ...editing, nick_name: e.target.value })} />
              </Field>
            </div>
            <Field label={editing.id ? '重置密码（留空不修改）' : '初始密码'}>
              <Input type="password" value={editing.password} onChange={(e) => setEditing({ ...editing, password: e.target.value })} />
            </Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="所属机构">
                <Select value={editing.dept_id} onChange={(e) => setEditing({ ...editing, dept_id: Number(e.target.value) })}>
                  {depts.map((d) => <option key={d.id} value={d.id}>{d.dept_name}（{d.dept_no}）</option>)}
                </Select>
              </Field>
              <Field label="状态">
                <Select value={editing.status} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                  <option value="0">正常</option>
                  <option value="1">停用</option>
                </Select>
              </Field>
              <Field label="手机号">
                <Input value={editing.phone} onChange={(e) => setEditing({ ...editing, phone: e.target.value })} />
              </Field>
            </div>
            <Field label="角色">
              <div className="flex flex-wrap gap-3 rounded-md border border-slate-200 p-2.5">
                {roles.map((r) => (
                  <label key={r.id} className="flex items-center gap-1.5 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={editing.role_ids.includes(r.id)}
                      onChange={(e) => setEditing({
                        ...editing,
                        role_ids: e.target.checked
                          ? [...editing.role_ids, r.id]
                          : editing.role_ids.filter((i: number) => i !== r.id),
                      })}
                    />
                    {r.role_name}
                  </label>
                ))}
              </div>
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button disabled={!editing.user_name || (!editing.id && !editing.password)} onClick={save}>保存</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
