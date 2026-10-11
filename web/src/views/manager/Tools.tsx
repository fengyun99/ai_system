import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { ToolRow } from '../../types/api'
import { Card, Table, Badge, Button, Modal, Input, Textarea, Select, Empty } from '../../components/ui'
import { Field } from './Knowledge'

/** 工具编辑表单体（ToolBody 请求形态）。 */
interface ToolForm {
  id?: number
  dept_no: string
  name: string
  description: string
  parameters: string
  shared: number
  status: number
}

export default function Tools() {
  const [rows, setRows] = useState<ToolRow[]>([])
  const [editing, setEditing] = useState<ToolForm | null>(null)

  const load = async () => setRows(await get<ToolRow[]>('/tools/list'))
  useEffect(() => { load() }, [])

  const save = async () => {
    if (!editing) return
    try {
      if (editing.id) await put(`/tools/${editing.id}`, editing)
      else await post('/tools', editing)
      setEditing(null)
      load()
    } catch (e) {
      alert(errMsg(e))
    }
  }

  const remove = async (t: ToolRow) => {
    if (!confirm(`确认删除工具「${t.name}」？`)) return
    await del(`/tools/${t.id}`)
    load()
  }

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">MCP 工具登记</h1>
          <p className="mt-0.5 text-xs text-slate-400">
            工具服务：同进程 FastMCP（streamable-http /mcp）；清单按部门下发（本部门 + 共享），Agent 端 list_tools → bind_tools
          </p>
        </div>
        <Button size="sm" onClick={() => setEditing({ dept_no: '', name: '', description: '', parameters: '{"type":"object","properties":{},"required":[]}', shared: 0, status: 1 })}>
          ＋ 新增工具
        </Button>
      </div>

      <Card>
        <Table headers={['ID', '工具名', '归属机构', '描述', '参数 Schema', '共享', '状态', '']}>
          {rows.length === 0 && <tr><td colSpan={8}><Empty /></td></tr>}
          {rows.map((t) => (
            <tr key={t.id} className="text-xs text-slate-600 hover:bg-slate-50/70">
              <td className="px-4 py-2.5 font-mono text-slate-400">{t.id}</td>
              <td className="px-4 py-2.5 font-mono font-medium text-amber-700">{t.name}</td>
              <td className="px-4 py-2.5 font-mono">{t.dept_no}</td>
              <td className="max-w-[220px] truncate px-4 py-2.5" title={t.description}>{t.description}</td>
              <td className="max-w-[200px] truncate px-4 py-2.5 font-mono text-[10px] text-slate-400" title={t.parameters}>
                {t.parameters}
              </td>
              <td className="px-4 py-2.5">{t.shared ? <Badge tone="green">共享</Badge> : <Badge>本部门</Badge>}</td>
              <td className="px-4 py-2.5">
                <Badge tone={t.status === 1 ? 'green' : 'red'}>{t.status === 1 ? '启用' : '停用'}</Badge>
              </td>
              <td className="whitespace-nowrap px-4 py-2.5">
                <Button size="sm" variant="ghost" onClick={() => setEditing({ ...t })}>编辑</Button>
                <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(t)}>删除</Button>
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing?.id ? '编辑工具' : '新增工具'}>
        {editing && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-2 gap-3">
              <Field label="工具名（唯一，与 MCP 服务端注册名一致）">
                <Input value={editing.name} disabled={!!editing.id} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
              </Field>
              <Field label="归属机构号">
                <Input value={editing.dept_no} onChange={(e) => setEditing({ ...editing, dept_no: e.target.value })} placeholder="如 35000" />
              </Field>
            </div>
            <Field label="工具描述（供大模型理解用途）">
              <Input value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
            </Field>
            <Field label="参数 JSON Schema">
              <Textarea rows={6} className="font-mono text-xs" value={editing.parameters}
                onChange={(e) => setEditing({ ...editing, parameters: e.target.value })} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="共享">
                <Select value={editing.shared} onChange={(e) => setEditing({ ...editing, shared: Number(e.target.value) })}>
                  <option value={0}>仅本部门</option>
                  <option value={1}>全部门共享</option>
                </Select>
              </Field>
              <Field label="状态">
                <Select value={editing.status} onChange={(e) => setEditing({ ...editing, status: Number(e.target.value) })}>
                  <option value={1}>启用</option>
                  <option value={0}>停用</option>
                </Select>
              </Field>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button disabled={!editing.name || !editing.dept_no} onClick={save}>保存</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
