<template>
  <div class="screen-root" :class="{ idle: !running }">
    <header class="screen-header">
      <div class="title">
        <span class="live" v-if="running">● LIVE</span>
        <span class="live wait" v-else-if="reconnecting">● 重连中…</span>
        <h1>流水线执行大屏</h1>
        <span class="code">房间 {{ code }}</span>
      </div>
      <div class="meta">
        <div class="stat" v-for="s in stats" :key="s.label" :class="s.cls">
          <span class="num">{{ s.value }}</span><span class="lab">{{ s.label }}</span>
        </div>
        <div class="clock">{{ clock }}</div>
      </div>
    </header>

    <div class="screen-body">
      <div class="canvas-wrap">
        <DAGCanvas compact />
        <!-- 空闲等待遮罩：没有正在执行的任务 -->
        <div v-if="!running" class="idle-mask">
          <div class="idle-icon">⏳</div>
          <div class="idle-title">暂无正在执行的流水线</div>
          <div class="idle-sub">
            {{ store.status === 'SUCCESS' ? '上一轮执行已成功完成，等待下一次触发…'
              : store.status === 'FAILED' ? '上一轮执行失败，等待重新触发…'
              : '等待 operator 在普通页面发起执行…' }}
          </div>
        </div>
        <div v-if="reconnecting" class="net-mask">
          网络已断开，正在自动重连并补上落下的进展…
        </div>
      </div>

      <aside class="screen-side">
        <section class="logs">
          <h3>📡 最新日志</h3>
          <div class="log-lines">
            <div v-for="(l, i) in recentLogs" :key="i" class="line" :class="l.status.toLowerCase()">
              <span class="t">{{ hhmmss(l.timestamp) }}</span>
              <span class="s">{{ l.status }}</span>
              <span class="m">{{ l.message }}</span>
            </div>
            <div v-if="!recentLogs.length" class="no-log">等待日志…</div>
          </div>
        </section>
        <section class="breakers" v-if="store.breakers.length">
          <h3>⚡ 熔断器</h3>
          <div v-for="cb in activeBreakers" :key="cb.taskId" class="cb" :class="cb.state.toLowerCase()">
            <span>{{ cb.taskId }}</span><span>{{ cb.state }}</span><span>{{ cb.failureCount }}次失败</span>
          </div>
        </section>
      </aside>
    </div>

    <footer class="screen-footer">
      <div class="people">
        <span class="cast-label">投屏人</span>
        <span class="person presenter" v-if="room">
          <span class="avatar">{{ initial(room.presenter.name) }}</span>
          {{ room.presenter.name }}
          <em v-if="!room.presenterOnline" class="offline-note">（连接中断宽限中）</em>
        </span>
        <span class="cast-label watch-label">同屏观看 {{ watchers.length }}</span>
        <span v-for="w in watchers" :key="w.id" class="person watcher">
          <span class="avatar w">{{ initial(w.name) }}</span>{{ w.name }}
        </span>
      </div>
      <div class="foot-right">
        <span class="readonly-tag">🔒 只读视图 · 可见字段按约定 v1</span>
        <span class="back-link">普通页面请打开 #/ ｜ 投屏人结束投放请回到普通页操作</span>
      </div>
    </footer>

    <!-- 会话结束（投屏人取消/超时）覆盖层 -->
    <div v-if="screen.endedReason" class="ended-mask">
      <div class="ended-card">
        <div class="ended-icon">📭</div>
        <h2>本次投屏已结束</h2>
        <p>{{ endedText }}</p>
        <el-button type="primary" @click="goHome">返回普通页面</el-button>
      </div>
    </div>

    <!-- 房间码无效 -->
    <div v-if="invalid" class="ended-mask">
      <div class="ended-card">
        <div class="ended-icon">❓</div>
        <h2>投屏房间不存在或已关闭</h2>
        <el-button type="primary" @click="goHome">返回普通页面</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import DAGCanvas from '../components/DAGCanvas.vue'
import { useExecutionStore } from '../store/execution'
import { useIdentityStore } from '../store/identity'
import { useScreenStore } from '../store/screen'
import { setSurface } from '../api'

const store = useExecutionStore()
const identity = useIdentityStore()
const screen = useScreenStore()

const code = computed(() => location.hash.split('/')[2] || '')
let offRoom: (() => void) | null = null
let clockTimer: ReturnType<typeof setInterval>
const now = ref(Date.now())

const running = computed(() => store.status === 'RUNNING')
const reconnecting = computed(() => store.connState === 'reconnecting')
const room = computed(() => screen.room)
const watchers = computed(() => screen.room?.watchers || [])
// 房间码无效：后端在握手前拒绝（连接从未进入 online）
const invalid = computed(() =>
  store.connState === 'offline' && !store.everConnected && !screen.room)

const stats = computed(() => {
  const nodes = store.nodes
  const done = nodes.filter(n => n.status === 'SUCCESS').length
  const failed = nodes.filter(n => n.status === 'FAILED').length
  const r = nodes.filter(n => n.status === 'RUNNING').length
  const pending = nodes.filter(n => n.status === 'PENDING').length
  const pct = nodes.length ? Math.round((done + failed) / nodes.length * 100) : 0
  return [
    { label: '总任务', value: nodes.length, cls: '' },
    { label: '进行中', value: r, cls: 'run' },
    { label: '成功', value: done, cls: 'ok' },
    { label: '失败', value: failed, cls: 'bad' },
    { label: '等待', value: pending, cls: '' },
    { label: '进度', value: pct + '%', cls: pct === 100 && !failed ? 'ok' : '' },
  ]
})

const recentLogs = computed(() => store.logs.slice(-12).reverse())
const activeBreakers = computed(() => store.breakers.filter(cb => cb.state !== 'CLOSED' || cb.failureCount > 0))

const endedText = computed(() => ({
  stopped_by_presenter: '投屏人已取消投放，普通页面的权限与操作已恢复原样。',
  presenter_offline_timeout: '投屏人连接超时，会话已自动收档。',
  closing: '房间关闭。',
} as Record<string, string>)[screen.endedReason || ''] || '投屏会话已结束。')

const clock = computed(() => {
  const d = new Date(now.value)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
})
function hhmmss(ts: number) {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}
function initial(name: string) { return name.replace(/（.*?）/, '').slice(0, 1) }
function goHome() { location.hash = '#/' }

onMounted(async () => {
  setSurface('screen') // 大屏表面：变更类 HTTP 请求被服务端 X-Surface 闸门拒绝
  await identity.loadMembers()
  await store.hydrate()
  const off = screen.useRoom(code.value)
  offRoom = off
  clockTimer = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => {
  offRoom?.()
  store.closeSocket()
  clearInterval(clockTimer)
  setSurface('page')
})
</script>

<style scoped>
.screen-root{height:100vh;display:flex;flex-direction:column;background:#070714;color:#e8e8f0;overflow:hidden}
.screen-header{display:flex;justify-content:space-between;align-items:center;padding:18px 32px;background:linear-gradient(90deg,#12122b,#0b0b1e);border-bottom:1px solid #23234a}
.title{display:flex;align-items:center;gap:14px}
.title h1{font-size:26px;letter-spacing:2px}
.code{font-family:monospace;background:#bb86fc22;color:#c9a4ff;padding:3px 10px;border-radius:6px;font-size:15px}
.live{color:#ff4d4f;font-weight:700;font-size:15px;animation:blink 1.2s infinite}
.live.wait{color:#fbbf24;animation:none}
@keyframes blink{50%{opacity:.25}}
.meta{display:flex;gap:22px;align-items:center}
.stat{display:flex;flex-direction:column;align-items:center;min-width:64px}
.stat .num{font-size:30px;font-weight:800;font-family:'DIN',monospace}
.stat .lab{font-size:12px;color:#888}
.stat.run .num{color:#4ea1f5}.stat.ok .num{color:#3ddc84}.stat.bad .num{color:#ff5a5f}
.clock{font-size:24px;font-family:monospace;color:#a5a5c8;margin-left:10px}

.screen-body{flex:1;display:grid;grid-template-columns:1fr 420px;gap:14px;padding:14px;min-height:0}
.canvas-wrap{position:relative;background:#0c0c20;border:1px solid #1f1f42;border-radius:12px;overflow:hidden;min-height:0}
.screen-side{display:flex;flex-direction:column;gap:12px;min-height:0}
.logs{flex:1;background:#10102a;border:1px solid #1f1f42;border-radius:12px;padding:14px;display:flex;flex-direction:column;min-height:0}
.logs h3,.breakers h3{font-size:15px;color:#bb86fc;margin-bottom:10px}
.log-lines{flex:1;overflow:hidden;font-family:monospace;font-size:14px;display:flex;flex-direction:column;gap:4px}
.line{display:flex;gap:10px;padding:5px 8px;border-radius:6px;background:#ffffff06}
.line .t{color:#6b6b94}.line .s{font-weight:700;min-width:88px}
.line .m{color:#cfcfe6}
.line.running .s{color:#4ea1f5}.line.success{background:#3ddc8410}.line.success .s{color:#3ddc84}
.line.failed .s,.line.circuit_open .s{color:#ff5a5f}
.no-log{color:#555;text-align:center;margin-top:40px}
.breakers{background:#1a0f1c;border:1px solid #4a2030;border-radius:12px;padding:14px}
.cb{display:flex;justify-content:space-between;font-size:13px;padding:4px 0;color:#ff9aa2}

.idle-mask{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(7,7,20,.82);backdrop-filter:blur(2px)}
.idle-icon{font-size:72px;animation:bob 2s ease-in-out infinite}
@keyframes bob{50%{transform:translateY(-10px)}}
.idle-title{font-size:30px;margin-top:18px;color:#cfcfe6}
.idle-sub{margin-top:10px;color:#888;font-size:16px}
.net-mask{position:absolute;top:14px;left:50%;transform:translateX(-50%);background:#fbbf2422;border:1px solid #fbbf2466;color:#fbbf24;padding:8px 20px;border-radius:20px;font-size:14px}

.screen-footer{display:flex;justify-content:space-between;align-items:center;padding:12px 32px;background:#0b0b1e;border-top:1px solid #23234a}
.people{display:flex;align-items:center;gap:12px;font-size:14px}
.cast-label{color:#888}
.person{display:inline-flex;align-items:center;gap:6px}
.presenter{color:#ffd666;font-weight:700}
.avatar{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:#ffd66622;color:#ffd666;font-weight:700}
.avatar.w{background:#4ea1f522;color:#8ec5ff;font-size:12px}
.watch-label{margin-left:14px}
.watcher{color:#a5c8ff}
.offline-note{color:#888;font-size:12px;font-style:normal}
.foot-right{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.readonly-tag{font-size:13px;color:#c9a4ff}
.back-link{font-size:11px;color:#555}

.ended-mask{position:fixed;inset:0;background:rgba(4,4,12,.9);display:flex;align-items:center;justify-content:center;z-index:10}
.ended-card{background:#14142e;border:1px solid #2c2c5a;border-radius:16px;padding:40px 56px;text-align:center}
.ended-icon{font-size:56px}
.ended-card h2{margin:14px 0 8px}
.ended-card p{color:#999;margin-bottom:20px}
</style>
