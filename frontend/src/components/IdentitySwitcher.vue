<template>
  <el-select :model-value="identity.currentId" size="small" style="width:180px"
             @change="onChange" title="切换成员身份（演示权限）">
    <template #prefix>
      <span class="role-badge" :class="identity.current?.role">
        {{ identity.current?.role === 'operator' ? '运维' : '只读' }}
      </span>
    </template>
    <el-option v-for="m in identity.members" :key="m.id" :value="m.id"
               :label="`${m.name}（${m.role === 'operator' ? '可执行' : '只读'}）`" />
  </el-select>
</template>

<script setup lang="ts">
import { useIdentityStore } from '../store/identity'
const identity = useIdentityStore()
async function onChange(id: string) {
  identity.select(id)
  // 身份切换后刷新普通页投屏锁定状态与执行快照
  window.dispatchEvent(new CustomEvent('member-changed'))
}
</script>
<style scoped>
.role-badge{font-size:9px;padding:1px 5px;border-radius:8px;margin-right:4px;font-weight:700}
.role-badge.operator{background:#22c55e22;color:#4ade80}
.role-badge.viewer{background:#fbbf2422;color:#fbbf24}
</style>
