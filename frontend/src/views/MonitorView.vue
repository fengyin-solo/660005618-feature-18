<template>
  <div class="app-root">
    <header class="top-bar">
      <h1>🔀 分布式任务工作流DAG编排与执行引擎</h1>
      <div class="tools">
        <el-input v-model="wfName" placeholder="工作流名称" size="small" style="width:140px"/>
        <el-button size="small" @click="create" :loading="store.loading" :disabled="locked">创建DAG</el-button>
        <el-select v-model="store.workers" size="small" style="width:100px" :disabled="locked">
          <el-option :value="1" label="1 Worker"/><el-option :value="3" label="3 Workers"/><el-option :value="5" label="5 Workers"/>
        </el-select>
        <el-select v-model="store.strategy" size="small" style="width:100px" :disabled="locked">
          <el-option value="fifo" label="FIFO"/><el-option value="priority" label="优先级"/><el-option value="max_concurrent" label="最大并发"/>
        </el-select>
        <el-button type="success" size="small" @click="run"
                   :disabled="!store.workflowDef || running || locked" :loading="store.loading">▶ 执行</el-button>

        <template v-if="screen.mySession">
          <el-tag type="warning" size="small">📺 投屏中 {{ screen.mySession.code }}</el-tag>
          <el-button size="small" @click="goScreen(screen.mySession!.code)">查看大屏</el-button>
          <el-button type="danger" size="small" plain @click="stopCast">停止投屏</el-button>
        </template>
        <el-button v-else size="small" @click="startCast">📺 开始投屏</el-button>

        <el-button size="small" text @click="contractOpen = true">字段约定</el-button>
        <IdentitySwitcher />
        <span class="ws-dot" :class="dotClass" :title="dotTitle"></span>
      </div>
    </header>

    <div v-if="lockReason" class="lock-banner">{{ lockReason }}</div>

    <div class="main-grid">
      <div class="dag-area">
        <DAGCanvas />
      </div>
      <div class="side-area">
        <LogPanel />
        <CircuitBreakerPanel />
      </div>
    </div>

    <FieldContractDialog v-model="contractOpen" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import DAGCanvas from '../components/DAGCanvas.vue'
import LogPanel from '../components/LogPanel.vue'
import CircuitBreakerPanel from '../components/CircuitBreakerPanel.vue'
import IdentitySwitcher from '../components/IdentitySwitcher.vue'
import FieldContractDialog from '../components/FieldContractDialog.vue'
import { useExecutionStore } from '../store/execution'
import { useIdentityStore } from '../store/identity'
import { useScreenStore } from '../store/screen'
import { setSurface } from '../api'

const store = useExecutionStore()
const identity = useIdentityStore()
const screen = useScreenStore()

const wfName = ref('data-pipeline')
const contractOpen = ref(false)

const running = computed(() => store.status === 'RUNNING')
const isViewer = computed(() => identity.current?.role === 'viewer')
// 投屏期间（任何角色）普通页的执行操作都被服务端锁定，取消投放后恢复
const lockReason = computed(() => {
  if (screen.mySession) return `📺 正在投屏（会话 ${screen.mySession.code}），执行操作已锁定；停止投屏后自动恢复`
  if (isViewer.value) return '👁 只读成员：仅可查看，不能触发执行或重跑'
  return ''
})
const locked = computed(() => !!screen.mySession || isViewer.value || running.value)

const dotClass = computed(() => ({
  on: store.connected,
  wait: store.connState === 'reconnecting' || store.connState === 'connecting',
}))
const dotTitle = computed(() => ({ online: '实时连接正常', reconnecting: '网络断开，自动重连并补进展中…', connecting: '连接中…', idle: '未连接' } as Record<string, string>)[store.connState])

async function create() {
  try { await store.createWorkflow(wfName.value) } catch { /* 理由已由 store 弹窗 */ }
}
async function run() {
  try { await store.run() } catch { /* 403 理由已弹窗 */ }
}
async function startCast() {
  const s = await screen.startCasting()
  if (!s) return
  await ElMessageBox.confirm(
    `投屏会话已创建（房间码 ${s.code}）。投屏期间你的执行操作将被临时锁定。\n` +
    `投屏人打开大屏：#/screen/${s.code}；其他成员可用同一房间码同时观看。`,
    '开始投屏', { confirmButtonText: '打开大屏', cancelButtonText: '留在本页' })
    .then(() => goScreen(s.code)).catch(() => {})
}
async function stopCast() {
  await screen.stopCasting()
}
function goScreen(code: string) { location.hash = `#/screen/${code}` }

async function refresh() {
  await Promise.all([screen.refreshMySession(), store.hydrate()])
}
async function onMemberChanged() {
  await refresh()
  // 以新身份重连 WS
  store.closeSocket()
  store.openSocket('page', null, () => identity.currentId)
}
onMounted(async () => {
  setSurface('page')
  await identity.loadMembers()
  await refresh()
  if (!store.workflowDef) {
    try { await store.createWorkflow('data-pipeline', true) } catch { /* viewer 403 由锁定条说明 */ }
  }
  store.openSocket('page', null, () => identity.currentId)
  window.addEventListener('member-changed', onMemberChanged)
})
onUnmounted(() => {
  store.closeSocket()
  window.removeEventListener('member-changed', onMemberChanged)
})
</script>

<style scoped>
.app-root{height:100vh;display:flex;flex-direction:column}
.top-bar{display:flex;justify-content:space-between;align-items:center;padding:10px 20px;background:#1a1a2e;border-bottom:1px solid #2a2a4a;gap:10px}
.top-bar h1{font-size:1rem;color:#bb86fc;white-space:nowrap}
.tools{display:flex;gap:6px;align-items:center}
.ws-dot{width:8px;height:8px;border-radius:50%;background:#ef4444;display:inline-block}
.ws-dot.on{background:#22c55e}.ws-dot.wait{background:#fbbf24;animation:pulse 1s infinite}
@keyframes pulse{50%{opacity:.3}}
.lock-banner{background:#fbbf2418;color:#fbbf24;font-size:12px;padding:6px 20px;border-bottom:1px solid #fbbf2433}
.main-grid{display:grid;grid-template-columns:1fr 340px;flex:1;overflow:hidden}
.dag-area{background:#0f0f23;position:relative;overflow:hidden}
.side-area{display:flex;flex-direction:column;gap:8px;padding:8px;overflow-y:auto;background:#14142b}
</style>
