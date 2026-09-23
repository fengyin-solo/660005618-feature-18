import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import ScreenView from './views/ScreenView.vue'
import './styles/global.css'

const isScreen = location.hash.startsWith('#/screen')
const Root = isScreen ? ScreenView : App
const app = createApp(Root)
app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
