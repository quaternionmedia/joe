// Import a module that was installed with npm
import p5 from 'p5'
// Import a variable from a JavaScript file from the project folder
import { sketch } from './capture.js'
// Import CSS styles in JavaScript

console.log('Hello from JavaScript!')

// Initialize p5.js
// p5 requires two arguments: new p5(sketch function, target DOM element)
new p5(sketch, document.getElementById('sketch'))

// Example: update the DOM
setTimeout(() => {
  document.getElementById('input').value = 'Edit me!'
}, 2000)
