/**
 * API 访问层：统一 token 头 + 响应解包 + SSE 流读取。
 *
 * 数据契约见 src/types/api.ts（与后端 app/api/schemas.py 镜像）。
 * 泛型默认 unknown：调用点必须显式给出 data 类型，杜绝静默 any。
 */

import type { StreamEvent } from '../types/api'

export const API_BASE = '/api'

export function token(): string | null {
  return localStorage.getItem('token')
}

export class ApiError extends Error {
  code: number
  constructor(msg: string, code: number) {
    super(msg)
    this.code = code
  }
}

/** catch 块取错误文案（ApiError/普通 Error 兼容，替代 catch (e: any)）。 */
export const errMsg = (e: unknown, fallback = '操作失败'): string =>
  e instanceof Error ? e.message : fallback

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      token: token() || '',
      ...(options.headers || {}),
    },
  })
  const body = await resp.json().catch(() => ({ code: resp.status, msg: '响应解析失败' }))
  // 登录接口的 401 是口令错误：只抛错不跳转（整页跳转会销毁 Login 组件，错误提示渲染不出来）
  if (body.code === 401 && path !== '/login') {
    localStorage.removeItem('token')
    window.location.href = '/login'
    throw new ApiError(body.msg || '未登录', 401)
  }
  if (body.code !== 200) throw new ApiError(body.msg || '请求失败', body.code)
  return body.data as T
}

export const get = <T = unknown>(path: string) => api<T>(path)
export const post = <T = unknown>(path: string, data?: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(data || {}) })
export const put = <T = unknown>(path: string, data?: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(data || {}) })
export const del = <T = unknown>(path: string) => api<T>(path, { method: 'DELETE' })

/** 文件导出下载（GET + token 头 → xlsx blob；后端流式响应）。 */
export async function downloadFile(path: string, filename: string) {
  const resp = await fetch(`${API_BASE}${path}`, { headers: { token: token() || '' } })
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('spreadsheet')) {
    const payload = await resp.json().catch(() => ({ code: resp.status, msg: '导出失败' }))
    if (payload.code === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    throw new ApiError(payload.msg || '导出失败', payload.code)
  }
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** 流程材料上传（multipart）：slot=材料槽位，返回 {slot,filename,size} */
export async function uploadFlowFile(
  instanceId: number, slot: string, file: File,
): Promise<{ slot: string; filename: string; size: number }> {
  const fd = new FormData()
  fd.append('slot', slot)
  fd.append('file', file)
  const resp = await fetch(`${API_BASE}/flow/upload/${instanceId}`, {
    method: 'POST', headers: { token: token() || '' }, body: fd,
  })
  const body = await resp.json().catch(() => ({ code: resp.status, msg: '上传失败' }))
  if (body.code !== 200) throw new ApiError(body.msg || '上传失败', body.code)
  return body.data
}

/** SSE 流式请求：逐事件回调（fetch reader 切帧，与后端 data: JSON 帧协议一致）。
 *  非 SSE 响应（如流程门控 409 的 JSON）会解析为 ApiError 抛出。 */
export async function sse(
  path: string,
  body: unknown,
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', token: token() || '' },
    body: JSON.stringify(body),
    signal,
  })
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('text/event-stream')) {
    const payload = await resp.json().catch(() => ({ code: resp.status, msg: '请求失败' }))
    if (payload.code === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    throw new ApiError(payload.msg || '请求失败', payload.code)
  }
  if (!resp.body) throw new Error('无响应流')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(line.slice(6)))
          } catch {
            /* 忽略残帧 */
          }
        }
      }
    }
  }
}


/** GET 形态的 SSE（断线续流 resume）。 */
export async function sseGet(
  path: string,
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { token: token() || '' },
    signal,
  })
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('text/event-stream')) {
    const payload = await resp.json().catch(() => ({ code: resp.status, msg: '请求失败' }))
    throw new ApiError(payload.msg || '请求失败', payload.code)
  }
  if (!resp.body) throw new Error('无响应流')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(line.slice(6)))
          } catch {
            /* 忽略残帧 */
          }
        }
      }
    }
  }
}
