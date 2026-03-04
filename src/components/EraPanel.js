import { animate } from 'animejs';

/**
 * EraPanel — overlaid era metadata display with keyboard navigation.
 *
 * Owns arrow-key navigation. Writes state.current so the p5 sketch picks up
 * the new palette on the next draw frame — no event bus required.
 *
 * anime.js animations:
 *   C — .era-content opacity cross-fade on navigation
 *   D — body backgroundColor cross-fade on navigation
 */
export class EraPanel {
  /**
   * @param {HTMLElement} el       - #era-panel container
   * @param {{ current: number }} state - shared mutable state (owned by index.js)
   * @param {Array} setlist        - imported from config/setlists.js
   */
  constructor(el, state, setlist) {
    this._el         = el;
    this._state      = state;
    this._setlist    = setlist;
    this._content    = el.querySelector('.era-content');
    this._genreEl    = el.querySelector('[data-testid="era-genre"]');
    this._titleEl    = el.querySelector('[data-testid="era-title"]');
    this._composerEl = el.querySelector('[data-testid="era-composer"]');
    this._yearEl     = el.querySelector('[data-testid="era-year"]');
    this._onKey      = this._onKey.bind(this);
  }

  mount() {
    document.addEventListener('keydown', this._onKey);
    this._updateText(this._state.current);
  }

  destroy() {
    document.removeEventListener('keydown', this._onKey);
  }

  /**
   * Navigate to a setlist index with cross-fade animation.
   * Clamps to [0, setlist.length - 1].
   */
  goTo(index) {
    const clamped = Math.max(0, Math.min(index, this._setlist.length - 1));
    if (clamped === this._state.current) return;

    // Update state and DOM immediately so tests can assert without waiting for animation
    this._state.current = clamped;
    this._updateText(clamped);

    // Reveal the panel on first navigation
    if (this._el.style.opacity !== '1') {
      this._el.style.opacity = '1';
    }

    // Animation C — visual cross-fade (cosmetic only, text already updated)
    animate(this._content, {
      opacity: [1, 0],
      duration: 180,
      ease: 'inSine',
      onComplete: () => {
        animate(this._content, {
          opacity: [0, 1],
          duration: 220,
          ease: 'outSine',
        });
      },
    });

    // Animation D — body background cross-fade
    const [r, g, b] = this._setlist[clamped].palette.bg;
    animate(document.body, {
      backgroundColor: `rgb(${r},${g},${b})`,
      duration: 600,
      ease: 'inOutSine',
    });
  }

  // ─── Private ───────────────────────────────────────────────────────────────

  _updateText(index) {
    const era = this._setlist[index];
    this._genreEl.textContent    = era.genre;
    this._titleEl.textContent    = era.title;
    this._composerEl.textContent = era.composer;
    this._yearEl.textContent     = era.year;
  }

  _onKey(e) {
    if (e.key === 'ArrowRight') this.goTo(this._state.current + 1);
    if (e.key === 'ArrowLeft')  this.goTo(this._state.current - 1);
  }
}
