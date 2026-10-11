import { useEffect, useState } from 'react'
import { get, post, put, del, errMsg } from '../../lib/api'
import type { FlowAdminMeta, FlowDefDetail, FlowDefRow } from '../../types/api'
import { Button, Card, Input, Badge } from '../../components/ui'

interface NodeField { name: string; label: string; type?: string; options?: string[]; required?: boolean; placeholder?: string; validate?: string }
interface NodeFile { name: string; label: string; required?: boolean; accept?: string }
interface FlowNode {
  key: string; type: string; title: string
  fields?: NodeField[]; files?: NodeFile[]; action?: string; action_args?: Record<string, unknown>
  summary_template?: string; text?: string
}
const EMPTY_NODE: Record<string, Partial<FlowNode>> = {
  form: { key: '', type: 'form', title: '新表单', fields: [] },
  upload: { key: '', type: 'upload', title: '上传材料', files: [] },
  confirm: { key: 'confirm', type: 'confirm', title: '信息确认', summary_template: '' },
  auto: { key: '', type: 'auto', title: '系统核验', action: '' },
  end: { key: 'end', type: 'end', title: '办理完成', text: '' },
}

export default function FlowDefs() {
  const [rows, setRows] = useState<FlowDefRow[]>([])
  const [meta, setMeta] = useState<FlowAdminMeta | null>(null)
  const [msg, setMsg] = useState('')
  const load = async () => { setRows(await get<FlowDefRow[]>('/flow-admin/list')) }
  useEffect(() => { load(); get<FlowAdminMeta>('/flow-admin/meta').then(setMeta).catch(() => {}) }, [])

  const [editing, setEditing] = useState<null | { id?: number; base: Record<string, string>; nodes: FlowNode[]; mode: 'rows' | 'json'; json: string }>(null)

  const openNew = () => setEditing({ base: { flow_key: '', name: '', description: '', dept_no: '35000', keywords: '', mode: 'embed', url: '' }, nodes: [], mode: 'rows', json: '' })
  const openEdit = async (id: number) => {
    const d = await get<FlowDefDetail>(`/flow-admin/${id}`)
    let nodes: FlowNode[] = []
    try { nodes = JSON.parse(d.nodes || '[]') } catch { nodes = [] }
    setEditing({ id, base: { flow_key: d.flow_key, name: d.name, description: d.description || '', dept_no: d.dept_no, keywords: d.keywords || '', mode: d.mode || 'embed', url: d.url || '' }, nodes, mode: 'rows', json: '' })
  }
  const setNode = (i: number, patch: Partial<FlowNode>) => {
    if (!editing) return
    editing.nodes[i] = { ...editing.nodes[i], ...patch }
    setEditing({ ...editing, nodes: [...editing.nodes] })
  }
  const move = (i: number, d: number) => {
    if (!editing) return
    const j = i + d
    if (j < 0 || j >= editing.nodes.length) return
    const arr = [...editing.nodes]; [arr[i], arr[j]] = [arr[j], arr[i]]
    setEditing({ ...editing, nodes: arr })
  }
  const switchMode = (m: 'rows' | 'json') => {
    if (!editing) return
    if (m === 'json') setEditing({ ...editing, mode: m, json: JSON.stringify(editing.nodes, null, 2) })
    else {
      try { setEditing({ ...editing, mode: m, nodes: JSON.parse(editing.json) }) }
      catch { setMsg('JSON 解析失败，请检查后重试') }
    }
  }
  const nodesJson = () => editing?.mode === 'json' ? editing.json : JSON.stringify(editing?.nodes || [])

  const save = async () => {
    if (!editing) return
    setMsg('')
    try {
      const body = { ...editing.base, nodes: nodesJson() }
      if (editing.id) await put(`/flow-admin/${editing.id}`, body)
      else await post('/flow-admin', body)
      setEditing(null); await load(); setMsg('草稿已保存（不影响线上，发布后生效）')
    } catch (e) { setMsg(errMsg(e, '保存失败')) }
  }
  const publish = async (id: number) => {
    setMsg('')
    try { await post(`/flow-admin/${id}/publish`); await load(); setMsg('已发布：引擎即刻生效（办理中的实例仍按发起时定义走完）') }
    catch (e) { setMsg(errMsg(e, '发布失败')) }
  }
  const remove = async (id: number) => {
    setMsg('')
    try { await del(`/flow-admin/${id}`); await load() } catch (e) { setMsg(errMsg(e, '删除失败')) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">流程定义</h1>
          <p className="text-xs text-slate-400">草稿保存不影响线上 · 发布经全量结构校验后生效 · 办理中实例按发起时定义走完</p>
        </div>
        <Button size="sm" className="ml-auto" onClick={openNew}>＋ 新增流程</Button>
      </div>
      {msg && <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">{msg}</p>}
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>{['标识', '名称', '模式', '触发词', '节点数', '发布状态', '操作'].map(h => <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-3 py-2 font-mono text-[11px] text-slate-600">{r.flow_key}</td>
                <td className="px-3 py-2 text-slate-700">{r.name}</td>
                <td className="px-3 py-2">{r.mode === 'embed' ? '嵌入会话' : '跳转业务页'}</td>
                <td className="max-w-40 truncate px-3 py-2 text-slate-400">{r.keywords || '—'}</td>
                <td className="px-3 py-2">{r.dirty ? `${r.draft_nodes}(草稿)/${r.published_nodes}` : r.published_nodes}</td>
                <td className="px-3 py-2">
                  {!r.published ? <Badge tone="slate">未发布</Badge>
                    : r.dirty ? <Badge tone="amber">已发布·有草稿改动</Badge>
                    : <Badge tone="green">已发布</Badge>}
                </td>
                <td className="space-x-2 px-3 py-2">
                  <button className="text-brand hover:underline" onClick={() => openEdit(r.id)}>编辑</button>
                  <button className="text-emerald-600 hover:underline" onClick={() => publish(r.id)}>发布</button>
                  <button className="text-red-400 hover:underline" onClick={() => remove(r.id)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setEditing(null)}>
          <div onClick={e => e.stopPropagation()}>
          <Card className="max-h-[86vh] w-[860px] overflow-y-auto p-5">
            <div className="mb-3 flex items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-700">{editing.id ? '编辑流程' : '新增流程（草稿）'}</h3>
              <div className="ml-auto flex gap-1">
                <Button size="sm" variant={editing.mode === 'rows' ? 'default' : 'outline'} onClick={() => switchMode('rows')}>结构编辑</Button>
                <Button size="sm" variant={editing.mode === 'json' ? 'default' : 'outline'} onClick={() => switchMode('json')}>JSON 模式</Button>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2.5">
              {[['flow_key', '流程标识(英文)'], ['name', '流程名称'], ['dept_no', '归属机构号'], ['keywords', '触发词(空格分隔)']].map(([k, label]) => (
                <div key={k}>
                  <label className="mb-1 block text-[11px] text-slate-500">{label}</label>
                  <Input value={editing.base[k]} onChange={e => setEditing({ ...editing, base: { ...editing.base, [k]: e.target.value } })} />
                </div>
              ))}
              <div>
                <label className="mb-1 flex items-center gap-1 text-[11px] text-slate-500">
                  办理模式
                  <span className="group relative inline-flex">
                    <span className="flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-slate-300 text-[9px] text-slate-400">?</span>
                    <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 hidden w-[340px] -translate-x-1/2 rounded-lg border border-slate-200 bg-white p-3 text-left text-[10.5px] font-normal leading-4 text-slate-600 shadow-lg group-hover:block">
                      <p className="mb-1 font-semibold text-slate-700">嵌入会话办理</p>
                      <p className="mb-2">用户问到触发词后，回答下方出现 ▶ 在线办理入口，表单卡片嵌入对话框按节点逐步办理（填写/传材料/确认由用户操作，核验由系统自动执行），办理期间该会话暂停问答，完成后返回受理单号。需完整配置节点，适合可线上自动办结的简单业务。</p>
                      <p className="mb-1 font-semibold text-slate-700">跳转业务系统</p>
                      <p>回答下方出现 🔗 跳转按钮，新窗口打开"跳转地址"页面，材料提交与人工审核在外部系统完成，本系统只做智能推荐。不需配置节点，只需触发词和跳转地址，适合需人工审核的复杂业务。</p>
                    </span>
                  </span>
                </label>
                <select className="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                  value={editing.base.mode || 'embed'}
                  onChange={e => setEditing({ ...editing, base: { ...editing.base, mode: e.target.value } })}>
                  <option value="embed">嵌入会话办理</option>
                  <option value="redirect">跳转业务系统</option>
                </select>
              </div>
              {(editing.base.mode || 'embed') === 'redirect' && (
                <div>
                  <label className="mb-1 block text-[11px] text-slate-500">跳转地址（业务系统页面 URL）</label>
                  <Input value={editing.base.url} onChange={e => setEditing({ ...editing, base: { ...editing.base, url: e.target.value } })} />
                </div>
              )}
              <div className="col-span-3">
                <label className="mb-1 block text-[11px] text-slate-500">描述</label>
                <Input value={editing.base.description} onChange={e => setEditing({ ...editing, base: { ...editing.base, description: e.target.value } })} />
              </div>
            </div>

            {editing.mode === 'json' ? (
              <textarea
                className="mt-3 h-72 w-full rounded-md border border-slate-200 p-2 font-mono text-[11px]"
                value={editing.json}
                onChange={e => setEditing({ ...editing, json: e.target.value })}
              />
            ) : (
              <div className="mt-3 space-y-2">
                {editing.nodes.map((n, i) => (
                  <div key={i} className="rounded-lg border border-slate-200 p-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="w-6 text-center text-[10px] text-slate-400">{i + 1}</span>
                      <select className="h-7 rounded border border-slate-200 bg-white px-1 text-xs"
                        value={n.type} onChange={e => setNode(i, { ...EMPTY_NODE[e.target.value], key: n.key, title: n.title } as Partial<FlowNode>)}>
                        {(meta?.node_types || ['form', 'upload', 'confirm', 'auto', 'end']).map(t => <option key={t}>{t}</option>)}
                      </select>
                      <Input className="h-7 w-32 text-xs" value={n.key} placeholder="key" onChange={e => setNode(i, { key: e.target.value })} />
                      <Input className="h-7 flex-1 text-xs" value={n.title} placeholder="节点标题" onChange={e => setNode(i, { title: e.target.value })} />
                      <button className="text-xs text-slate-400 hover:text-brand" onClick={() => move(i, -1)}>↑</button>
                      <button className="text-xs text-slate-400 hover:text-brand" onClick={() => move(i, 1)}>↓</button>
                      <button className="text-xs text-slate-400 hover:text-red-400" onClick={() => setEditing({ ...editing, nodes: editing.nodes.filter((_, j) => j !== i) })}>删</button>
                    </div>
                    {n.type === 'auto' && (
                      <div className="mt-2 flex gap-2">
                        <select className="h-7 rounded border border-slate-200 bg-white px-1 text-xs" value={n.action || ''} onChange={e => setNode(i, { action: e.target.value })}>
                          <option value="">选择动作…</option>
                          {(meta?.actions || []).map(a => <option key={a.key} value={a.key}>{a.key}（{a.doc.slice(0, 18)}）</option>)}
                        </select>
                        <Input className="h-7 flex-1 text-xs" placeholder='动作参数 JSON（可空），如 {"scene":"租房提取"}'
                          value={n.action_args ? JSON.stringify(n.action_args) : ''}
                          onChange={e => { try { setNode(i, { action_args: e.target.value.trim() ? JSON.parse(e.target.value) : undefined }) } catch { /* 输入中 */ } }} />
                      </div>
                    )}
                    {n.type === 'confirm' && (
                      <textarea className="mt-2 h-20 w-full rounded border border-slate-200 p-2 font-mono text-[11px]" placeholder="确认摘要模板（{变量} 引用流程变量，敏感值自动脱敏）"
                        value={n.summary_template || ''} onChange={e => setNode(i, { summary_template: e.target.value })} />
                    )}
                    {n.type === 'end' && (
                      <textarea className="mt-2 h-16 w-full rounded border border-slate-200 p-2 text-xs" placeholder="完成文案"
                        value={n.text || ''} onChange={e => setNode(i, { text: e.target.value })} />
                    )}
                    {n.type === 'form' && (
                      <div className="mt-2 space-y-1.5">
                        {(n.fields || []).map((f, fi) => (
                          <div key={fi} className="flex flex-wrap items-center gap-1.5">
                            <Input className="h-7 w-24 text-[11px]" value={f.name} placeholder="字段名" onChange={e => { n.fields![fi] = { ...f, name: e.target.value }; setNode(i, { fields: [...n.fields!] }) }} />
                            <Input className="h-7 w-28 text-[11px]" value={f.label} placeholder="标签" onChange={e => { n.fields![fi] = { ...f, label: e.target.value }; setNode(i, { fields: [...n.fields!] }) }} />
                            <select className="h-7 rounded border border-slate-200 bg-white px-1 text-[11px]" value={f.type || 'input'} onChange={e => { n.fields![fi] = { ...f, type: e.target.value }; setNode(i, { fields: [...n.fields!] }) }}>
                              {(meta?.field_types || ['input', 'number', 'select']).map(t => <option key={t}>{t}</option>)}
                            </select>
                            <label className="flex items-center gap-1 text-[10px] text-slate-500">
                              <input type="checkbox" checked={!!f.required} onChange={e => { n.fields![fi] = { ...f, required: e.target.checked }; setNode(i, { fields: [...n.fields!] }) }} />必填
                            </label>
                            {(f.type || 'input') === 'select' && (
                              <Input className="h-7 w-40 text-[11px]" placeholder="选项(逗号分隔)" value={(f.options || []).join(',')}
                                onChange={e => { n.fields![fi] = { ...f, options: e.target.value.split(/[,，]/).filter(Boolean) }; setNode(i, { fields: [...n.fields!] }) }} />
                            )}
                            <select className="h-7 rounded border border-slate-200 bg-white px-1 text-[11px]" value={f.validate || ''} onChange={e => { n.fields![fi] = { ...f, validate: e.target.value || undefined }; setNode(i, { fields: [...n.fields!] }) }}>
                              <option value="">无校验</option>
                              {(meta?.validate_rules || []).map(r => <option key={r}>{r}</option>)}
                            </select>
                            <button className="text-[11px] text-slate-400 hover:text-red-400" onClick={() => setNode(i, { fields: n.fields!.filter((_, j) => j !== fi) })}>删</button>
                          </div>
                        ))}
                        <button className="text-[11px] text-brand hover:underline" onClick={() => setNode(i, { fields: [...(n.fields || []), { name: '', label: '', type: 'input' }] })}>＋ 添加字段</button>
                      </div>
                    )}
                    {n.type === 'upload' && (
                      <div className="mt-2 space-y-1.5">
                        {(n.files || []).map((f, fi) => (
                          <div key={fi} className="flex items-center gap-1.5">
                            <Input className="h-7 w-28 text-[11px]" value={f.name} placeholder="槽位名" onChange={e => { n.files![fi] = { ...f, name: e.target.value }; setNode(i, { files: [...n.files!] }) }} />
                            <Input className="h-7 flex-1 text-[11px]" value={f.label} placeholder="材料名称" onChange={e => { n.files![fi] = { ...f, label: e.target.value }; setNode(i, { files: [...n.files!] }) }} />
                            <label className="flex items-center gap-1 text-[10px] text-slate-500">
                              <input type="checkbox" checked={!!f.required} onChange={e => { n.files![fi] = { ...f, required: e.target.checked }; setNode(i, { files: [...n.files!] }) }} />必传
                            </label>
                            <button className="text-[11px] text-slate-400 hover:text-red-400" onClick={() => setNode(i, { files: n.files!.filter((_, j) => j !== fi) })}>删</button>
                          </div>
                        ))}
                        <button className="text-[11px] text-brand hover:underline" onClick={() => setNode(i, { files: [...(n.files || []), { name: '', label: '', required: true }] })}>＋ 添加材料槽</button>
                      </div>
                    )}
                  </div>
                ))}
                <div className="flex gap-1.5">
                  {(meta?.node_types || ['form', 'upload', 'confirm', 'auto', 'end']).map(t => (
                    <button key={t} className="rounded border border-dashed border-slate-300 px-2 py-1 text-[11px] text-slate-500 hover:border-brand hover:text-brand"
                      onClick={() => setEditing({ ...editing, nodes: [...editing.nodes, { ...EMPTY_NODE[t], key: `${t}_${editing.nodes.length + 1}` } as FlowNode] })}>
                      ＋{t}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-4 flex items-center gap-2">
              <Button size="sm" onClick={save}>保存草稿</Button>
              {editing.id && <Button size="sm" variant="outline" className="!border-emerald-300 !text-emerald-600 hover:!bg-emerald-50" onClick={async () => { await save(); if (editing.id) await publish(editing.id) }}>保存并发布</Button>}
              <button className="ml-auto text-xs text-slate-400 hover:text-red-400" onClick={() => setEditing(null)}>关闭</button>
            </div>
          </Card>
        </div>
        </div>
      )}
    </div>
  )
}
