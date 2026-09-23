<template>
  <PipelineGraph :workflow="store.execution.workflow || store.workflow" :execution="store.execution"/>
</template>

<script setup lang="ts">
import PipelineGraph from './PipelineGraph.vue'
import { useAppStore } from '../store/app'
const store = useAppStore()
</script>
