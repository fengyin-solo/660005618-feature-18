import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import type { Member } from '@/types'

// 演示环境：本地选择“我是谁”，请求经 X-Member-Id 头交给后端鉴权
const STORAGE_KEY = 'dag.memberId'

export const useIdentityStore = defineStore('identity', () => {
  const members = ref<Member[]>([])
  const currentId = ref<string>(localStorage.getItem(STORAGE_KEY) || 'u-alice')
  const current = ref<Member | null>(null)

  async function loadMembers() {
    const { data } = await axios.get('/api/members')
    members.value = data.members
    current.value = members.value.find(m => m.id === currentId.value) || members.value[0] || null
    if (current.value) currentId.value = current.value.id
  }

  function select(id: string) {
    currentId.value = id
    localStorage.setItem(STORAGE_KEY, id)
    current.value = members.value.find(m => m.id === id) || null
  }

  return { members, currentId, current, loadMembers, select }
})
