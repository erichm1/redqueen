/* Runs the hellgate: shows "Accessing..." for the configured delay, then opens the app. */
(function () {
  'use strict';
  var stage = document.querySelector('[data-portal]');
  if (!stage) return;
  var delay = parseInt(stage.dataset.delay, 10) || 5000;
  var destination = stage.dataset.destination || '/';
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  stage.style.setProperty('--delay', (delay / 1000) + 's');   // the progress bar takes exactly as long as the wait

  // WebGL vortex if available; otherwise the CSS portal underneath stays visible
  var canvas = document.getElementById('gate-canvas');
  import(stage.dataset.module).then(function (mod) {
    mod.startGate(canvas, { delay: delay, reduced: reduced });
    stage.classList.add('gl-on');
  }).catch(function (err) {
    if (window.console) console.info('WebGL gate unavailable, using the CSS portal:', err && err.message);
  });

  // the gate swallows the screen in the last moments, then the app opens
  if (!reduced) setTimeout(function () { stage.classList.add('entering'); }, Math.max(delay - 900, 0));
  setTimeout(function () { window.location.replace(destination); }, delay);
})();
