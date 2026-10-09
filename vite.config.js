export default {
  root: 'src',
  base: '/joe',
  server: {
    port: 3000,
    proxy: {
      // joe's own API. JOE_API_URL moves it, so a second backend -- the
      // walkthrough's, on a port of its own -- can sit beside a developer's.
      '/api': process.env.JOE_API_URL || 'http://localhost:8000',
      // qmcp's human queue, for "Answer by voice". QMCP_URL moves it.
      '/v1': process.env.QMCP_URL || 'http://localhost:3141',
    },
  },
  build: {
    outDir: '../dist',
  },
}