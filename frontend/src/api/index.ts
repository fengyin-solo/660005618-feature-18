import axios from 'axios'
import type { ExecutionInfo, PresentationInfo, UserInfo } from '@/types'

export const http = axios.create({ baseURL: '' })

export const tokenStore = {
  get(): string | null { return localStorage.getItem('dag_token') },
  set(t: string) { localStorage.setItem('dag_token', t) },
  clear() { localStorage.removeItem('dag_token') },
}

http.interceptors.request.use((cfg) => {
  const t = tokenStore.get()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

export class ApiError extends Error {
  status: number
  constructor(status: number, detail: string) { super(detail); this.status = status }
}

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const detail = err?.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new ApiError(err?.response?.status || 0, detail))
  },
)

export const api = {
  async login(username: string, password: string): Promise<{ token: string; user: UserInfo }> {
    const { data } = await http.post('/api/auth/login', { username, password })
    return data
  },
  me(): Promise<UserInfo> { return http.get('/api/me').then(r => r.data) },
  contract(): Promise<Record<string, string[]>> { return http.get('/api/contract').then(r => r.data) },
  createWorkflow(name: string) { return http.post('/api/workflow', { name }).then(r => r.data) },
  run(workflowId: number, workers: number, strategy: string):
    Promise<{ seq: number; execution: ExecutionInfo }> {
    return http.post('/api/run', { workflowId, workers, strategy }).then(r => r.data)
  },
  execution(): Promise<{ seq: number; execution: ExecutionInfo }> {
    return http.get('/api/execution').then(r => r.data)
  },
  startPresentation(): Promise<{ presentation: PresentationInfo; screenToken: string; screenUrl: string }> {
    return http.post('/api/presentation/start').then(r => r.data)
  },
  screenToken(): Promise<{ presentation: PresentationInfo; screenToken: string; screenUrl: string }> {
    return http.post('/api/presentation/screen-token').then(r => r.data)
  },
  stopPresentation(): Promise<{ ok: boolean }> {
    return http.post('/api/presentation/stop').then(r => r.data)
  },
  activePresentation(): Promise<{ presentation: PresentationInfo | null }> {
    return http.get('/api/presentation/active').then(r => r.data)
  },
}
