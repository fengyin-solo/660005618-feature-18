import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles.css'
import App from './App.vue'
import { configureApi } from './api'

const pinia = createPinia()
configureApi({ getMemberId: () => localStorage.getItem('dag.memberId') || 'u-alice' })

const app = createApp(App)
app.use(pinia)
app.use(ElementPlus)
app.mount('#app')
