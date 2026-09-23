<template>
  <canvas ref="cvs" class="dag-canvas"></canvas>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed, onBeforeUnmount, nextTick } from 'vue'
import { useExecutionStore } from '../store/execution'
import type { TaskNode } from '../types'

const props = defineProps<{ compact?: boolean }>()

const store = useExecutionStore()
const cvs = ref<HTMLCanvasElement>()

const STATUS_COLORS: Record<string, string> = {
  PENDING: '#4a5568', RUNNING: '#3182ce', SUCCESS: '#38a169', FAILED: '#e53e3e', TIMEOUT: '#d69e2e'
}

interface LaidNode extends TaskNode { x: number; y: number }

// 只读投影不含坐标：按边做 Kahn 分层布局（任何拿到只读快照的表面都能还原图形）
const laidOut = computed<{ nodes: LaidNode[]; edges: [string, string][] }>(() => {
  const nodes = store.nodes as TaskNode[]
  if (!nodes.length) return { nodes: [], edges: [] }
  if (nodes.every(n => typeof n.x === 'number' && typeof n.y === 'number')) {
    return { nodes: nodes as LaidNode[], edges: store.edges }
  }
  const indeg = new Map(nodes.map(n => [n.id, 0]))
  const adj = new Map<string, string[]>()
  for (const [u, v] of store.edges) {
    indeg.set(v, (indeg.get(v) || 0) + 1)
    adj.set(u, [...(adj.get(u) || []), v])
  }
  const layerOf = new Map<string, number>()
  let frontier = nodes.filter(n => (indeg.get(n.id) || 0) === 0).map(n => n.id)
  let d = 0
  while (frontier.length) {
    const next: string[] = []
    for (const id of frontier) {
      layerOf.set(id, d)
      for (const v of adj.get(id) || []) {
        indeg.set(v, (indeg.get(v) || 1) - 1)
        if ((indeg.get(v) || 0) === 0) next.push(v)
      }
    }
    frontier = next
    d += 1
  }
  nodes.forEach(n => { if (!layerOf.has(n.id)) layerOf.set(n.id, 0) })
  const rows = new Map<number, string[]>()
  nodes.forEach(n => {
    const layer = layerOf.get(n.id)!
    rows.set(layer, [...(rows.get(layer) || []), n.id])
  })
  return {
    nodes: nodes.map(n => {
      const layer = layerOf.get(n.id)!
      const row = rows.get(layer)!
      const idx = row.indexOf(n.id)
      const offset = row.length === 1 ? 0 : (idx - (row.length - 1) / 2) * 2.2
      return { ...n, x: 2.5 + offset, y: layer * 0.9 }
    }),
    edges: store.edges,
  }
})

function draw() {
  const c = cvs.value
  if (!c) return
  c.width = c.clientWidth; c.height = c.clientHeight
  const ctx = c.getContext('2d')!; const W = c.width, H = c.height
  ctx.fillStyle = '#0f0f23'; ctx.fillRect(0, 0, W, H)

  const { nodes, edges } = laidOut.value
  if (!nodes.length) return

  const compact = props.compact
  const scaleX = Math.min(compact ? 70 : 86, (W - 160) / 5)
  const scaleY = Math.min(compact ? 56 : 72, (H - 120) / 8)
  const rw = compact ? 104 : 120
  const rh = compact ? 38 : 44
  const nodePos: Record<string, {x:number, y:number}> = {}
  nodes.forEach(n => { nodePos[n.id] = { x: 80 + n.x * scaleX, y: compact ? 40 + n.y * scaleY : 60 + n.y * scaleY } })

  edges.forEach(([u, v]) => {
    const a = nodePos[u], b = nodePos[v]
    if (!a || !b) return
    ctx.strokeStyle = '#2a2a4a'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(a.x, a.y)
    const mx = (a.x + b.x) / 2
    ctx.bezierCurveTo(mx, a.y, mx, b.y, b.x, b.y)
    ctx.stroke()

    const angle = Math.atan2(b.y - Math.max(a.y, b.y - 20), b.x - a.x)
    const arrowSize = 8
    ctx.fillStyle = '#2a2a4a'
    ctx.beginPath()
    ctx.moveTo(b.x, b.y)
    ctx.lineTo(b.x - arrowSize * Math.cos(angle - 0.5), b.y - arrowSize * Math.sin(angle - 0.5))
    ctx.lineTo(b.x - arrowSize * Math.cos(angle + 0.5), b.y - arrowSize * Math.sin(angle + 0.5))
    ctx.fill()
  })

  nodes.forEach(n => {
    const {x, y} = nodePos[n.id]
    const color = STATUS_COLORS[n.status] || '#4a5568'
    if (n.status === 'RUNNING') {
      ctx.shadowColor = color; ctx.shadowBlur = 15
    }
    const rx = x - rw/2, ry = y - rh/2
    ctx.fillStyle = '#1a1a2e'; ctx.strokeStyle = color; ctx.lineWidth = 2
    ctx.beginPath(); roundRect(ctx, rx, ry, rw, rh, 6); ctx.fill(); ctx.stroke()
    ctx.shadowBlur = 0

    ctx.fillStyle = color
    ctx.beginPath(); ctx.moveTo(rx+6, ry); ctx.lineTo(rx+rw-6, ry); ctx.lineTo(rx+rw-6, ry+4); ctx.lineTo(rx+6, ry+4); ctx.fill()

    ctx.fillStyle = '#e0e0e0'; ctx.font = `bold ${compact ? 10 : 11}px system-ui`; ctx.textAlign = 'center'
    ctx.fillText(n.name, x, y - 2)
    ctx.fillStyle = '#888'; ctx.font = `${compact ? 8 : 9}px monospace`
    ctx.fillText(`${n.status} | 重试${n.retries}`, x, y + 13)
    ctx.textAlign = 'start'

    if (n.startTime && n.endTime) {
      ctx.font = '8px monospace'; ctx.fillStyle = '#666'
      ctx.fillText(`${(n.endTime - n.startTime).toFixed(1)}s`, rx + 4, ry + rh - 4)
    }
  })
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y); ctx.arcTo(x+w, y, x+w, y+r, r)
  ctx.lineTo(x+w, y+h-r); ctx.arcTo(x+w, y+h, x+w-r, y+h, r)
  ctx.lineTo(x+r, y+h); ctx.arcTo(x, y+h, x, y+h-r, r)
  ctx.lineTo(x, y+r); ctx.arcTo(x, y, x+r, y, r)
}

onMounted(() => { nextTick(draw); window.addEventListener('resize', draw) })
onBeforeUnmount(() => window.removeEventListener('resize', draw))
watch(() => [store.workflowDef, store.snapshot], draw, { deep: true })
</script>

<style scoped>
.dag-canvas { width: 100%; height: 100%; display: block; }
</style>
