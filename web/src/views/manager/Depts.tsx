import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { DeptRow } from '../../types/api'
import { Card, Table, Badge, Button, Modal, Input, Empty } from '../../components/ui'
import { Field } from './Knowledge'

/** 机构编辑表单体。 */
interface DeptForm {
  id?: number
  dept_no: string
  dept_name: string
  parent_id: number
  status: string
}

export default function Depts() {
  const [rows, setRows] = useState<DeptRow[]>([])
  const [editing, setEditing] = useState<DeptForm | null>(null)

  const load = async () => setRows(await get<DeptRow[]>('/system/depts'))
  useEffect(() => { load() }, [])

  const save = async () => {
    if (!editing) return
    try {
      if (editing.id) await put(`/system/depts/${editing.id}`, editing)
      else await post('/system/depts', editing)
      setEditing(null)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const remove = async (d: DeptRow) => {
    if (!confirm(`确认删除机构「${d.dept_name}」？`)) return
    try {
      await del(`/system/depts/${d.id}`)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const depth = (ancestors: string) => (ancestors === '0' ? 0 : ancestors.split(',').length)

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">部门（机构）管理</h1>
          <p className="mt-0.5 text-xs text-slate-400">
            多租户轴：机构树决定检索可见性（本部门+祖先链公开知识）与数据读范围（本部门及以下）
          </p>
        </div>
        <Button size="sm" onClick={() => setEditing({ dept_no: '', dept_name: '', parent_id: 0, status: '0' })}>＋ 新增机构</Button>
      </div>

      <Card>
        <Table headers={['机构号', '机构名称', '层级', '父级路径', '状态', '']}>
          {rows.length === 0 && <tr><td colSpan={6}><Empty /></td></tr>}
          {rows.map((d) => (
            <tr key={d.id} className="text-xs text-slate-600 hover:bg-slate-50/70">
              <td className="px-4 py-2.5 font-mono font-medium">{d.dept_no}</td>
              <td className="px-4 py-2.5" style={{ paddingLeft: `${16 + depth(d.ancestors) * 20}px` }}>
                {depth(d.ancestors) > 0 && <span className="mr-1 text-slate-300">└</span>}
                {d.dept_name}
              </td>
              <td className="px-4 py-2.5 text-slate-400">L{depth(d.ancestors)}</td>
              <td className="px-4 py-2.5 font-mono text-[10px] text-slate-400">{d.ancestors}</td>
              <td className="px-4 py-2.5">
                <Badge tone={d.status === '0' ? 'green' : 'red'}>{d.status === '0' ? '正常' : '停用'}</Badge>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5">
                <Button size="sm" variant="ghost" onClick={() => setEditing({ ...d })}>编辑</Button>
                <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(d)}>删除</Button>
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing?.id ? '编辑机构' : '新增机构'}>
        {editing && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-2 gap-3">
              <Field label="机构号 dept_no">
                <Input value={editing.dept_no} onChange={(e) => setEditing({ ...editing, dept_no: e.target.value })} placeholder="如 35004" />
              </Field>
              <Field label="机构名称">
                <Input value={editing.dept_name} onChange={(e) => setEditing({ ...editing, dept_name: e.target.value })} />
              </Field>
            </div>
            <Field label="上级机构">
              <select
                className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                value={editing.parent_id}
                disabled={!!editing.id}
                onChange={(e) => setEditing({ ...editing, parent_id: Number(e.target.value) })}
              >
                <option value={0}>（根）</option>
                {rows.filter((d) => d.id !== editing.id).map((d) => (
                  <option key={d.id} value={d.id}>{d.dept_name}（{d.dept_no}）</option>
                ))}
              </select>
            </Field>
            <Field label="状态">
              <select
                className="flex h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                value={editing.status}
                onChange={(e) => setEditing({ ...editing, status: e.target.value })}
              >
                <option value="0">正常</option>
                <option value="1">停用</option>
              </select>
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button disabled={!editing.dept_no || !editing.dept_name} onClick={save}>保存</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
