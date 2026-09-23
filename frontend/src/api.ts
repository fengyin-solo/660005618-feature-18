import axios, { AxiosError } from 'axios'
import type { DAGWorkflowDef, Snapshot, FieldContract, ScreenSession, Member, DenyDetail } from '@/types'

// 当前请求来源表面：'page' 普通页面 | 'screen' 大屏只读表面。
// 大屏通道发出的变更请求会被服务端直接拒绝（X-Surface 闸门）。
let surface: 'page' | 'screen' = 'page'
let memberId = () => 'u-alice'

export function configureApi(opts: { getMemberId: () => string; surface_?: 'page' | 'screen' }) {
  memberId = opts.getMemberId
  if (opts.surface_) surface = opts.surface_
}
export function setSurface(s: 'page' | 'screen') { surface = s }

export const http = axios.create({ baseURL: location.origin })

http.interceptors.request.use(cfg => {
  cfg.headers = cfg.headers || {}
  cfg.headers['X-Member-Id'] = memberId()
  cfg.headers['X-Surface'] = surface
  return cfg
})

/** 提取后端 403/401 的拒绝理由；无结构化 detail 时给兜底文案。 */
export function denyReason(err: unknown): DenyDetail {
  const ax = err as AxiosError<{ detail: DenyDetail }>
  const d = ax.response?.data?.detail
  if (d && typeof d === 'object' && d.message) return d
  return { code: 'unknown', message: '操作被拒绝' }
}

export const api = {
  members: () => http.get<{ members: Member[] }>('/api/members').then(r => r.data.members),
  contract: () => http.get<FieldContract>('/api/contract').then(r => r.data),
  state: () => http.get<Snapshot>('/api/state').then(r => r.data),
  createWorkflow: (name: string) =>
    http.post<DAGWorkflowDef>('/api/workflow', { name }).then(r => r.data),
  run: (workflowId: number, workers: number, strategy: string) =>
    http.post<Snapshot & { runId: number }>('/api/run', { workflowId, workers, strategy }).then(r => r.data),
  activeScreen: () =>
    http.get<{ session: ScreenSession | null }>('/api/screen/active').then(r => r.data.session),
  startScreen: () =>
    http.post<{ session: ScreenSession }>('/api/screen/start').then(r => r.data.session),
  stopScreen: (code: string) =>
    http.post<{ session: ScreenSession }>(`/api/screen/${code}/stop`).then(r => r.data.session),
}
