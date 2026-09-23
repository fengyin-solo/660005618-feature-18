import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, ApiError, tokenStore } from '@/api'
import { RealtimeClient } from '@/api/realtime'
import type { DAGWorkflow, ExecutionInfo, PresentationInfo, UserInfo } from '@/types'

const IDLE_EXECUTION: ExecutionInfo = {
  workflow: null, logs: [], circuitBreakers: [], completed: false, phase: 'idle',
  runSeq: 0, startedAt: null, updatedAt: null,
  stats: { total: 0, pending: 0, running: 0, success: 0, failed: 0,
           progressPercent: 0, elapsedSeconds: null },
}

export const useAppStore = defineStore('app', () => {
  const user = ref<UserInfo | null>(null)
  const workflow = ref<DAGWorkflow | null>(null)
  const execution = ref<ExecutionInfo>({ ...IDLE_EXECUTION })
  const presentation = ref<PresentationInfo | null>(null)
  const wsConnected = ref(false)
  const workers = ref(3)
  const strategy = ref('fifo')
  const loading = ref(false)
  const toast = ref<{ kind: 'error' | 'success' | 'info'; text: string } | null>(null)
  const screenEnded = ref<string | null>(null)
  const lastSeq = ref(0)

  let rt = new RealtimeClient()

  function applyExecution(seq: number, info: ExecutionInfo) {
    // 同一轮执行内按 seq 取最新；新一轮执行无条件采用
    if (info.runSeq > execution.value.runSeq || seq >= lastSeq.value) {
      lastSeq.value = seq
      execution.value = info
    }
  }

  function showToast(kind: 'error' | 'success' | 'info', text: string) {
    toast.value = { kind, text }
    window.setTimeout(() => { if (toast.value?.text === text) toast.value = null }, 5000)
  }

  function explain(err: unknown) {
    if (err instanceof ApiError) showToast('error', err.message)
    else showToast('error', (err as Error)?.message || '操作失败')
  }

  async function initSession(opts: { watchPresentation?: boolean } = {}) {
    const token = tokenStore.get()
    if (!token) return false
    try {
      user.value = await api.me()
      bindRealtime(token, opts.watchPresentation)
      const snap = await api.execution()
      applyExecution(snap.seq, snap.execution)
      presentation.value = (await api.activePresentation()).presentation
      return true
    } catch {
      tokenStore.clear()
      user.value = null
      return false
    }
  }

  function bindRealtime(token: string, watchPresentation = false, resume = false) {
    rt.close()
    rt = new RealtimeClient()
    rt.onStatus = (s) => { wsConnected.value = s === 'connected' }
    rt.onEvent = (msg) => {
      if (msg.type === 'snapshot' || msg.type === 'execution') {
        applyExecution(msg.seq, msg.data)
      } else if (msg.type === 'presence') {
        presentation.value = msg.data.presentation
      } else if (msg.type === 'presentation_end') {
        presentation.value = null
        screenEnded.value = msg.data.reason
      }
    }
    // 首次绑定（登录/大屏初始化）从 0 开始，由服务端给全量快照；
    // 只有“跟随观看投屏”重绑才沿用 lastSeq 继续接增量。
    rt.connect(token, { watchPresentation, lastSeq: resume ? lastSeq.value : 0 })
  }

  async function login(username: string, password: string) {
    try {
      const { token, user: u } = await api.login(username, password)
      tokenStore.set(token)
      user.value = u
      await initSession()
      return true
    } catch (e) {
      explain(e)
      return false
    }
  }

  function logout() {
    rt.close()
    tokenStore.clear()
    user.value = null
    workflow.value = null
    execution.value = { ...IDLE_EXECUTION }
    presentation.value = null
  }

  async function createWorkflow(name: string) {
    loading.value = true
    try {
      workflow.value = await api.createWorkflow(name)
      showToast('success', 'DAG 已创建')
    } catch (e) { explain(e) } finally { loading.value = false }
  }

  async function run() {
    if (!workflow.value) { showToast('error', '请先创建 DAG'); return }
    loading.value = true
    try {
      const r = await api.run(workflow.value.id, workers.value, strategy.value)
      applyExecution(r.seq, r.execution)
      screenEnded.value = null
      showToast('success', '流水线开始执行')
    } catch (e) { explain(e) } finally { loading.value = false }
  }

  async function startPresentation(): Promise<string | null> {
    try {
      const r = await api.startPresentation()
      return `${location.origin}/#/screen?token=${r.screenToken}`
    } catch (e) {
      explain(e)
      return null
    }
  }

  async function openScreen(): Promise<string | null> {
    try {
      const r = await api.screenToken()
      return `${location.origin}/#/screen?token=${r.screenToken}`
    } catch (e) {
      explain(e)
      return null
    }
  }

  async function stopPresentation() {
    try {
      await api.stopPresentation()
      presentation.value = null
      showToast('info', '已结束投放，普通页面权限不变')
    } catch (e) { explain(e) }
  }

  function watchPresentation() {
    const t = tokenStore.get()
    if (t) bindRealtime(t, true, true)
  }

  function consumeScreenEnd() { screenEnded.value = null }

  return {
    user, workflow, execution, presentation, wsConnected, workers, strategy, loading,
    toast, screenEnded,
    initSession, login, logout, createWorkflow, run,
    startPresentation, openScreen, stopPresentation,
    watchPresentation,
    showToast, explain, consumeScreenEnd,
  }
})
