<template>
  <div class="login-mask">
    <div class="login-card">
      <h2>🔀 DAG 执行监控</h2>
      <p class="sub">请登录后查看执行监控（大屏为只读视图）</p>
      <el-input v-model="username" placeholder="用户名（operator / viewer）" size="large" @keyup.enter="doLogin"/>
      <el-input v-model="password" type="password" placeholder="密码" size="large" show-password @keyup.enter="doLogin"/>
      <el-button type="primary" size="large" :loading="busy" @click="doLogin" style="width:100%">登录</el-button>
      <p class="hint">演示账号：operator/operator（可执行）、viewer/viewer（只读成员）</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/store/app'
const store = useAppStore()
const username = ref('operator')
const password = ref('operator')
const busy = ref(false)
async function doLogin() {
  busy.value = true
  await store.login(username.value, password.value)
  busy.value = false
}
</script>

<style scoped>
.login-mask{position:fixed;inset:0;background:radial-gradient(circle at 50% 30%,#1a1a3e,#0c0c1d);display:flex;align-items:center;justify-content:center;z-index:100}
.login-card{width:360px;background:#1a1a2e;border:1px solid #2a2a4a;border-radius:12px;padding:28px;display:flex;flex-direction:column;gap:14px;box-shadow:0 20px 60px #0008}
.login-card h2{color:#bb86fc;font-size:1.1rem}
.sub{color:#888;font-size:12px}
.hint{color:#555;font-size:11px;text-align:center}
</style>
