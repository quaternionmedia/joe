export default {
  root: 'src',
  base: '/joe',
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: '../dist',
  },
}