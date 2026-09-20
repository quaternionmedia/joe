import { setlist } from './config/setlists.js';

const HIST_SIZE   = 125;
const TRANSPORT_H = 48;   // must match MainCanvas.js TRANSPORT_H
const LABEL_W     = 28;   // must match MainCanvas.js LABEL_W

// C-note piano-key indices (key = MIDI - 20) matching MainCanvas guide lines:
// C1=4, C2=16, C3=28, C4=40 (middle C), C5=52, C6=64, C7=76
const STAFF_LINES = new Set([4, 16, 28, 40, 52, 64, 76]);

/**
 * Returns the p5 instance-mode sketch function for the live FFT visualiser.
 *
 * Coordinate system is aligned with MainCanvas so staff lines, dot history,
 * and the playhead hairline share the same pixel rows/columns:
 *
 *   Y: key n=0 (A0)  → y = height - TRANSPORT_H  (bottom of draw area)
 *      key n=87 (B7) → y = 0                       (top)
 *   X: m=0 (now)     → x = width                   (right edge = MainCanvas rightEdge)
 *      m=HIST_SIZE   → x = LABEL_W                  (left label margin)
 *
 * @param {Object} state - Shared mutable state: { current: number }
 */
export function createSketch(state) {
  return (p) => {
    let fft, mic;
    let _audioSrcNode = null;   // MediaElementAudioSourceNode for playback FFT
    let pmap = [];
    let pmaphb = [];
    const pmaph = [];
    let _playheadX = -1;   // pixel X of playhead hairline; -1 = hidden

    p.setup = () => {
      p.createCanvas(p.windowWidth, p.windowHeight);
      pmap = new Float32Array(pnoDist(88, 12, 440));
    };

    p.draw = () => {
      const palette = setlist[state.current].palette;
      const [br, bg, bb] = palette.bg;
      p.background(br, bg, bb);

      if (pmaph.length > 2000) pmaph.length = 2000;

      const drawBottom = p.height - TRANSPORT_H;

      // ── Staff lines: C notes, aligned with MainCanvas C-note guides ───────
      p.noFill();
      p.strokeWeight(0.5);
      for (const n of STAFF_LINES) {
        const py = (87 - n) / 87 * drawBottom;
        p.stroke(125, 125, 125, 55);
        p.line(LABEL_W, py, p.width, py);
      }

      // ── FFT dot history (while mic is active OR audio is routed through FFT)
      if (fft && (mic || _audioSrcNode)) {
        fft.analyze();

        for (let k = 0; k < pmap.length; k++) {
          pmaphb[k] = fft.getEnergy(pmap[k]);
        }
        pmaph.unshift(pmaphb);
        if (p.onFrame) p.onFrame(pmaphb); // emit before clearing
        pmaphb = [];

        const pmapL = Math.min(pmaph.length, HIST_SIZE);
        const [ar, ag, ab] = palette.accent;

        p.noStroke();
        for (let m = 0; m < pmapL; m++) {
          for (let n = 0; n < pmaph[m].length; n++) {
            const xy = logMap(pmaph[m][n], 20, 255, 0, 10, p);
            if (xy <= 0) continue;
            p.fill(ar, ag, ab);
            // X: m=0 (now) at right edge, m=HIST_SIZE (oldest) at LABEL_W
            const px = p.map(m, 0, HIST_SIZE, p.width, LABEL_W);
            // Y: n=0 (A0) at drawBottom, n=87 (B7) at 0  — matches MainCanvas
            const py = (87 - n) / 87 * drawBottom;
            p.ellipse(px, py, xy, xy);
          }
        }
      }

      // ── Playhead hairline (results-mode, driven by Transport via index.js) ─
      if (_playheadX >= LABEL_W) {
        p.stroke(255, 255, 255, 70);
        p.strokeWeight(1);
        p.noFill();
        p.line(_playheadX, 0, _playheadX, drawBottom);
      }
    };

    p.windowResized = () => {
      p.resizeCanvas(p.windowWidth, p.windowHeight);
    };

    /**
     * Set playhead pixel X for results-mode sync with Transport playback.
     * Called from index.js each rAF frame while audio plays.  Pass -1 to hide.
     */
    p.setPlayheadX = (x) => { _playheadX = x; };

    /**
     * Start microphone capture.  The button click IS the required user gesture
     * that allows AudioContext.resume() to succeed.
     */
    p.startAudio = () => {
      const P5 = p.constructor;
      p.getAudioContext().resume().then(() => {
        fft = new P5.FFT();
        mic = new P5.AudioIn();
        fft.setInput(mic);   // route mic exclusively to FFT analyser
        mic.start();
        _playheadX = -1;     // hide results playhead while live
      });
    };

    /** Stop microphone capture and suspend the Web Audio context. */
    p.stopAudio = () => {
      if (mic) { mic.stop(); mic = null; }
      fft = null;
      p.getAudioContext().suspend();
    };

    /**
     * Route an HTMLAudioElement through the p5 FFT analyser so that
     * audio playback shows up in the live FFT dots.
     * Safe to call multiple times with the same element (no-op after first).
     * @param {HTMLAudioElement} audioEl
     */
    p.connectAudioSource = (audioEl) => {
      if (!fft) return;
      // Each audio element may only have one MediaElementSourceNode —
      // reuse it if already created (stored on the element itself).
      if (!audioEl._p5SrcNode) {
        const ctx = p.getAudioContext();
        audioEl._p5SrcNode = ctx.createMediaElementSource(audioEl);
      }
      if (_audioSrcNode !== audioEl._p5SrcNode) {
        if (_audioSrcNode) _audioSrcNode.disconnect();
        _audioSrcNode = audioEl._p5SrcNode;
        // Connect: audioEl → FFT analyser → destination (so we still hear it)
        _audioSrcNode.connect(fft.analyser);
        fft.analyser.connect(p.getAudioContext().destination);
      }
    };

    /** Disconnect the audio element from the FFT analyser. */
    p.disconnectAudioSource = () => {
      if (_audioSrcNode) {
        _audioSrcNode.disconnect();
        _audioSrcNode = null;
      }
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
