import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 loopback explicitly so http://127.0.0.1:5174 works (by default
    // Vite follows `localhost`, which resolves to IPv6 ::1 on Windows and makes
    // the 127.0.0.1 address refuse connections).
    host: '127.0.0.1',
    port: 5174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
    },
  },
});
