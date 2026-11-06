// What a spec's page reaches for and the spec has not scripted -- joe's API, qmcp's
// queue -- answered 503, so no joe, qmcp or demo running on this machine ever
// answers a spec. playwright.config.js starts it and points the page's proxy here.
import { createServer } from 'node:http';

const port = Number(process.env.PORT || 3199);

createServer((req, res) => {
  if (req.url === '/__ready') {
    res.writeHead(200, { 'content-type': 'text/plain' }).end('ready');
    return;
  }
  res.writeHead(503, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ detail: `no backend in the specs: ${req.method} ${req.url} was not scripted` }));
}).listen(port, '127.0.0.1');
