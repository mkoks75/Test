/**
 * scanner.js — herbruikbare barcode scanner module via ZXing
 */

(function (global) {
  'use strict';

  var Scanner = {};
  var codeReader = new ZXing.BrowserMultiFormatReader();

  /**
   * Start de scanner op het opgegeven video element.
   * @param {string}   videoElementId  - id van het <video> element
   * @param {function} callback        - callback(barcodeString) bij succesvolle scan
   */
  Scanner.startScanner = function (videoElementId, callback) {
    codeReader.decodeFromVideoDevice(null, videoElementId, function (result, err) {
      if (result) {
        codeReader.reset();
        callback(result.getText());
      }
    });
  };

  /**
   * Stop de actieve scanner.
   */
  Scanner.stopScanner = function () {
    codeReader.reset();
  };

  global.Scanner = Scanner;
})(window);
