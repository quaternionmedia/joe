/**
 * Setlist + palette configuration.
 * Each entry defines a musical era and its visual palette.
 * To add a new era: append an object following the same shape.
 *
 * palette.bg     — canvas background colour  [r, g, b]
 * palette.accent — FFT dot / highlight colour [r, g, b]
 * palette.text   — overlay text colour        [r, g, b]
 */
export const setlist = [
  {
    id: 'placeholder',
    genre: '',
    composer: '',
    title: '',
    year: '',
    range: '',
    palette: { bg: [0, 0, 0], accent: [200, 200, 200], text: [200, 200, 200] },
  },
  {
    id: 'baroque',
    genre: 'Baroque',
    composer: 'J.S. Bach',
    title: 'The Well-Tempered Clavier, Prelude in C',
    year: '1722',
    range: '1600–1750',
    palette: { bg: [20, 18, 12], accent: [180, 160, 100], text: [220, 210, 180] },
  },
  {
    id: 'classical',
    genre: 'Classical',
    composer: 'Wolfgang Amadeus Mozart',
    title: 'Fantasy in D minor',
    year: '1782',
    range: '1730–1820',
    palette: { bg: [10, 14, 22], accent: [130, 160, 210], text: [200, 215, 240] },
  },
  {
    id: 'romantic',
    genre: 'Romantic',
    composer: 'Frédéric Chopin',
    title: 'Opus 69, Waltz No. 2',
    year: '1829',
    range: '1780–1910',
    palette: { bg: [18, 8, 14], accent: [200, 80, 120], text: [230, 180, 200] },
  },
  {
    id: 'impressionist',
    genre: 'Impressionist',
    composer: 'Claude Debussy',
    title: "Children's Corner: Doctor Gradus ad Parnassum",
    year: '1908',
    range: '1875–1925',
    palette: { bg: [8, 18, 18], accent: [80, 200, 190], text: [180, 230, 225] },
  },
  {
    id: 'ragtime',
    genre: 'Ragtime',
    composer: 'Scott Joplin',
    title: 'Easy Winners',
    year: '1901',
    range: '1895–1917',
    palette: { bg: [20, 14, 4], accent: [220, 160, 40], text: [240, 210, 140] },
  },
  {
    id: 'modern',
    genre: 'Modern',
    composer: 'George Gershwin',
    title: 'Prelude No. 2',
    year: '1926',
    range: '1890–1975',
    palette: { bg: [6, 12, 20], accent: [60, 120, 200], text: [160, 200, 240] },
  },
  {
    id: 'jazz',
    genre: 'Jazz',
    composer: 'Dave Brubeck',
    title: 'Blue Rondo à la Turk',
    year: '1959',
    range: '1920s–1970s',
    palette: { bg: [4, 4, 14], accent: [100, 80, 200], text: [180, 170, 240] },
  },
  {
    id: 'present',
    genre: 'Present',
    composer: 'Peter Kagstrom',
    title: 'Improvisation',
    year: '2016',
    range: 'right now',
    palette: { bg: [0, 0, 0], accent: [255, 255, 255], text: [255, 255, 255] },
  },
];
