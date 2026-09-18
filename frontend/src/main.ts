import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { vTip } from './lib/tip'
import './styles.css'

createApp(App).use(createPinia()).directive('tip', vTip).mount('#app')
