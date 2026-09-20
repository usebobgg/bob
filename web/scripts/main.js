import { initApp } from './app.js'

initApp().catch((E) => {
  console.error('Bob could not start:', E)
})
