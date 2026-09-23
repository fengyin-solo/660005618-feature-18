<template>
  <el-dialog v-model="show" title="大屏只读字段约定" width="640px">
    <div v-if="contract">
      <p class="desc">{{ contract.description }}（{{ contract.version }}，允许动作：{{ contract.actions.join('/') }}）</p>
      <el-table :data="rows" size="small" border>
        <el-table-column prop="entity" label="对象" width="150" />
        <el-table-column prop="fields" label="可见字段">
          <template #default="{ row }">
            <el-tag v-for="f in row.fields" :key="f" size="small" class="f-tag" effect="plain">{{ f }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <h4 class="hide-title">对只读成员隐藏</h4>
      <ul class="hide-list">
        <li v-for="h in contract.hidden" :key="h">{{ h }}</li>
      </ul>
      <p class="note">普通页面与大屏对同一份执行共用该投影；越权操作由服务端拦截并返回理由。</p>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import type { FieldContract } from '@/types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()
const contract = ref<FieldContract | null>(null)
const show = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})
const rows = computed(() =>
  Object.entries(contract.value?.fields || {}).map(([entity, fields]) => ({ entity, fields })))

watch(show, async open => {
  if (open && !contract.value) contract.value = await api.contract()
})
</script>
<style scoped>
.desc{color:#bbb;font-size:13px;margin-bottom:10px}
.f-tag{margin:2px}
.hide-title{margin:12px 0 6px;color:#f87171;font-size:13px}
.hide-list{padding-left:18px;color:#999;font-size:12px}
.note{margin-top:10px;color:#666;font-size:12px}
</style>
