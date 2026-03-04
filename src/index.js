// p5 and p5.sound are CDN globals loaded in index.html
import './style.css';
import { createSketch } from './sketch.js';
import { EraPanel } from './components/EraPanel.js';
import { ResultsPanel } from './components/ResultsPanel.js';
import { setlist } from './config/setlists.js';

// Shared state — owned here, passed by reference to sketch + EraPanel.
// EraPanel writes state.current; sketch reads it each draw frame.
const state = { current: 0 };

// ─── p5 sketch ───────────────────────────────────────────────────────────────
// window.p5 is the CDN global; p5.sound has already patched it
// eslint-disable-next-line no-undef
const sketchInstance = new p5(createSketch(state), document.getElementById('sketch'));

// Wire the "Joe, go!" DOM button to the sketch's audio starter
document.getElementById('start-button').addEventListener('click', () => {
  sketchInstance.startAudio();
});

// ─── Era panel ───────────────────────────────────────────────────────────────
const eraPanel = new EraPanel(
  document.getElementById('era-panel'),
  state,
  setlist,
);
eraPanel.mount();

// ─── Results panel ───────────────────────────────────────────────────────────
const resultsPanel = new ResultsPanel(document.getElementById('results-panel'));
resultsPanel.mount();

document.getElementById('results-toggle').addEventListener('click', () => {
  resultsPanel.toggle();
});
