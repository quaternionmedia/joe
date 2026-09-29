export default {
  root: 'src',
  base: '/joe',
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
      // qmcp's human queue, for "Answer by voice". QMCP_URL moves it.
      '/v1': process.env.QMCP_URL || 'http://localhost:3141',
    },
  },
  build: {
    outDir: '../dist',
  },
}