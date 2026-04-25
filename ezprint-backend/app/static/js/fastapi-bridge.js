/**
 * EzPrint customer UI ↔ FastAPI (`/api/v1/jobs`, upload token in query `t=`).
 * Loaded before customer.js; exposes async helpers on window.
 */
(function (global) {
  'use strict';

  const __uploadToken = { v: '' };

  const __slug = (function () {
    const p = (global.location.pathname || '').replace(/\/+$/, '');
    const parts = p.split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : '';
  })();

  function layoutTypeFromSelect(val) {
    const v = String(val);
    switch (v) {
      case '1': return 'normal';
      case '2': return '2up';
      case '4': return '4up';
      case '6': return '6up';
      case '8': return '8up';
      case '9': return '9up';
      case '16': return '16up';
      default: return 'normal';
    }
  }

  global.__ezprintSlug = __slug;
  global.__ezprintLayoutType = layoutTypeFromSelect;

  global.__ezprintTokenPromise = (async function loadUploadToken() {
    if (!__slug) throw new Error('Invalid shop link');
    const res = await global.fetch(
      '/api/v1/auth/upload/' + encodeURIComponent(__slug)
    );
    if (!res.ok) {
      const err = await res.json().catch(function () { return {}; });
      throw new Error(err.detail || ('HTTP ' + res.status));
    }
    const data = await res.json();
    __uploadToken.v = data.upload_token;
    const shop = data.shop_name || 'Shop';
    global.document.querySelectorAll('[data-ezprint-shop]').forEach(function (el) {
      el.textContent = shop;
    });
    return data;
  })();

  global.__ezprintTokenPromise.catch(function (err) {
    global.document.querySelectorAll('[data-ezprint-shop]').forEach(function (el) {
      el.textContent = 'Shop unavailable';
    });
    if (global.console) global.console.error('EzPrint upload token failed:', err);
  });

  global.__ezprintEnsureToken = async function () {
    await global.__ezprintTokenPromise;
    if (!__uploadToken.v) throw new Error('Upload session not ready');
    return __uploadToken.v;
  };

  global.__ezprintGetToken = function () { return __uploadToken.v; };

  /**
   * @param {File} file
   * @param {object} options
   */
  global.__ezprintSubmitFile = async function (file, options) {
    const t = encodeURIComponent(await global.__ezprintEnsureToken());
    const ext = (file.name.split('.').pop() || 'pdf')
      .toLowerCase()
      .replace(/^\./, '');

    const body = {
      filename: file.name,
      file_type: ext,
      file_size: file.size,
      copies: parseInt(String(options.copies), 10) || 1,
      page_size: options.page_size,
      orientation: options.orientation,
      print_side: options.print_side,
      color_mode: options.color_mode,
      layout_pages: parseInt(String(options.layout_pages), 10) || 1,
      layout_type: options.layout_type,
      page_range: options.page_range || null,
      customer_name: options.customer_name || null,
      customer_phone: options.customer_phone || null,
    };

    const createRes = await global.fetch('/api/v1/jobs?t=' + t, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!createRes.ok) {
      const e = await createRes.json().catch(function () { return ({}); });
      throw new Error(
        (typeof e.detail === 'string' ? e.detail : null) ||
          ('Create job failed: ' + createRes.status)
      );
    }
    const created = await createRes.json();
    const jobId = created.job_id;

    await new Promise(function (resolve, reject) {
      const fd = new global.FormData();
      fd.append('file', file, file.name);
      const xhr = new global.XMLHttpRequest();
      xhr.open(
        'POST',
        '/api/v1/jobs/' + encodeURIComponent(jobId) + '/upload?t=' + t
      );
      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else {
          reject(
            new Error('Upload failed: ' + xhr.status + ' ' + xhr.responseText.slice(0, 200))
          );
        }
      };
      xhr.onerror = function () { reject(new Error('Network error during upload')); };
      xhr.send(fd);
    });

    const fin = await global.fetch(
      '/api/v1/jobs/' + encodeURIComponent(jobId) + '/finalize?t=' + t,
      { method: 'POST' }
    );
    if (!fin.ok) {
      const e = await fin.json().catch(function () { return ({}); });
      throw new Error(
        (typeof e.detail === 'string' ? e.detail : null) ||
          ('Finalize failed: ' + fin.status)
      );
    }
    const out = await fin.json();
    return { job_id: jobId, finalize: out };
  };

  /** @returns {Promise<{ job_id: string, status: string, amount?: number }>} */
  global.__ezprintFetchJob = async function (jobId) {
    const t = encodeURIComponent(await global.__ezprintEnsureToken());
    const res = await global.fetch(
      '/api/v1/jobs/' + encodeURIComponent(jobId) + '?t=' + t
    );
    if (!res.ok) {
      const e = await res.json().catch(function () { return ({}); });
      throw new Error(
        (typeof e.detail === 'string' ? e.detail : null) || ('Job fetch ' + res.status)
      );
    }
    return res.json();
  };

  function __parsePageIndices(rangeStr, numPages) {
    if (!numPages || numPages < 1) return [];
    if (!rangeStr || !String(rangeStr).trim()) {
      const a = [];
      for (var i = 1; i <= numPages; i++) a.push(i);
      return a;
    }
    const s = String(rangeStr).replace(/\s+/g, '');
    const out = [];
    const seen = {};
    s.split(',').forEach(function (part) {
      if (!part) return;
      if (part.indexOf('-') >= 0) {
        const ab = part.split('-');
        const lo = Math.max(1, parseInt(ab[0], 10) || 1);
        const hi = Math.min(numPages, parseInt(ab[1], 10) || numPages);
        for (var p = lo; p <= hi; p++) {
          if (!seen[p] && p >= 1 && p <= numPages) {
            seen[p] = true;
            out.push(p);
          }
        }
      } else {
        const n = parseInt(part, 10);
        if (!isNaN(n) && n >= 1 && n <= numPages && !seen[n]) {
          seen[n] = true;
          out.push(n);
        }
      }
    });
    return out.length ? out.sort(function (a, b) { return a - b; }) : (function () {
      const a = [];
      for (var i = 1; i <= numPages; i++) a.push(i);
      return a;
    })();
  }

  /** @param {Uint8Array} pdfData */
  function __getPdfDocument(pdfData) {
    if (!global.pdfjsLib) {
      return Promise.reject(new Error('PDF preview library not loaded'));
    }
    const base = {
      data: pdfData,
      disableRange: true,
      disableStream: true,
      isEvalSupported: false,
    };
    return global.pdfjsLib.getDocument(base).promise;
  }

  function __layoutGrid(n) {
    const v = Math.max(1, parseInt(String(n), 10) || 1);
    switch (v) {
      case 2: return { rows: 1, cols: 2 };
      case 4: return { rows: 2, cols: 2 };
      case 6: return { rows: 2, cols: 3 };
      case 8: return { rows: 2, cols: 4 };
      case 9: return { rows: 3, cols: 3 };
      case 16: return { rows: 4, cols: 4 };
      default: return { rows: 1, cols: 1 };
    }
  }

  function __previewSheetSize(orientation, layoutPages) {
    const layoutN = Math.max(1, parseInt(String(layoutPages || 1), 10) || 1);
    const wantsLandscape = String(orientation || 'Portrait') === 'Landscape' || layoutN === 2;
    return wantsLandscape
      ? { width: 594, height: 420 }
      : { width: 420, height: 594 };
  }

  function __previewPixelRatio() {
    return Math.min(3, Math.max(2, Number(global.devicePixelRatio) || 1));
  }

  function __createPreviewSheetCanvas(width, height, pixelRatio) {
    const ratio = pixelRatio || __previewPixelRatio();
    const canvas = global.document.createElement('canvas');
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.scale(ratio, ratio);
    return { canvas: canvas, ctx: ctx };
  }

  function __applyGrayscaleCanvas(canvas) {
    var ctx = canvas.getContext('2d');
    var w = canvas.width;
    var h = canvas.height;
    var img = ctx.getImageData(0, 0, w, h);
    var d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      d[i] = d[i + 1] = d[i + 2] = y;
    }
    ctx.putImageData(img, 0, 0);
  }

  /**
   * @param {import('pdfjs-dist').PDFPageProxy} page
   * @param {number} maxW
   * @param {number} maxH
   * @param {number} rotation optional explicit page rotation
   */
  function __renderPageFitted(page, maxW, maxH, rotation) {
    const viewportArgs = { scale: 1 };
    if (typeof rotation === 'number' && !isNaN(rotation)) {
      viewportArgs.rotation = rotation;
    }
    const base = page.getViewport(viewportArgs);
    const sc = Math.min(maxW / base.width, maxH / base.height, 4);
    const renderArgs = { scale: sc };
    if (typeof rotation === 'number' && !isNaN(rotation)) {
      renderArgs.rotation = rotation;
    }
    const vp = page.getViewport(renderArgs);
    const canvas = global.document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = Math.floor(vp.width);
    canvas.height = Math.floor(vp.height);
    return page.render({ canvasContext: ctx, viewport: vp }).promise.then(function () {
      return canvas;
    });
  }

  function __drawContained(ctx, sourceCanvas, x, y, maxW, maxH) {
    const sw = sourceCanvas.width || 1;
    const sh = sourceCanvas.height || 1;
    const scale = Math.min(maxW / sw, maxH / sh);
    const drawW = sw * scale;
    const drawH = sh * scale;
    const drawX = x + (maxW - drawW) / 2;
    const drawY = y + (maxH - drawH) / 2;
    ctx.drawImage(sourceCanvas, drawX, drawY, drawW, drawH);
  }

  function __trimCanvasWhitespace(canvas, padding) {
    const w = canvas.width || 0;
    const h = canvas.height || 0;
    if (w < 2 || h < 2) return canvas;
    const ctx = canvas.getContext('2d');
    const data = ctx.getImageData(0, 0, w, h).data;
    var minX = w;
    var minY = h;
    var maxX = -1;
    var maxY = -1;
    const step = Math.max(1, Math.floor(Math.max(w, h) / 1200));
    for (var y = 0; y < h; y += step) {
      for (var x = 0; x < w; x += step) {
        var i = (y * w + x) * 4;
        var a = data[i + 3];
        var r = data[i];
        var g = data[i + 1];
        var b = data[i + 2];
        if (a > 12 && (r < 245 || g < 245 || b < 245)) {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < minX || maxY < minY) return canvas;
    const pad = Math.max(0, padding || 0);
    minX = Math.max(0, minX - pad);
    minY = Math.max(0, minY - pad);
    maxX = Math.min(w - 1, maxX + pad);
    maxY = Math.min(h - 1, maxY + pad);
    var cropW = maxX - minX + 1;
    var cropH = maxY - minY + 1;
    const targetAspect = 210 / 297;
    const cropAspect = cropW / cropH;
    if (cropAspect < targetAspect) {
      var wantedW = Math.min(w, Math.ceil(cropH * targetAspect));
      var extraW = wantedW - cropW;
      minX = Math.max(0, minX - Math.floor(extraW / 2));
      maxX = Math.min(w - 1, minX + wantedW - 1);
      minX = Math.max(0, maxX - wantedW + 1);
    } else if (cropAspect > targetAspect) {
      var wantedH = Math.min(h, Math.ceil(cropW / targetAspect));
      var extraH = wantedH - cropH;
      minY = Math.max(0, minY - Math.floor(extraH / 2));
      maxY = Math.min(h - 1, minY + wantedH - 1);
      minY = Math.max(0, maxY - wantedH + 1);
    }
    cropW = maxX - minX + 1;
    cropH = maxY - minY + 1;
    if (cropW >= w * 0.92 && cropH >= h * 0.92) return canvas;
    const out = global.document.createElement('canvas');
    out.width = cropW;
    out.height = cropH;
    out.getContext('2d').drawImage(canvas, minX, minY, cropW, cropH, 0, 0, cropW, cropH);
    return out;
  }

  function __splitTallCanvas(canvas) {
    const w = canvas.width || 0;
    const h = canvas.height || 0;
    if (w < 1 || h < 1) return [];
    const a4SliceH = Math.max(1, Math.round((w * 297) / 210));
    if (h <= a4SliceH * 1.25) return [canvas];
    const out = [];
    for (var y = 0; y < h; y += a4SliceH) {
      var partH = Math.min(a4SliceH, h - y);
      var c = global.document.createElement('canvas');
      c.width = w;
      c.height = partH;
      c.getContext('2d').drawImage(canvas, 0, y, w, partH, 0, 0, w, partH);
      out.push(c);
    }
    return out;
  }

  /**
   * One raster image (or unrecognised embed) → single-page A4 PDF bytes (for PDF.js preview).
   * Mirrors the PRINT “combine images to PDF” layout in customer.js.
   */
  async function __rasterFileToPdfBytes(file, signal, printSettings) {
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    if (!global.PDFLib || !global.PDFLib.PDFDocument) {
      throw new Error('PDF library not loaded');
    }
    const { PDFDocument } = global.PDFLib;
    const pdfDoc = await PDFDocument.create();
    const imageBytes = await file.arrayBuffer();
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    const u8 = new global.Uint8Array(imageBytes);
    var pdfImage = null;
    try {
      pdfImage = await pdfDoc.embedJpg(u8);
    } catch (e) {
      pdfImage = null;
    }
    if (!pdfImage) {
      try {
        pdfImage = await pdfDoc.embedPng(u8);
      } catch (e) {
        pdfImage = null;
      }
    }
    if (!pdfImage) {
      var blob;
      try {
        blob = new global.Blob([u8], { type: file.type || 'image/png' });
        var bitmap = await global.createImageBitmap(blob);
        var c0 = global.document.createElement('canvas');
        c0.width = bitmap.width;
        c0.height = bitmap.height;
        c0.getContext('2d').drawImage(bitmap, 0, 0);
        bitmap.close && bitmap.close();
        var pbin = c0.toDataURL('image/png');
        pbin = pbin.indexOf(',') >= 0 ? pbin.split(',')[1] : pbin;
        var raw = global.atob(pbin);
        var pbuf = new global.Uint8Array(raw.length);
        for (var i2 = 0; i2 < raw.length; i2++) pbuf[i2] = raw.charCodeAt(i2);
        pdfImage = await pdfDoc.embedPng(pbuf);
      } catch (e2) {
        throw new Error('Unsupported or unreadable image for preview.');
      }
    }
    const previewSize = __previewSheetSize(
      printSettings && printSettings.orientation,
      1
    );
    const pageWidth = previewSize.width === 594 ? 842 : 595;
    const pageHeight = previewSize.width === 594 ? 595 : 842;
    const margin = 20;
    const pdfPage = pdfDoc.addPage([pageWidth, pageHeight]);
    const availableWidth = pageWidth - 2 * margin;
    const availableHeight = pageHeight - 2 * margin;
    const iw = pdfImage.width;
    const ih = pdfImage.height;
    const imgAspect = iw / ih;
    const pageAspect = availableWidth / availableHeight;
    var drawW;
    var drawH;
    if (imgAspect > pageAspect) {
      drawW = availableWidth;
      drawH = availableWidth / imgAspect;
    } else {
      drawH = availableHeight;
      drawW = availableHeight * imgAspect;
    }
    const x0 = (pageWidth - drawW) / 2;
    const y0 = (pageHeight - drawH) / 2;
    pdfPage.drawImage(pdfImage, { x: x0, y: y0, width: drawW, height: drawH });
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    return pdfDoc.save();
  }

  /**
   * .docx → multi-page A4 PDF using mammoth (HTML) + html2canvas + pdf-lib.
   */
  async function __docxToPdfBytes(file, signal) {
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    if (!global.mammoth) {
      throw new Error('Word document preview (mammoth) not loaded');
    }
    if (!global.html2canvas) {
      throw new Error('Document renderer (html2canvas) not loaded');
    }
    if (!global.PDFLib || !global.PDFLib.PDFDocument) {
      throw new Error('PDF library not loaded');
    }
    const { PDFDocument } = global.PDFLib;
    const buf = await file.arrayBuffer();
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    const result = await global.mammoth.convertToHtml({ arrayBuffer: buf });
    const html = (result && result.value) ? String(result.value) : '';
    const wrap = global.document.createElement('div');
    wrap.id = 'ezprint-docx-temp';
    wrap.setAttribute('aria-hidden', 'true');
    wrap.style.cssText = [
      'position:fixed', 'left:-9999px', 'top:0', 'width:420px',
      'background:#fff', 'color:#111', 'box-sizing:border-box',
      'padding:16px', 'font:12px/1.4 system-ui,-apple-system,Segoe UI,sans-serif',
      'word-wrap:break-word', 'overflow:visible', 'z-index:0',
    ].join(';');
    var style = global.document.createElement('style');
    style.textContent = 'table{max-width:100%;border-collapse:collapse;} img{max-width:100%;} p{margin:0 0 0.5em 0}';
    wrap.appendChild(style);
    var body = global.document.createElement('div');
    if (html) {
      body.innerHTML = html;
    } else {
      body.textContent = ' ';
    }
    wrap.appendChild(body);
    global.document.body.appendChild(wrap);
    if (signal && signal.aborted) {
      try {
        global.document.body.removeChild(wrap);
      } catch (e) {
        /* ignore */
      }
      throw new global.DOMException('Aborted', 'AbortError');
    }
    var h2cOpts = {
      backgroundColor: '#ffffff',
      scale: 1,
      useCORS: true,
      allowTaint: true,
    };
    var big;
    try {
      big = await global.html2canvas(wrap, h2cOpts);
    } finally {
      try {
        if (wrap.parentNode) {
          global.document.body.removeChild(wrap);
        }
      } catch (e) {
        /* ignore */
      }
    }
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    if (!big || big.width < 1 || big.height < 1) {
      const pdf0 = await PDFDocument.create();
      pdf0.addPage([595, 842]);
      return pdf0.save();
    }
    const sliceW = big.width;
    const sliceH = Math.max(1, Math.round((sliceW * 297) / 210));
    const pdfOut = await PDFDocument.create();
    for (var y0 = 0, pi = 0; y0 < big.height; y0 += sliceH) {
      if (pi > 200) {
        break;
      }
      var hPart = global.Math.min(sliceH, big.height - y0);
      var cPart = global.document.createElement('canvas');
      cPart.width = sliceW;
      cPart.height = hPart;
      cPart.getContext('2d').drawImage(
        big,
        0,
        y0,
        sliceW,
        hPart,
        0,
        0,
        sliceW,
        hPart
      );
      var pbytes = await new global.Promise(function (resolve) {
        cPart.toBlob(
          function (b) {
            if (!b) {
              resolve(new global.Uint8Array(0));
              return;
            }
            b.arrayBuffer().then(function (ab) {
              resolve(new global.Uint8Array(ab));
            });
          },
          'image/png',
          0.92
        );
      });
      if (!pbytes || pbytes.length < 8) {
        break;
      }
      var eimg;
      try {
        eimg = await pdfOut.embedPng(pbytes);
      } catch (e) {
        break;
      }
      const pageW = 595;
      const pageH = 842;
      const m = 20;
      const aw = pageW - 2 * m;
      const ah = pageH - 2 * m;
      const s = global.Math.min(aw / eimg.width, ah / eimg.height);
      const dw = eimg.width * s;
      const dh = eimg.height * s;
      const x = (pageW - dw) / 2;
      const y = (pageH - dh) / 2;
      const pgN = pdfOut.addPage([pageW, pageH]);
      pgN.drawImage(eimg, { x: x, y: y, width: dw, height: dh });
      pi++;
    }
    if (pi === 0) {
      const pdf1 = await PDFDocument.create();
      pdf1.addPage([595, 842]);
      return pdf1.save();
    }
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    return pdfOut.save();
  }

  function __cloneElementMarkup(el) {
    var holder = global.document.createElement('div');
    holder.appendChild(el.cloneNode(true));
    return holder.innerHTML;
  }

  async function __docxToImagePreviews(file, pageRangeVal, settings, signal) {
    if (signal && signal.aborted) {
      throw new global.DOMException('Aborted', 'AbortError');
    }
    if (!global.docx || typeof global.docx.renderAsync !== 'function') {
      throw new Error('Word document preview renderer not loaded');
    }
    if (!global.html2canvas) {
      throw new Error('Document renderer not loaded');
    }

    const buf = await file.arrayBuffer();
    const host = global.document.createElement('div');
    host.id = 'ezprint-docx-direct-temp';
    host.setAttribute('aria-hidden', 'true');
    host.style.cssText = [
      'position:fixed', 'left:-12000px', 'top:0',
      'width:900px', 'height:auto', 'background:#fff',
      'z-index:0', 'overflow:visible',
    ].join(';');
    global.document.body.appendChild(host);
    try {
      await global.docx.renderAsync(buf, host, host, {
        className: 'docx',
        inWrapper: true,
        ignoreWidth: false,
        ignoreHeight: false,
        ignoreFonts: false,
        breakPages: true,
        experimental: true,
      });
      if (signal && signal.aborted) {
        throw new global.DOMException('Aborted', 'AbortError');
      }
      var pageEls = Array.prototype.slice.call(
        host.querySelectorAll('.docx-wrapper > section.docx, .docx-wrapper > section, section.docx, section')
      ).filter(function (el) {
        return (el.offsetWidth > 0 && el.offsetHeight > 0) ||
          el.textContent.trim() ||
          el.querySelector('img,table,svg,canvas');
      });
      if (!pageEls.length) {
        pageEls = [host];
      }
      const layoutPages = Math.max(1, parseInt(String(settings.layout_pages || 1), 10) || 1);
      const colorMode = settings.color_mode || 'Color';
      const isBw = (colorMode + '').toLowerCase().indexOf('black') >= 0;
      const grid = __layoutGrid(layoutPages);
      const cap = grid.rows * grid.cols;
      const renderedPages = [];
      const sourceIndices = __parsePageIndices(pageRangeVal, pageEls.length);
      for (var rp = 0; rp < sourceIndices.length; rp++) {
        if (signal && signal.aborted) {
          throw new global.DOMException('Aborted', 'AbortError');
        }
        var renderSrc = pageEls[sourceIndices[rp] - 1];
        if (!renderSrc) continue;
        var renderedCanvas = await global.html2canvas(renderSrc, {
          backgroundColor: '#ffffff',
          scale: 1.5,
          useCORS: true,
          allowTaint: true,
          windowWidth: Math.ceil(renderSrc.scrollWidth || renderSrc.offsetWidth || 900),
          windowHeight: Math.ceil(renderSrc.scrollHeight || renderSrc.offsetHeight || 1200),
        });
        renderedCanvas = __trimCanvasWhitespace(renderedCanvas, 48);
        __splitTallCanvas(renderedCanvas).forEach(function (part) {
          renderedPages.push(part);
        });
      }
      const indices = [];
      for (var ri = 1; ri <= renderedPages.length; ri++) indices.push(ri);
      const totalSheets = Math.ceil(indices.length / cap);
      const sheetCount = Math.min(40, totalSheets);
      const sheetSize = __previewSheetSize(settings.orientation, layoutPages);
      const pixelRatio = __previewPixelRatio();
      const pad = 6;
      const cellW = Math.floor((sheetSize.width - pad * (grid.cols + 1)) / grid.cols);
      const cellH = Math.floor((sheetSize.height - pad * (grid.rows + 1)) / grid.rows);
      const previews = [];

      for (var s = 0; s < sheetCount; s++) {
        const chunk = [];
        for (var c = 0; c < cap; c++) {
          const idx = s * cap + c;
          if (idx < indices.length) chunk.push(indices[idx]);
        }
        if (!chunk.length) break;
        var useRepeatFill =
          layoutPages > 1 &&
          chunk.length === 1 &&
          cap > 1 &&
          indices.length === 1;
        var drawCount = useRepeatFill ? cap : chunk.length;
        const sheetParts = __createPreviewSheetCanvas(sheetSize.width, sheetSize.height, pixelRatio);
        const sheet = sheetParts.canvas;
        const sctx = sheetParts.ctx;
        sctx.fillStyle = '#ffffff';
        sctx.fillRect(0, 0, sheetSize.width, sheetSize.height);

        for (var k = 0; k < drawCount; k++) {
          var pnum = useRepeatFill ? chunk[0] : chunk[k];
          if (signal && signal.aborted) {
            throw new global.DOMException('Aborted', 'AbortError');
          }
          var pageCanvas = renderedPages[pnum - 1];
          if (!pageCanvas) continue;
          if (isBw) __applyGrayscaleCanvas(pageCanvas);
          var row = Math.floor(k / grid.cols);
          var col = k % grid.cols;
          var x = pad + col * (cellW + pad);
          var y = pad + row * (cellH + pad);
          __drawContained(sctx, pageCanvas, x, y, cellW, cellH);
        }
        previews.push(sheet.toDataURL('image/jpeg', 0.94));
      }

      return {
        success: true,
        preview_source: 'docx',
        previews: previews,
        total_pages: totalSheets < 1 ? 1 : totalSheets,
        total_document_pages: renderedPages.length || pageEls.length,
        selected_document_pages: renderedPages.length,
        layout_pages: layoutPages,
        color_sheets: 0,
        bw_sheets: 0,
        total_amount: 0,
        page_range_warning: null,
      };
    } finally {
      try {
        if (host.parentNode) host.parentNode.removeChild(host);
      } catch (e) {
        /* ignore */
      }
    }
  }

  async function __renderPdfToPreviews(pdfData, oneBasedIndices, opt) {
    if (!global.pdfjsLib) {
      throw new Error('PDF preview library not loaded');
    }
    const settings = opt || {};
    const colorMode = settings.color_mode || 'Color';
    const orientation = settings.orientation || 'Portrait';
    const layoutPages = Math.max(1, parseInt(String(settings.layout_pages || 1), 10) || 1);
    const isBw = (colorMode + '').toLowerCase().indexOf('black') >= 0;
    const grid = __layoutGrid(layoutPages);
    const sheetCapacity = grid.rows * grid.cols;
    const sheetSize = __previewSheetSize(orientation, layoutPages);

    var pdf = pdfData;
    if (!pdf || typeof pdf.getPage !== 'function') {
      pdf = await __getPdfDocument(pdfData);
    }
    const numDoc = pdf.numPages;
    const maxSheets = 40;
    const urls = [];
    const indices = oneBasedIndices.slice();
    const totalSheets = Math.ceil(indices.length / sheetCapacity);
    const sheetCount = Math.min(maxSheets, totalSheets);
    const pad = 6;
    const baseCellW = sheetSize.width;
    const baseCellH = sheetSize.height;
    const pixelRatio = __previewPixelRatio();

    for (var s = 0; s < sheetCount; s++) {
      const chunk = [];
      for (var c = 0; c < sheetCapacity; c++) {
        var idx = s * sheetCapacity + c;
        if (idx < indices.length) chunk.push(indices[idx]);
      }
      if (chunk.length === 0) break;

      const cellW = Math.floor((baseCellW - pad * (grid.cols + 1)) / grid.cols);
      const cellH = Math.floor((baseCellH - pad * (grid.rows + 1)) / grid.rows);
      const sheetParts = __createPreviewSheetCanvas(baseCellW, baseCellH, pixelRatio);
      const sheet = sheetParts.canvas;
      const sctx = sheetParts.ctx;
      sctx.fillStyle = '#ffffff';
      sctx.fillRect(0, 0, baseCellW, baseCellH);

      // Single source page (e.g. one image, or page range selecting only one page):
      // fill every cell of the N-up grid with repeats so the preview matches
      // "2 per sheet" / "4 per sheet" etc. Multi-page jobs keep one PDF page per cell
      // until a sheet is full; the last *partial* sheet must not repeat the last page.
      var useRepeatFill =
        layoutPages > 1 &&
        chunk.length === 1 &&
        sheetCapacity > 1 &&
        indices.length === 1;
      var drawCount = useRepeatFill ? sheetCapacity : chunk.length;

      for (var k = 0; k < drawCount; k++) {
        var pnum = useRepeatFill ? chunk[0] : chunk[k];
        var page = await pdf.getPage(pnum);
        var row = Math.floor(k / grid.cols);
        var col = k % grid.cols;
        var cellCanvas = await __renderPageFitted(page, cellW * pixelRatio, cellH * pixelRatio);
        if (isBw) __applyGrayscaleCanvas(cellCanvas);
        var x = pad + col * (cellW + pad);
        var y = pad + row * (cellH + pad);
        __drawContained(sctx, cellCanvas, x, y, cellW, cellH);
      }
      urls.push(sheet.toDataURL('image/jpeg', 0.94));
    }

    return {
      previews: urls,
      totalDocumentPages: numDoc,
      selectedCount: oneBasedIndices.length,
      sheetCount: totalSheets,
      layoutN: layoutPages,
    };
  }

  /**
   * Same general shape as the old Flask /api/preview JSON (for PRINT flow).
   */
  global.__ezprintClientPrintPreview = async function (file, pageRangeVal, printSettings, signal) {
    if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
    const name = (file.name || '').toLowerCase();
    const isImg = /\.(png|jpe?g|gif|webp|bmp|tiff?)$/i.test(name) ||
      ((file.type || '').toLowerCase().indexOf('image/') === 0 &&
        !/\.(pdf|docx?)$/i.test(name));
    const isDocx = /\.docx$/i.test(name);
    const isDoc = /\.doc$/i.test(name);
    const ps = printSettings || {};

    if (isDoc) {
      throw new Error('Preview is available for DOCX and PDF files. Please save this Word file as .docx to preview it here.');
    }

    if (isDocx) {
      return __docxToImagePreviews(file, pageRangeVal, ps, signal);
    }

    var uintData;
    if (isImg) {
      const ab0 = await __rasterFileToPdfBytes(file, signal, ps);
      uintData = new Uint8Array(ab0);
    } else {
      const buf = await file.arrayBuffer();
      if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
      uintData = new Uint8Array(buf);
    }
    if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
    if (!global.pdfjsLib) {
      throw new Error('PDF.js not loaded; cannot preview in the browser.');
    }
    var pdfDoc;
    try {
      pdfDoc = await __getPdfDocument(uintData);
    } catch (e) {
      var msg = (e && e.message) ? String(e.message) : 'Could not read PDF';
      throw new Error(msg.indexOf('Invalid') >= 0 || msg.indexOf('structure') >= 0
        ? 'Invalid PDF structure.'
        : msg);
    }
    const docPageCount = pdfDoc.numPages;
    const idx = __parsePageIndices(pageRangeVal, docPageCount);
    const layoutN = Math.max(1, parseInt(String(ps.layout_pages), 10) || 1);
    const grid0 = __layoutGrid(layoutN);
    const cap = grid0.rows * grid0.cols;
    const billableSheets = idx.length === 0 ? 0 : Math.ceil(idx.length / cap);
    const renderOpts = {
      color_mode: ps.color_mode,
      orientation: ps.orientation,
      layout_pages: layoutN,
    };
    const rendered = await __renderPdfToPreviews(pdfDoc, idx, renderOpts);
    return {
      success: true,
      previews: rendered.previews,
      total_pages: billableSheets < 1 ? 1 : billableSheets,
      total_document_pages: docPageCount,
      selected_document_pages: idx.length,
      layout_pages: layoutN,
      color_sheets: 0,
      bw_sheets: 0,
      total_amount: 0,
      page_range_warning: null,
    };
  };

  /**
   * XEROX: scanned images combined to PDF.
   * Optional `printSettings` matches PRINT preview (layout, orientation, B/W).
   * @param {object} [printSettings] e.g. { color_mode, orientation, layout_pages }
   */
  global.__ezprintClientXeroxPreview = async function (pdfFile, pageRangeStr, signal, printSettings) {
    if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
    if (!global.pdfjsLib) {
      throw new Error('PDF.js not loaded');
    }
    const ps = printSettings || {};
    const buf = await pdfFile.arrayBuffer();
    const uintData = new Uint8Array(buf);
    let pdf;
    try {
      pdf = await __getPdfDocument(uintData);
    } catch (e) {
      var xmsg = (e && e.message) ? String(e.message) : 'Could not read PDF';
      throw new Error(xmsg.indexOf('Invalid') >= 0 || xmsg.indexOf('structure') >= 0
        ? 'Invalid PDF structure.'
        : xmsg);
    }
    const docPageCount = pdf.numPages;
    const idx = __parsePageIndices(pageRangeStr, docPageCount);
    const layoutN = Math.max(1, parseInt(String(ps.layout_pages || 1), 10) || 1);
    const grid0 = __layoutGrid(layoutN);
    const cap = grid0.rows * grid0.cols;
    const billableSheets = idx.length === 0 ? 0 : Math.ceil(idx.length / cap);
    const renderOpts = {
      color_mode: ps.color_mode,
      orientation: ps.orientation,
      layout_pages: layoutN,
    };
    const rendered = await __renderPdfToPreviews(pdf, idx, renderOpts);
    return {
      success: true,
      previews: rendered.previews,
      total_pages: billableSheets < 1 ? 1 : billableSheets,
      total_document_pages: docPageCount,
      selected_document_pages: idx.length,
      layout_pages: layoutN,
      total_amount: 0,
      color_sheets: 0,
      bw_sheets: 0,
    };
  };

  if (global.pdfjsLib) {
    global.pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';
  }
})(typeof window !== 'undefined' ? window : globalThis);
