import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // 本番でもエラーのスタックトレースを元のソースに対応させ、原因調査をしやすくする
    sourcemap: true,
  },
})
