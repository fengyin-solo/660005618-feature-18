<template>
  <component :is="view" :key="routeKey" />
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import MonitorView from './views/MonitorView.vue'
import ScreenView from './views/ScreenView.vue'

// 轻量 hash 路由：#/ 普通页面（完整操作），#/screen/<code> 只读大屏
const hash = ref(location.hash)
function sync() { hash.value = location.hash }
onMounted(() => window.addEventListener('hashchange', sync))
onUnmounted(() => window.removeEventListener('hashchange', sync))

const isScreen = computed(() => /^#\/screen\/[A-Z0-9]{6}/i.test(hash.value))
const view = computed(() => (isScreen.value ? ScreenView : MonitorView))
const routeKey = computed(() => (isScreen.value ? hash.value : 'monitor'))
</script>
