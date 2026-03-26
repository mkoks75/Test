/**
 * scanner.js — herbruikbare barcode scanner module
 * Probeert eerst BarcodeDetector (native, Safari iOS 17+),
 * daalt af naar @zxing/library als fallback.
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
    var zxingReader = null;

    function stopAll() {
      stopped = true;
      if (stream) {
        stream.getTracks().forEach(function (t) { t.stop(); });
        stream = null;
      }
      if (zxingReader) {
        try { zxingReader.reset(); } catch (e) {}
        zxingReader = null;
      }
      if (videoEl) {
        videoEl.srcObject = null;
      }
    }

    function startCamera(callback) {
      navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      }).then(function (s) {
        stream = s;
        videoEl.srcObject = s;
        videoEl.setAttribute('playsinline', true);
        videoEl.play().then(callback).catch(function (e) {
          onError('Camera afspelen mislukt: ' + e.message);
        });
      }).catch(function (e) {
        onError('Camera toegang geweigerd: ' + e.message);
      });
    }

    // Probeer BarcodeDetector
    if (typeof BarcodeDetector !== 'undefined') {
      BarcodeDetector.getSupportedFormats().then(function (formats) {
        var detector = new BarcodeDetector({ formats: formats });

        startCamera(function () {
          function tick() {
            if (stopped) return;
            if (videoEl.readyState < videoEl.HAVE_ENOUGH_DATA) {
              requestAnimationFrame(tick);
              return;
            }
            detector.detect(videoEl).then(function (barcodes) {
              if (stopped) return;
              if (barcodes && barcodes.length > 0) {
                stopAll();
                onResult(barcodes[0].rawValue);
              } else {
                requestAnimationFrame(tick);
              }
            }).catch(function () {
              if (!stopped) requestAnimationFrame(tick);
            });
          }
          tick();
        });
      }).catch(function () {
        startZxing();
      });
    } else {
      startZxing();
    }

    function startZxing() {
      // Laad ZXing dynamisch als het nog niet aanwezig is
      if (typeof ZXing !== 'undefined') {
        runZxing();
        return;
      }
      var script = document.createElement('script');
      script.src = 'https://unpkg.com/@zxing/library@0.21.0/umd/index.min.js';
      script.onload = runZxing;
      script.onerror = function () { onError('ZXing bibliotheek kon niet worden geladen'); };
      document.head.appendChild(script);
    }

    function runZxing() {
      try {
        var hints = new Map();
        var codeReader = new ZXing.BrowserMultiFormatReader(hints);
        zxingReader = codeReader;
        startCamera(function () {
          codeReader.decodeFromVideoElement(videoEl, function (result, err) {
            if (stopped) return;
            if (result) {
              stopAll();
              onResult(result.getText());
            }
          });
        });
      } catch (e) {
        onError('ZXing fout: ' + e.message);
      }
    }

    return stopAll;
  };

  global.Scanner = Scanner;
})(window);
