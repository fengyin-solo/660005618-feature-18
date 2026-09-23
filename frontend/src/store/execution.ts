import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AxiosError } from 'axios'
import { api, denyReason } from '@/api'
import type { DAGWorkflowDef, Snapshot } from '@/types'

type ConnState = 'idle' | 'connecting' | 'online' | 'reconnecting' | 'offline'

export const useExecutionStore = defineStore('execution', () => {
  const loading = ref(false)
  const workflowDef = ref<DAGWorkflowDef | null>(null) // DAG 定义（创建后、未执行前用于画布）
  const snapshot = ref<Snapshot | null>(null)
  const workers = ref(3)
  const strategy = ref('fifo')

  const connState = ref<ConnState>('idle')
  const lastRecovered = ref(0)
  const lastCloseCode = ref<number | null>(null)
  // 本次 openSocket 之后是否曾成功上线（用于区分“房间无效”与“中途断线”）
  const everConnected = ref(false)

  let ws: WebSocket | null = null
  let surface: 'page' | 'screen' = 'page'
  let memberId = 'u-alice'
  let closedByUs = false
  let retries = 0
  let pingTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  const connected = computed(() => connState.value === 'online')
  const status = computed(() => snapshot.value?.status ?? 'IDLE')
  const nodes = computed(() => snapshot.value?.nodes ?? workflowDef.value?.nodes ?? [])
  const edges = computed(() => snapshot.value?.edges ?? workflowDef.value?.edges ?? [])
  const logs = computed(() => snapshot.value?.logs ?? [])
  const breakers = computed(() => snapshot.value?.circuitBreakers ?? [])
  const runId = computed(() => snapshot.value?.run?.runId ?? null)
  const seq = computed(() => snapshot.value?.seq ?? 0)

  function applySnapshot(s: Snapshot) {
    snapshot.value = s
  }

  // 增量事件合并（断线重放的一串事件也能立即还原现场）
  function mergeEvent(prev: Snapshot, msg: any): Snapshot {
    if (msg.seq <= prev.seq) return prev
    const s: Snapshot = { ...prev, seq: msg.seq }
    if (msg.kind === 'node_update' && msg.node) {
      s.nodes = s.nodes.map(n => n.id === msg.node.id ? { ...n, ...msg.node } : n)
    } else if (msg.kind === 'log' && msg.log) {
      s.logs = prev.logs.some(l => l.timestamp === msg.log.timestamp && l.message === msg.log.message)
        ? prev.logs
        : [...prev.logs.slice(-499), msg.log]
    } else if (msg.kind === 'breaker' && msg.breaker) {
      s.circuitBreakers = prev.circuitBreakers.some(cb => cb.taskId === msg.breaker.taskId)
        ? prev.circuitBreakers.map(cb => cb.taskId === msg.breaker.taskId ? msg.breaker : cb)
        : [...prev.circuitBreakers, msg.breaker]
    } else if (msg.kind === 'run_status') {
      s.status = msg.status
      s.completed = msg.status === 'SUCCESS' || msg.status === 'FAILED'
      s.run = s.run ? { ...s.run, status: msg.status } : s.run
    }
    return s
  }

  function openSocket(surface_: 'page' | 'screen', code: string | null, getMemberId: () => string) {
    surface = surface_
    memberId = getMemberId()
    closedByUs = false
    retries = 0
    everConnected.value = false
    lastCloseCode.value = null
    connState.value = 'connecting'
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const path = code
      ? `/ws/screen?code=${encodeURIComponent(code)}&member_id=${encodeURIComponent(memberId)}`
      : `/ws?member_id=${encodeURIComponent(memberId)}`
    ws = new WebSocket(`${proto}://${location.host}${path}`)

    ws.onopen = () => {
      connState.value = 'online'
      everConnected.value = true
      retries = 0
      // hello：带上当前 runId / lastSeq，让服务端补断线期间落下的进展
      ws?.send(JSON.stringify({
        type: 'hello',
        runId: runId.value,
        lastSeq: snapshot.value ? seq.value : -1,
      }))
      if (pingTimer) clearInterval(pingTimer)
      pingTimer = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, 10_000)
    }

    ws.onmessage = (e) => {
      let msg: any
      try { msg = JSON.parse(e.data) } catch { return }
      if (msg.type === 'snapshot') {
        const prevSeq = seq.value
        applySnapshot(msg as Snapshot)
        if (connState.value === 'reconnecting' && msg.seq > prevSeq) {
          lastRecovered.value = msg.seq - prevSeq
          ElMessage.success(`网络已恢复，补回 ${msg.seq - prevSeq} 条进展`)
        }
        if (connState.value === 'reconnecting') connState.value = 'online'
      } else if (msg.type === 'event') {
        // 增量事件立即合并；权威状态仍以随后到达的 snapshot 对齐
        if (snapshot.value && msg.runId === runId.value && msg.seq > seq.value) {
          snapshot.value = mergeEvent(snapshot.value, msg)
        }
      }
      // presence / session_ended / pong 由 screen store 挂接处理
      onMessageHooks.forEach(fn => fn(msg))
    }

    ws.onclose = (ev) => {
      lastCloseCode.value = ev.code
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
      if (closedByUs) { connState.value = 'idle'; return }
      // 握手前被服务端拒绝（4401 身份未知 / 4404 房间不存在）表现为 1006，
      // 且从未上线：不做无意义重连，交由界面提示
      if (!everConnected.value || ev.code === 4401 || ev.code === 4404) {
        connState.value = 'offline'
        return
      }
      scheduleReconnect()
    }
    ws.onerror = () => { ws?.close() }
  }

  function scheduleReconnect() {
    connState.value = 'reconnecting'
    const delay = Math.min(1000 * 2 ** retries, 15_000) // 指数退避，上限 15s
    retries += 1
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(() => {
      const c = surface === 'screen' ? screenCode : null
      openSocket(surface, c, () => memberId)
    }, delay)
  }

  let screenCode: string | null = null
  function setScreenCode(code: string | null) { screenCode = code }

  const onMessageHooks = new Set<(msg: any) => void>()
  function onMessage(fn: (msg: any) => void) {
    onMessageHooks.add(fn)
    return () => onMessageHooks.delete(fn)
  }

  function closeSocket() {
    closedByUs = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (pingTimer) clearInterval(pingTimer)
    ws?.close()
    ws = null
    connState.value = 'idle'
  }

  // 首次进入也用 HTTP 兜底拿一次，避免 WS 握手期间空白
  async function hydrate() {
    try { applySnapshot(await api.state()) } catch { /* 等 WS 快照 */ }
  }

  async function createWorkflow(name: string, silent = false) {
    loading.value = true
    try {
      workflowDef.value = await api.createWorkflow(name)
    } catch (e) {
      // silent=true 用于页面初始化：viewer 的 403 由锁定条说明，不再弹错误条
      if (!silent) ElMessage.error(`创建被拒绝：${denyReason(e).message}`)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function run() {
    if (!workflowDef.value) return
    loading.value = true
    try {
      const s = await api.run(workflowDef.value.id, workers.value, strategy.value)
      applySnapshot(s)
    } catch (e) {
      const ax = e as AxiosError
      // 越权操作被挡下（viewer / 大屏 / 投屏锁定）或 409 执行中：都展示服务端理由
      const reason = denyReason(e)
      if (ax.response?.status === 409) ElMessage.info(reason.message)
      else ElMessage.warning(`无法执行：${reason.message}`)
      throw e
    } finally {
      loading.value = false
    }
  }

  return {
    loading, snapshot, workflowDef, workers, strategy,
    connState, connected, lastRecovered, lastCloseCode, everConnected,
    status, nodes, edges, logs, breakers, runId, seq,
    openSocket, closeSocket, hydrate, setScreenCode, onMessage,
    createWorkflow, run,
  }
})
