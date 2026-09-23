import type { WsEvent } from '@/types'

type Status = 'connecting' | 'connected' | 'disconnected'

/**
 * 实时连接：
 * - 维护单调 lastSeq，重连后由服务端回放缺失事件（缺口过大时服务端下发 snapshot）；
 * - 指数退避自动重连，网络恢复后自动补上断开期间的进展；
 * - 心跳 ping 维持在线名单。
 */
export class RealtimeClient {
  private ws: WebSocket | null = null
  private token = ''
  private lastSeq = 0
  private retries = 0
  private pingTimer: number | null = null
  private closedByUser = false
  private watchPresentation = false
  private helloDone = false

  status: Status = 'disconnected'
  onEvent: (e: WsEvent) => void = () => {}
  onStatus: (s: Status) => void = () => {}

  connect(token: string, opts: { watchPresentation?: boolean; lastSeq?: number } = {}) {
    this.token = token
    this.watchPresentation = !!opts.watchPresentation
    if (typeof opts.lastSeq === 'number') this.lastSeq = opts.lastSeq
    this.closedByUser = false
    this.openSocket()
  }

  private setStatus(s: Status) { this.status = s; this.onStatus(s) }

  private openSocket() {
    this.setStatus(this.retries === 0 ? 'connecting' : 'connecting')
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(this.token)}`)
    this.ws = ws

    ws.onopen = () => {
      this.retries = 0
      this.setStatus('connected')
      this.sendHello()
      this.startPing()
    }
    ws.onmessage = (ev) => {
      try {
        const msg: WsEvent = JSON.parse(ev.data)
        if (msg.type === 'snapshot') this.lastSeq = msg.seq
        if ((msg as { seq?: number }).seq) this.lastSeq = (msg as { seq: number }).seq
        this.onEvent(msg)
      } catch { /* 忽略无法解析的帧 */ }
    }
    ws.onclose = () => {
      this.stopPing()
      this.helloDone = false
      if (this.closedByUser) { this.setStatus('disconnected'); return }
      this.setStatus('disconnected')
      // 指数退避自动重连：0.5s -> 1s -> 2s -> 4s -> 5s 封顶
      const delay = Math.min(5000, 500 * 2 ** this.retries)
      this.retries += 1
      window.setTimeout(() => { if (!this.closedByUser) this.openSocket() }, delay)
    }
    ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
  }

  private sendHello() {
    this.ws?.send(JSON.stringify({
      type: 'hello', lastSeq: this.lastSeq, watchPresentation: this.watchPresentation,
    }))
    this.helloDone = true
  }

  private startPing() {
    this.stopPing()
    this.pingTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping', at: Date.now() }))
      }
    }, 10000)
  }

  private stopPing() {
    if (this.pingTimer) { window.clearInterval(this.pingTimer); this.pingTimer = null }
  }

  close() {
    this.closedByUser = true
    this.stopPing()
    try { this.ws?.close() } catch { /* noop */ }
    this.ws = null
    this.setStatus('disconnected')
  }
}
