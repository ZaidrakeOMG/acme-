import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { registerSW } from 'virtual:pwa-register'
import { App } from './App'
import { AuthProvider } from './contexts/AuthContext'
import { usarTransporte } from './services/formularios/respuestas'
import { transporteHibrido } from './services/offline/transporteRespuestas'
import { syncEngine } from './services/syncEngine'
import './index.css'

registerSW({ immediate: true })
// P05: toda escritura de formularios pasa por el transporte híbrido (HTTP y, sin red, cola en IndexedDB).
usarTransporte(transporteHibrido)
syncEngine.iniciar()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
