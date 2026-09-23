<template>
  <LoginCard v-if="!store.user" />
  <div v-else class="app-root">
    <header class="top-bar">
      <h1>🔀 分布式任务工作流DAG编排与执行引擎</h1>
      <div class="tools">
        <el-input v-model="wfName" placeholder="工作流名称" size="small" style="width:150px"/>
        <el-button size="small" @click="store.createWorkflow(wfName)" :loading="store.loading"
                   :disabled="!canWrite" :title="writeTip">创建DAG</el-button>
        <el-select v-model="store.workers" size="small" style="width:96px" :disabled="!canWrite">
          <el-option :value="1" label="1 Worker"/><el-option :value="3" label="3 Workers"/><el-option :value="5" label="5 Workers"/>
        </el-select>
        <el-select v-model="store.strategy" size="small" style="width:96px" :disabled="!canWrite">
          <el-option value="fifo" label="FIFO"/><el-option value="priority" label="优先级"/><el-option value="max_concurrent" label="最大并发"/>
        </el-select>
        <el-button type="success" size="small" @click="store.run()" :disabled="!canWrite || !store.workflow"
                   :loading="store.loading" :title="writeTip">▶ 执行/重跑</el-button>

        <el-divider direction="vertical"/>

        <el-button type="warning" plain size="small" @click="startCast" v-if="!store.presentation">📺 投屏到大屏</el-button>
        <template v-else>
          <el-button type="primary" plain size="small" @click="openScreen">🔗 打开大屏</el-button>
          <el-button type="danger" plain size="small" @click="store.stopPresentation()"
                     v-if="isPresenter">结束投放</el-button>
          <el-button text size="small" @click="store.watchPresentation()"
                     v-else>👀 跟随观看（{{ store.presentation.viewerCount }}人）</el-button>
        </template>

        <el-divider direction="vertical"/>
        <span class="ws-dot" :class="{on:store.wsConnected}" :title="store.wsConnected ? '实时连接正常' : '已断开，自动重连中'"></span>
        <el-dropdown trigger="click" @command="onUser">
          <span class="user-chip">
            {{ store.user.displayName }}
            <el-tag size="small" :type="canWrite ? 'success' : 'info'">{{ store.user.roleLabel }}</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- 只读 / 投屏提示条 -->
    <div class="notice-bar" v-if="!canWrite">
      🔒 当前为只读成员视图：可以查看全部进展与日志，但不能创建、执行或重跑
    </div>
    <div class="notice-bar casting" v-else-if="store.presentation">
      📺 {{ isPresenter ? '你' : store.presentation.presenter.displayName + ' ' }}正在投屏，
      大屏为只读视图（{{ store.presentation.members.length }} 人在线）；普通页面权限保持不变
    </div>

    <!-- 越权操作原因浮层（服务端拒绝的请求会通过 toast 展示理由） -->
    <Transition name="toast">
      <div v-if="store.toast" class="toast" :class="store.toast.kind">{{ store.toast.text }}</div>
    </Transition>

    <div class="main-grid">
      <div class="dag-area">
        <DAGCanvas />
      </div>
      <div class="side-area">
        <LogPanel />
        <CircuitBreakerPanel />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import DAGCanvas from './components/DAGCanvas.vue'
import LogPanel from './components/LogPanel.vue'
import CircuitBreakerPanel from './components/CircuitBreakerPanel.vue'
import LoginCard from './components/LoginCard.vue'
import { useAppStore } from './store/app'

const store = useAppStore()
const wfName = ref('data-pipeline')

const canWrite = computed(() => !!store.user?.canWrite)
const isPresenter = computed(() =>
  store.presentation?.presenter.username === store.user?.username)
const writeTip = computed(() =>
  canWrite.value ? '' : '只读成员没有执行/重跑权限，仅大屏之外的普通页面可操作')

async function startCast() {
  const url = await store.startPresentation()
  if (url) window.open(url, '_blank')
}
function openScreen() {
  store.openScreen().then(url => url && window.open(url, '_blank'))
}
function onUser(cmd: string) { if (cmd === 'logout') store.logout() }

onMounted(async () => { await store.initSession() })
</script>

<style>
.app-root{height:100vh;display:flex;flex-direction:column}
.top-bar{display:flex;justify-content:space-between;align-items:center;padding:10px 20px;background:#1a1a2e;border-bottom:1px solid #2a2a4a}
.top-bar h1{font-size:1rem;color:#bb86fc}
.tools{display:flex;gap:6px;align-items:center}
.ws-dot{width:8px;height:8px;border-radius:50%;background:#ef4444}.ws-dot.on{background:#22c55e}
.user-chip{display:inline-flex;align-items:center;gap:6px;color:#cfcfe8;font-size:12px;cursor:pointer}
.notice-bar{padding:6px 20px;font-size:12px;color:#fbbf24;background:#3a2f10;border-bottom:1px solid #5a4710}
.notice-bar.casting{color:#93c5fd;background:#10223a;border-bottom-color:#1e3a5f}
.main-grid{display:grid;grid-template-columns:1fr 320px;flex:1;overflow:hidden}
.dag-area{background:#0f0f23;position:relative;overflow:hidden}
.side-area{display:flex;flex-direction:column;gap:8px;padding:8px;overflow-y:auto;background:#14142b}
.toast{position:fixed;top:64px;left:50%;transform:translateX(-50%);z-index:200;padding:10px 18px;border-radius:8px;font-size:13px;box-shadow:0 8px 30px #000a;max-width:640px}
.toast.error{background:#4a1518;border:1px solid #ef444466;color:#fecaca}
.toast.success{background:#14361f;border:1px solid #22c55e66;color:#bbf7d0}
.toast.info{background:#1e293b;border:1px solid #60a5fa66;color:#bfdbfe}
.toast-enter-active,.toast-leave-active{transition:all .25s}.toast-enter-from,.toast-leave-to{opacity:0;transform:translate(-50%,-8px)}
</style>
