import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, denyReason } from '@/api'
import { useIdentityStore } from './identity'
import { useExecutionStore } from './execution'
import type { ScreenSession } from '@/types'

export const useScreenStore = defineStore('screen', () => {
  // 我作为投屏人在普通页上的进行中会话
  const mySession = ref<ScreenSession | null>(null)
  // 大屏房间信息（presenter / watchers），仅大屏视图使用
  const room = ref<ScreenSession | null>(null)
  const endedReason = ref<string | null>(null)

  async function refreshMySession() {
    mySession.value = await api.activeScreen()
  }

  async function startCasting(): Promise<ScreenSession | null> {
    try {
      mySession.value = await api.startScreen()
      return mySession.value
    } catch (e) {
      ElMessage.error(`投屏失败：${denyReason(e).message}`)
      return null
    }
  }

  async function stopCasting(): Promise<boolean> {
    if (!mySession.value) return false
    const code = mySession.value.code
    try {
      await api.stopScreen(code)
      ElMessage.success('已结束投屏，普通页面操作权限已恢复')
      return true
    } catch (e) {
      ElMessage.error(`结束投屏失败：${denyReason(e).message}`)
      return false
    } finally {
      mySession.value = null
    }
  }

  function handleMessage(msg: any) {
    if (msg.type === 'presence' && msg.session) {
      room.value = msg.session
    } else if (msg.type === 'session_ended') {
      endedReason.value = msg.reason || 'ended'
      if (room.value) room.value = { ...room.value, status: 'stopped' }
    }
  }

  /** 进入大屏路由：连接大屏只读 WS 并挂接 presence/结束事件。 */
  function useRoom(code: string): () => void {
    resetRoom()
    const identity = useIdentityStore()
    const exec = useExecutionStore()
    exec.setScreenCode(code)
    exec.openSocket('screen', code, () => identity.currentId)
    const off = exec.onMessage(handleMessage)
    return off
  }

  function resetRoom() {
    room.value = null
    endedReason.value = null
  }

  return {
    mySession, room, endedReason,
    refreshMySession, startCasting, stopCasting,
    useRoom, resetRoom, handleMessage,
  }
})
