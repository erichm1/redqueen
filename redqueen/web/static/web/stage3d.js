/* Sign-in artwork. Preferred: a live 3D scene (queen3d.js, three.js) that follows the pointer.
 * Fallback (no WebGL, or the module fails to load): the layered SVG art, tilted toward the pointer with CSS 3D. */
(function () {
  'use strict';
  var stage = document.querySelector('[data-stage3d]');
  if (!stage) return;
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var canvas = stage.querySelector('[data-queen3d]');
  var figure = stage.querySelector('.stage-figure');
  var queen = null;
  var password = document.getElementById('id_password');   // the sign-in form's password field

  // Privacy: while the password field has focus she closes her eyes; leaving it opens them again.
  function eyes(closed) {
    stage.classList.toggle('eyes-closed', closed);                        // the 2D fallback reacts to this class
    if (queen) { queen.setEyesClosed(closed, reduced); if (reduced) queen.renderAt(0.25); }
  }
  if (password) {
    password.addEventListener('focus', function () { eyes(true); });
    password.addEventListener('blur', function () { eyes(false); });
  }

  function bounds(e) {
    var r = stage.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width - 0.5, y: (e.clientY - r.top) / r.height - 0.5 };
  }

  stage.addEventListener('pointermove', function (e) {
    var p = bounds(e);
    if (queen) { queen.setPointer(p.x, p.y); return; }
    if (reduced || !figure) return;
    figure.style.setProperty('--ry', (p.x * 34).toFixed(1) + 'deg');
    figure.style.setProperty('--rx', (-p.y * 18).toFixed(1) + 'deg');
  });
  stage.addEventListener('pointerleave', function () {
    if (queen) { queen.setPointer(0, 0); return; }
    if (figure) { figure.style.setProperty('--ry', '0deg'); figure.style.setProperty('--rx', '0deg'); }
  });

  if (!canvas) return;
  import(canvas.dataset.module).then(function (mod) {
    queen = mod.createQueen(canvas, { offsetX: 0.13 });
    stage.classList.add('gl-on');
    if (password && document.activeElement === password) queen.setEyesClosed(true, true);   // already typing when the scene loaded
    queen.resize();
    if (reduced) { queen.renderAt(0.25); return; }
    queen.start();
    if ('IntersectionObserver' in window) {   // stop drawing while the stage is off screen
      new IntersectionObserver(function (entries) { entries[0].isIntersecting ? queen.start() : queen.stop(); }).observe(stage);
    }
  }).catch(function (err) {
    queen = null; stage.classList.remove('gl-on');
    if (window.console) console.info('3D scene unavailable, using the 2D artwork:', err && err.message);
  });
})();
