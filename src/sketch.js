import { setlist } from './config/setlists.js';

const HIST_SIZE = 125;
const STAFF_LINES = new Set([23, 27, 30, 33, 37, 44, 47, 51, 54, 57]);

/**
 * Returns the p5 instance-mode sketch function for the live FFT visualiser.
 *
 * @param {Object} state - Shared mutable state: { current: number }
 *   state.current is the active setlist index, owned by index.js.
 *   EraPanel writes it; this sketch reads it each draw frame for the palette.
 */
export function createSketch(state) {
  return (p) => {
    let fft, mic;
    let pmap = [];
    let pmaphb = [];
    const pmaph = [];

    p.setup = () => {
      p.createCanvas(p.windowWidth, p.windowHeight);
      p.textAlign(p.CENTER);
      pmap = new Float32Array(pnoDist(88, 12, 440));
    };

    p.draw = () => {
      const palette = setlist[state.current].palette;
      const [br, bg, bb] = palette.bg;
      p.background(br, bg, bb);

      if (pmaph.length > 2000) pmaph.length = 2000;

      if (!mic) return;

      fft.analyze();

      for (let k = 0; k < pmap.length; k++) {
        pmaphb[k] = fft.getEnergy(pmap[k]);
      }
      pmaph.unshift(pmaphb);
      pmaphb = [];

      const pmapL = Math.min(pmaph.length, HIST_SIZE);
      const [ar, ag, ab] = palette.accent;

      // Staff lines — fixed horizontal guides at specific piano-key pitches (n axis)
      for (let n = 0; n < 88; n++) {
        if (STAFF_LINES.has(n)) {
          p.stroke(125);
          p.strokeWeight(3);
          p.line(0, p.map(n, 0, 88, p.height - 100, 100),
                 p.width, p.map(n, 0, 88, p.height - 100, 100));
        }
      }

      // Frequency history dots
      p.noStroke();
      for (let m = 0; m < pmapL; m++) {
        for (let n = 0; n < pmaph[m].length; n++) {
          p.fill(ar, ag, ab);
          const xy = logMap(pmaph[m][n], 20, 255, 0, 10, p);
          const px = p.map(m, 0, HIST_SIZE, p.width - 100, 100);
          const py = p.map(n, 0, 88, p.height - 100, 100);
          p.ellipse(px, py, xy, xy);
        }
      }
    };

    p.windowResized = () => {
      p.resizeCanvas(p.windowWidth, p.windowHeight);
    };

    /**
     * Start microphone capture. Called from the #start-button DOM handler.
     * Exposed on the sketch instance via p so index.js can call sketch.startAudio().
     *
     * Browsers suspend the Web Audio context until an explicit resume() inside a
     * user-gesture handler. We resume here (the button click IS a user gesture),
     * then create FFT + AudioIn only after the context is running.
     */
    p.startAudio = () => {
      const P5 = p.constructor;
      p.getAudioContext().resume().then(() => {
        fft = new P5.FFT();
        mic = new P5.AudioIn();
        fft.setInput(mic);   // route mic exclusively to FFT analyser
        mic.start();
      });
    };
  };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

// dB-scale mapping: maps FFT energy to dot diameter using audio-perceptual dB scaling.
// Mimics how we perceive loudness — quiet sounds get small dots, loud sounds get large dots,
// with the growth rate matching the logarithmic nature of human hearing (dB scale).
// _vmin is the noise floor (anything at or below → 0px), _vmax is full scale (→ _omax px).
function logMap(_v, _vmin, _vmax, _omin, _omax, p) {
  if (_v <= _vmin) return _omin;
  const dB     = 20 * Math.log10(_v / _vmax);
  const dB_min = 20 * Math.log10(_vmin / _vmax);
  const norm   = (dB - dB_min) / (-dB_min);   // 0 at noise floor, 1 at full scale
  return p.map(norm, 0, 1, _omin, _omax);
}

function pnoDist(_numKeys, _split, _center) {
  const fs = [];
  for (let i = 0; i < _numKeys; i++) {
    fs[i] = Math.pow(2, (i - (_numKeys / 2 + 5)) / _split) * _center;
  }
  return fs;
}
