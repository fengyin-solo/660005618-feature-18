<template>
  <div class="panel">
    <h4>📜 执行日志 <span class="hint">最近 {{ logs.length }} 条</span></h4>
    <div ref="listEl" class="log-list">
      <div v-for="(l,i) in logs" :key="i" class="log-row" :class="l.status.toLowerCase()">
        <span class="l-time">{{ fmt(l.timestamp) }}</span>
        <span class="l-status">{{ l.status }}</span>
        <span class="l-task">{{ l.taskId }}</span>
        <span class="l-msg">{{ l.message }}</span>
      </div>
      <div v-if="!logs.length" class="empty">暂无日志</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { useExecutionStore } from '../store/execution'
const store = useExecutionStore()
const logs = computed(() => store.logs.slice(-100))
const listEl = ref<HTMLElement>()
function fmt(ts: number) {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}
watch(logs, () => nextTick(() => { if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight }))
</script>
<style scoped>
.panel{background:#1a1a2e;border-radius:8px;padding:10px;border:1px solid #2a2a4a;flex:1;display:flex;flex-direction:column;min-height:0}
.panel h4{color:#bb86fc;font-size:12px;margin-bottom:6px}
.hint{color:#555;font-weight:400;margin-left:6px}
.log-list{flex:1;overflow-y:auto;font-size:10px;font-family:monospace;min-height:120px}
.log-row{display:flex;gap:6px;padding:2px 4px;border-radius:2px;margin:1px 0}
.log-row.running{background:#3182ce15}.log-row.success{color:#38a169}.log-row.failed,.log-row.circuit_open{color:#e53e3e;background:#e53e3e10}
.l-time{color:#666}.l-status{font-weight:700;min-width:72px}.l-task{color:#888;min-width:80px}.l-msg{color:#ccc}.empty{color:#4a5568}
</style>
