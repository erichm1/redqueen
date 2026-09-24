/* Webcam capture for forms. Fills a file input with a captured photo (or short video), or,
 * in multi-photo mode, with several photos. Nothing is uploaded until the form is submitted. */
(function () {
  'use strict';

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text) node.textContent = text;
    return node;
  }

  function init(root) {
    var input = document.getElementById(root.dataset.input);
    var allowVideo = root.dataset.video === '1';
    var maxPhotos = parseInt(root.dataset.max || '1', 10);
    var multi = maxPhotos > 1;
    var video = root.querySelector('video');
    var status = root.querySelector('[data-status]');
    var shots = root.querySelector('[data-shots]');
    var buttons = {};
    root.querySelectorAll('[data-action]').forEach(function (b) { buttons[b.dataset.action] = b; });
    var stream = null, recorder = null, timer = null, files = [];

    function say(msg) { status.textContent = msg; }

    function publish() {
      var dt = new DataTransfer();
      files.forEach(function (f) { dt.items.add(f.file); });
      input.files = dt.files;
      input.dispatchEvent(new Event('change', {bubbles: true}));
      renderShots();
    }

    function renderShots() {
      if (!shots) return;
      shots.textContent = '';
      files.forEach(function (f, i) {
        var box = el('figure', {'class': 'shot'});
        var img = el('img', {alt: 'Captured photo ' + (i + 1), src: f.url});
        var rm = el('button', {type: 'button', 'class': 'secondary small', 'aria-label': 'Remove photo ' + (i + 1)}, 'Remove');
        rm.addEventListener('click', function () { URL.revokeObjectURL(f.url); files.splice(i, 1); publish(); });
        box.appendChild(img); box.appendChild(rm); shots.appendChild(box);
      });
      if (multi) say(files.length + ' of ' + maxPhotos + ' photos captured.');
    }

    function setBusy(recording) {
      buttons.photo.disabled = !stream || recording;
      if (buttons.record) buttons.record.disabled = !stream || recording;
      buttons.start.hidden = !!stream; buttons.stop.hidden = !stream;
    }

    function stopCamera() {
      if (recorder && recorder.state !== 'inactive') recorder.stop();
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null; video.srcObject = null; setBusy(false);
    }

    buttons.start.addEventListener('click', function () {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        say('Camera access needs a secure page: use http://localhost:8000 or HTTPS, not a LAN address.'); return;
      }
      say('Requesting camera…');
      navigator.mediaDevices.getUserMedia({video: {width: {ideal: 1280}, height: {ideal: 720}, facingMode: 'user'}, audio: false})
        .then(function (s) { stream = s; video.srcObject = s; video.hidden = false; setBusy(false); say('Camera ready. Face the camera, in good light, alone in the frame.'); })
        .catch(function (err) {
          say(err.name === 'NotAllowedError' ? 'Camera permission was denied. Allow it in the browser address bar and try again.'
            : err.name === 'NotFoundError' ? 'No camera found.' : 'Could not start the camera: ' + err.message);
        });
    });
    buttons.stop.addEventListener('click', function () { stopCamera(); say('Camera off.'); });

    buttons.photo.addEventListener('click', function () {
      if (!video.videoWidth) { say('Camera is still starting, try again in a moment.'); return; }
      if (multi && files.length >= maxPhotos) { say('Maximum of ' + maxPhotos + ' photos reached. Remove one to retake.'); return; }
      var canvas = document.createElement('canvas');
      canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      canvas.toBlob(function (blob) {
        var file = new File([blob], 'webcam-' + Date.now() + '.jpg', {type: 'image/jpeg'});
        var entry = {file: file, url: URL.createObjectURL(blob)};
        if (multi) files.push(entry); else { files.forEach(function (f) { URL.revokeObjectURL(f.url); }); files = [entry]; }
        publish();
        if (!multi) say('Photo captured. Submit the form to run it through the pipeline.');
      }, 'image/jpeg', 0.92);
    });

    if (allowVideo && buttons.record) {
      buttons.record.addEventListener('click', function () {
        if (typeof MediaRecorder === 'undefined') { say('This browser cannot record video. Use a photo instead.'); return; }
        var types = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4'];
        var type = types.filter(function (t) { return MediaRecorder.isTypeSupported(t); })[0];
        var chunks = [], seconds = parseInt(root.dataset.seconds || '5', 10);
        recorder = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
        recorder.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
        recorder.onstop = function () {
          clearInterval(timer);
          var mime = recorder.mimeType || type || 'video/webm';
          var blob = new Blob(chunks, {type: mime});
          var file = new File([blob], 'webcam-' + Date.now() + (mime.indexOf('mp4') >= 0 ? '.mp4' : '.webm'), {type: mime});
          files = [{file: file, url: URL.createObjectURL(blob)}];
          var dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
          input.dispatchEvent(new Event('change', {bubbles: true}));
          setBusy(false); say('Video captured (' + seconds + ' s). Submit the form to run it through the pipeline.');
        };
        var left = seconds; setBusy(true); say('Recording… ' + left + ' s. Turn your head slightly.');
        timer = setInterval(function () { left -= 1; if (left > 0) say('Recording… ' + left + ' s'); }, 1000);
        recorder.start();
        setTimeout(function () { if (recorder.state !== 'inactive') recorder.stop(); }, seconds * 1000);
      });
    }

    root.closest('form').addEventListener('submit', stopCamera);
    window.addEventListener('pagehide', stopCamera);
    setBusy(false);
  }

  document.querySelectorAll('[data-webcam]').forEach(init);
})();
