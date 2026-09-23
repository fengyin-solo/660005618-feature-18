<template>
  <canvas ref="cvs" class="dag-canvas"></canvas>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'
import type { DAGWorkflow, ExecutionInfo } from '@/types'

const props = defineProps<{
  workflow: DAGWorkflow | null
  execution?: ExecutionInfo | null
  scale?: number
}>()

const cvs = ref<HTMLCanvasElement>()

const STATUS_COLORS: Record<string, string> = {
  PENDING: '#4a5568', RUNNING: '#3182ce', SUCCESS: '#38a169', FAILED: '#e53e3e', TIMEOUT: '#d69e2e',
}
const STATUS_LABELS: Record<string, string> = {
  PENDING: '等待', RUNNING: '执行中', SUCCESS: '成功', FAILED: '失败', TIMEOUT: '超时',
}

function draw() {
  const c = cvs.value
  if (!c) return
  const dpr = window.devicePixelRatio || 1
  const W = c.clientWidth, H = c.clientHeight
  c.width = W * dpr; c.height = H * dpr
  const ctx = c.getContext('2d')!
  ctx.scale(dpr, dpr)
  ctx.fillStyle = '#0f0f23'
  ctx.fillRect(0, 0, W, H)

  const wf = props.workflow
  if (!wf) return

  // 计算包围盒并自动缩放到画布
  const xs = wf.nodes.map(n => n.x), ys = wf.nodes.map(n => n.y)
  const minX = Math.min(...xs) - 1.2, maxX = Math.max(...xs) + 1.2
  const minY = Math.min(...ys) - 0.9, maxY = Math.max(...ys) + 0.9
  const unit = Math.min(W / (maxX - minX), H / (maxY - minY)) * 0.92 * (props.scale || 1)
  const offX = (W - (maxX - minX) * unit) / 2 - minX * unit
  const offY = (H - (maxY - minY) * unit) / 2 - minY * unit
  const px = (x: number) => offX + x * unit
  const py = (y: number) => offY + y * unit

  const nodePos: Record<string, { x: number, y: number }> = {}
  wf.nodes.forEach(n => { nodePos[n.id] = { x: px(n.x), y: py(n.y) } })

  wf.edges.forEach(([u, v]) => {
    const a = nodePos[u], b = nodePos[v]
    if (!a || !b) return
    const active = wf.nodes.find(n => n.id === u)?.status === 'SUCCESS'
    ctx.strokeStyle = active ? 'rgba(56,161,105,.6)' : '#2a2a4a'
    ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(a.x, a.y)
    const mx = (a.x + b.x) / 2
    ctx.bezierCurveTo(mx, a.y, mx, b.y, b.x, b.y)
    ctx.stroke()

    const angle = Math.atan2(b.y - Math.max(a.y, b.y - 20), b.x - a.x)
    const arrow = 8
    ctx.fillStyle = active ? '#38a169' : '#2a2a4a'
    ctx.beginPath()
    ctx.moveTo(b.x, b.y)
    ctx.lineTo(b.x - arrow * Math.cos(angle - 0.5), b.y - arrow * Math.sin(angle - 0.5))
    ctx.lineTo(b.x - arrow * Math.cos(angle + 0.5), b.y - arrow * Math.sin(angle + 0.5))
    ctx.fill()
  })

  const rw = Math.min(130, unit * 1.05), rh = Math.min(48, unit * 0.42)
  wf.nodes.forEach(n => {
    const { x, y } = nodePos[n.id]
    const color = STATUS_COLORS[n.status] || '#4a5568'
    if (n.status === 'RUNNING') { ctx.shadowColor = color; ctx.shadowBlur = 18 }

    const rx = x - rw / 2, ry = y - rh / 2
    ctx.fillStyle = '#1a1a2e'; ctx.strokeStyle = color; ctx.lineWidth = 2
    ctx.beginPath(); roundRect(ctx, rx, ry, rw, rh, 6); ctx.fill(); ctx.stroke()
    ctx.shadowBlur = 0

    ctx.fillStyle = color
    ctx.beginPath()
    ctx.moveTo(rx + 6, ry); ctx.lineTo(rx + rw - 6, ry)
    ctx.lineTo(rx + rw - 6, ry + 4); ctx.lineTo(rx + 6, ry + 4)
    ctx.fill()

    ctx.fillStyle = '#e0e0e0'
    ctx.font = `bold ${Math.max(10, rh * 0.26)}px system-ui`
    ctx.textAlign = 'center'
    ctx.fillText(n.name, x, y - 2)
    ctx.fillStyle = '#888'
    ctx.font = `${Math.max(8, rh * 0.2)}px monospace`
    ctx.fillText(`${STATUS_LABELS[n.status] || n.status}${n.retries ? ' | 重试' + n.retries : ''}`, x, y + rh * 0.28)
    ctx.textAlign = 'start'

    if (n.startTime && n.endTime) {
      ctx.font = `${Math.max(8, rh * 0.18)}px monospace`; ctx.fillStyle = '#666'
      ctx.fillText(`${(n.endTime - n.startTime).toFixed(1)}s`, rx + 5, ry + rh - 4)
    }
  })
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r)
  ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r)
  ctx.lineTo(x + r, y + h); ctx.arcTo(x, y + h, x, y + h - r, r)
  ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r)
}

let ro: ResizeObserver | null = null
onMounted(() => {
  nextTick(draw)
  ro = new ResizeObserver(() => draw())
  if (cvs.value) ro.observe(cvs.value)
})
watch(() => [props.workflow, props.execution], draw, { deep: true })
</script>

<style scoped>
.dag-canvas { width: 100%; height: 100%; display: block; }
</style>
