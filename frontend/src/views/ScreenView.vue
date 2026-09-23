<template>
  <div class="screen-root" @click="requestFullscreen" :class="{ dim: !!store.screenEnded }">
    <!-- 顶部状态条 -->
    <header class="screen-header">
      <div class="brand">📺 执行大屏 · 只读</div>
      <div class="phase" :class="phase">
        <span class="phase-dot"></span>
        {{ phaseText }}
      </div>
      <div class="conn">
        <span class="ws-dot" :class="{ on: store.wsConnected }"></span>
        {{ store.wsConnected ? '实时连接正常' : '网络断开，正在自动重连…' }}
      </div>
    </header>

    <!-- 统计条 -->
    <div class="stat-bar">
      <div class="stat"><b>{{ stats.total }}</b><span>任务总数</span></div>
      <div class="stat running"><b>{{ stats.running }}</b><span>执行中</span></div>
      <div class="stat pending"><b>{{ stats.pending }}</b><span>等待中</span></div>
      <div class="stat success"><b>{{ stats.success }}</b><span>已成功</span></div>
      <div class="stat failed" v-if="stats.failed"><b>{{ stats.failed }}</b><span>失败重试</span></div>
      <div class="progress-wrap">
        <div class="progress"><div class="progress-fill" :style="{ width: stats.progressPercent + '%' }"></div></div>
        <span class="progress-text">{{ stats.progressPercent }}% · 用时 {{ elapsed }}</span>
      </div>
    </div>

    <div class="screen-body">
      <!-- 左：流水线图 -->
      <div class="graph-panel">
        <div v-if="isIdle" class="waiting">
          <div class="spinner"></div>
          <div class="wait-title">暂无正在执行的任务</div>
          <div class="wait-sub">大屏已就绪，等待流水线发起执行后自动展示进展…</div>
          <div v-if="lastRunText" class="wait-last">{{ lastRunText }}</div>
        </div>
        <PipelineGraph v-else :workflow="store.execution.workflow" :execution="store.execution" :scale="0.96"/>
      </div>

      <!-- 右：日志 + 熔断 + 名单 -->
      <aside class="right-panel">
        <section class="box log-box">
          <h4>📜 最近日志</h4>
          <div v-if="!logs.length" class="empty">暂无日志</div>
          <div v-for="(l,i) in logs.slice(-12)" :key="i" class="log-row" :class="l.status.toLowerCase()">
            <span class="l-status">{{ l.status }}</span>
            <span class="l-msg">{{ l.message }}</span>
          </div>
        </section>
        <section class="box" v-if="breakers.length">
          <h4>⚡ 熔断</h4>
          <div v-for="cb in breakers" :key="cb.taskId" class="cb-row" :class="cb.state.toLowerCase()">
            {{ cb.taskId }} · {{ cb.state }} · {{ cb.failureCount }}次失败
          </div>
        </section>
        <section class="box presence-box">
          <h4>👥 投屏现场 <span class="who">投屏人：{{ presenterName }}</span></h4>
          <div class="members">
            <span v-for="m in members" :key="m.username" class="member" :class="m.role">
              <i class="m-dot"></i>{{ m.displayName }}
              <em v-if="m.username === presenterUser">（投屏中）</em>
            </span>
          </div>
        </section>
      </aside>
    </div>

    <footer class="screen-footer">
      <span>本视图为只读：不可触发执行或重跑，操作请在普通页面进行</span>
      <span v-if="store.user">当前凭证：{{ store.user.displayName }} · 大屏只读令牌</span>
    </footer>

    <!-- 无效 / 已失效凭证 -->
    <div v-if="initError" class="end-mask">
      <div class="end-card">
        <div class="end-icon">🔐</div>
        <h3>无法打开大屏</h3>
        <p>{{ initError }}</p>
        <p class="end-sub">请由投屏成员从普通页面重新发起投放，获取有效的大屏地址。</p>
      </div>
    </div>

    <!-- 投屏结束遮罩 -->
    <div v-if="store.screenEnded" class="end-mask">
      <div class="end-card">
        <div class="end-icon">📴</div>
        <h3>投屏已结束</h3>
        <p>{{ store.screenEnded }}</p>
        <p class="end-sub">大屏只读令牌已失效，普通页面的权限与操作不受影响。</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PipelineGraph from '@/components/PipelineGraph.vue'
import { useAppStore } from '@/store/app'
import { api, tokenStore } from '@/api'

const store = useAppStore()
const initError = ref('')
const stats = computed(() => store.execution.stats)
const logs = computed(() => store.execution.logs)
const breakers = computed(() => store.execution.circuitBreakers)
const phase = computed(() => store.execution.phase)
const isIdle = computed(() => phase.value !== 'running')

const phaseText = computed(() => {
  if (phase.value === 'running') return `流水线执行中 · 第 ${store.execution.runSeq} 次执行`
  if (phase.value === 'completed') return '上次执行已完成 · 等待下一次执行'
  return '空闲中 · 等待任务'
})
const elapsed = computed(() =>
  stats.value.elapsedSeconds == null ? '—' : `${stats.value.elapsedSeconds.toFixed(1)}s`)
const lastRunText = computed(() => {
  if (phase.value === 'completed')
    return `上次执行结果：成功 ${stats.value.success}/${stats.value.total}（用时 ${elapsed.value}）`
  return ''
})

const presenterName = computed(() => store.presentation?.presenter.displayName || '—')
const presenterUser = computed(() => store.presentation?.presenter.username || '')
const members = computed(() => store.presentation?.members || [])

function requestFullscreen() {
  // 单击页面即可进入全屏（浏览器要求用户手势），忽略非 HTTPS 等异常
  document.documentElement.requestFullscreen?.().catch(() => {})
}

onMounted(async () => {
  const token = new URLSearchParams(location.hash.split('?')[1] || '').get('token')
  if (!token) { initError.value = '大屏地址缺少投屏令牌（token）。'; return }
  tokenStore.set(token)
  try {
    // 大屏必须使用受限只读令牌，防止有人把普通页面令牌拼到大屏地址上
    const me = await api.me()
    if (me.scope !== 'screen') {
      initError.value = '该凭证不是大屏只读令牌，请使用「投屏到大屏」生成的地址。'
      return
    }
    await store.initSession()
  } catch (e) {
    initError.value = (e as Error).message || '投屏令牌无效或已过期。'
  }
})
</script>

<style scoped>
.screen-root{height:100vh;display:flex;flex-direction:column;background:linear-gradient(160deg,#0d0d22,#07071a);color:#e6e6f5;cursor:default;transition:opacity .3s}
.screen-root.dim{opacity:.35;pointer-events:none}
.screen-header{display:flex;justify-content:space-between;align-items:center;padding:18px 28px;border-bottom:1px solid #20204a;background:#10102ecc}
.brand{font-size:22px;font-weight:700;color:#bb86fc;letter-spacing:1px}
.phase{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:600}
.phase-dot{width:12px;height:12px;border-radius:50%;background:#666}
.phase.running .phase-dot{background:#3182ce;box-shadow:0 0 12px #3182ce;animation:pulse 1.2s infinite}
.phase.completed .phase-dot{background:#38a169}
.phase.idle .phase-dot{background:#6b7280}
@keyframes pulse{50%{opacity:.35}}
.conn{display:flex;align-items:center;gap:8px;font-size:14px;color:#9aa}
.ws-dot{width:10px;height:10px;border-radius:50%;background:#ef4444}.ws-dot.on{background:#22c55e;box-shadow:0 0 8px #22c55e}

.stat-bar{display:flex;align-items:center;gap:22px;padding:16px 28px;background:#0d0d28;border-bottom:1px solid #1c1c40}
.stat{display:flex;flex-direction:column;align-items:center;min-width:86px;font-size:13px;color:#8a8ab0}
.stat b{font-size:30px;color:#e6e6f5;line-height:1.1}
.stat.running b{color:#60a5fa}.stat.pending b{color:#9ca3af}.stat.success b{color:#34d399}.stat.failed b{color:#f87171}
.progress-wrap{flex:1;display:flex;flex-direction:column;gap:6px}
.progress{height:12px;border-radius:6px;background:#1c1c3a;overflow:hidden}
.progress-fill{height:100%;background:linear-gradient(90deg,#3182ce,#34d399);transition:width .4s}
.progress-text{font-size:13px;color:#8a8ab0;text-align:right}

.screen-body{flex:1;display:grid;grid-template-columns:1fr 380px;gap:14px;padding:14px;min-height:0}
.graph-panel{position:relative;background:#0f0f23;border:1px solid #20204a;border-radius:12px;overflow:hidden;min-height:0}
.right-panel{display:flex;flex-direction:column;gap:14px;min-height:0}
.box{background:#141432;border:1px solid #242450;border-radius:12px;padding:14px}
.box h4{font-size:14px;color:#bb86fc;margin-bottom:10px}
.log-box{flex:1;min-height:0;overflow-y:auto}
.log-row{font-family:monospace;font-size:13px;padding:5px 6px;border-radius:4px;margin:2px 0}
.log-row.running{background:#3182ce15}.log-row.success{color:#34d399}.log-row.failed{color:#f87171;background:#e53e3e12}.log-row.circuit_open{color:#fbbf24}
.l-status{font-weight:700;margin-right:8px}
.cb-row{font-size:13px;padding:4px;color:#fbbf24}
.presence-box .who{color:#8a8ab0;font-weight:400;font-size:12px;margin-left:8px}
.members{display:flex;flex-wrap:wrap;gap:8px}
.member{display:inline-flex;align-items:center;gap:6px;background:#1d1d45;border:1px solid #2f2f66;border-radius:999px;padding:5px 12px;font-size:13px}
.m-dot{width:7px;height:7px;border-radius:50%;background:#60a5fa}
.member.operator .m-dot{background:#fbbf24}.member.viewer .m-dot{background:#60a5fa}
.member em{color:#8a8ab0;font-style:normal;font-size:11px}
.empty{color:#555;font-size:13px}

.waiting{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:#9aa0c0}
.spinner{width:54px;height:54px;border-radius:50%;border:4px solid #232355;border-top-color:#bb86fc;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.wait-title{font-size:30px;font-weight:700;color:#c8c8ee}
.wait-sub{font-size:16px;color:#7c82a8}
.wait-last{margin-top:10px;font-size:14px;color:#5fbf96;background:#173a2c55;padding:8px 16px;border-radius:8px}

.screen-footer{display:flex;justify-content:space-between;padding:10px 28px;border-top:1px solid #1c1c40;color:#6b7094;font-size:12px;background:#0c0c24}

.end-mask{position:fixed;inset:0;background:#07071af2;display:flex;align-items:center;justify-content:center;z-index:50}
.end-card{background:#161636;border:1px solid #2c2c60;border-radius:16px;padding:44px 56px;text-align:center;max-width:520px}
.end-icon{font-size:52px;margin-bottom:12px}
.end-card h3{font-size:24px;color:#e6e6f5;margin-bottom:12px}
.end-card p{color:#aab;font-size:15px;line-height:1.6}
.end-sub{margin-top:10px;color:#777;font-size:13px}
</style>
