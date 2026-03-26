/**
 * scanner.js — herbruikbare barcode scanner module
 * Gebruikt BarcodeDetector met een polling loop (300ms interval).
 * Fallback: handmatig tekstveld als BarcodeDetector niet beschikbaar is.
 */

(function (global) {
  'use strict';

  var Scanner = {};

  /**
   * Start de camera en scan barcodes.
   * @param {HTMLVideoElement} videoEl  - <video> element om camerabeeld in te tonen
   * @param {function} onResult        - callback(barcodeString) bij succesvolle scan
   * @param {function} onError         - callback(errorMessage) bij fout
   * @returns {function} stopFn        - aanroepen om camera te stoppen
   */
  Scanner.start = function (videoEl, onResult, onError) {
    var stopped = false;
    var stream = null;
    var intervalId = null;
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');

    function stopAll() {
      stopped = true;
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
      if (stream) {
        stream.getTracks().forEach(function (t) { t.stop(); });
        stream = null;
      }
      if (videoEl) {
        videoEl.srcObject = null;
      }
    }

    // Fallback: BarcodeDetector niet beschikbaar
    if (typeof BarcodeDetector === 'undefined') {
      var container = videoEl.parentNode;
      var melding = document.createElement('p');
      melding.textContent = 'Barcode scanner niet beschikbaar op dit apparaat';
      melding.style.cssText = 'color:#856404;background:#fff3cd;border:1px solid #ffc107;border-radius:4px;padding:.5rem .75rem;font-size:.9rem;margin-bottom:.5rem;';

      var invoer = document.createElement('input');
      invoer.type = 'text';
      invoer.placeholder = 'Voer barcode handmatig in';
      invoer.style.cssText = 'width:100%;padding:.5rem;border:1px solid #ced4da;border-radius:4px;font-size:.95rem;margin-bottom:.5rem;';

      var knop = document.createElement('button');
      knop.type = 'button';
      knop.textContent = 'Bevestigen';
      knop.style.cssText = 'padding:.4rem .8rem;background:#2D6A4F;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.9rem;';
      knop.addEventListener('click', function () {
        var val = invoer.value.trim();
        if (val) {
          melding.remove();
          invoer.remove();
          knop.remove();
          onResult(val);
        }
      });
      invoer.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') knop.click();
      });

      if (container) {
        container.insertBefore(knop, videoEl);
        container.insertBefore(invoer, knop);
        container.insertBefore(melding, invoer);
      }

      return stopAll;
    }

    // BarcodeDetector beschikbaar: start camera en polling loop
    var detector = new BarcodeDetector();

    navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }
    }).then(function (s) {
      stream = s;
      videoEl.srcObject = s;
      videoEl.setAttribute('playsinline', true);
      videoEl.play().then(function () {
        intervalId = setInterval(function () {
          if (stopped) return;
          if (videoEl.readyState < videoEl.HAVE_ENOUGH_DATA) return;

          canvas.width = videoEl.videoWidth;
          canvas.height = videoEl.videoHeight;
          ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);

          detector.detect(canvas).then(function (barcodes) {
            if (stopped) return;
            if (barcodes && barcodes.length > 0) {
              stopAll();
              onResult(barcodes[0].rawValue);
            }
          }).catch(function () {
            // Detectie mislukt voor dit frame, volgende poging over 300ms
          });
        }, 300);
      }).catch(function (e) {
        onError('Camera afspelen mislukt: ' + e.message);
      });
    }).catch(function (e) {
      onError('Camera toegang geweigerd: ' + e.message);
    });

    return stopAll;
  };

  global.Scanner = Scanner;
})(window);
