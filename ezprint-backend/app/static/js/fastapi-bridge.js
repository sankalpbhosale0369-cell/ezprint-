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

  async function __renderPdfToPreviews(pdfData, oneBasedIndices) {
    if (!global.pdfjsLib) {
      throw new Error('PDF preview library not loaded');
    }
    const pdf = await global.pdfjsLib.getDocument({ data: pdfData }).promise;
    const count = Math.min(40, oneBasedIndices.length);
    const urls = [];
    for (var i = 0; i < count; i++) {
      var pnum = oneBasedIndices[i];
      var page = await pdf.getPage(pnum);
      var scale = 1.15;
      var vp = page.getViewport({ scale: scale });
      var canvas = global.document.createElement('canvas');
      var ctx = canvas.getContext('2d');
      canvas.width = vp.width;
      canvas.height = vp.height;
      const task = page.render({ canvasContext: ctx, viewport: vp });
      await task.promise;
      urls.push(canvas.toDataURL('image/jpeg', 0.82));
    }
    return {
      previews: urls,
      totalDocumentPages: pdf.numPages,
      selectedCount: oneBasedIndices.length,
    };
  }

  /**
   * Same general shape as the old Flask /api/preview JSON (for PRINT flow).
   */
  global.__ezprintClientPrintPreview = async function (file, pageRangeVal, _printSettings, signal) {
    if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
    const name = (file.name || '').toLowerCase();
    const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
    if (isImg) {
      const url = global.URL.createObjectURL(file);
      return {
        success: true,
        previews: [url],
        total_pages: 1,
        total_document_pages: 1,
        selected_document_pages: 1,
        layout_pages: 1,
        color_sheets: 0,
        bw_sheets: 0,
        total_amount: 0,
        page_range_warning: null,
      };
    }
    const buf = await file.arrayBuffer();
    if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
    if (!global.pdfjsLib) {
      throw new Error('PDF.js not loaded; cannot preview PDFs in the browser.');
    }
    const tmp = await global.pdfjsLib.getDocument({ data: buf }).promise;
    const n = tmp.numPages;
    const idx = __parsePageIndices(pageRangeVal, n);
    const rendered = await __renderPdfToPreviews(new Uint8Array(buf), idx);
    return {
      success: true,
      previews: rendered.previews,
      total_pages: rendered.selectedCount,
      total_document_pages: n,
      selected_document_pages: idx.length,
      layout_pages: 1,
      color_sheets: 0,
      bw_sheets: 0,
      total_amount: 0,
      page_range_warning: null,
    };
  };

  /** XEROX: scanned images combined to PDF; match old Flask /api/preview shape. */
  global.__ezprintClientXeroxPreview = async function (pdfFile, pageRangeStr, signal) {
    if (signal && signal.aborted) throw new global.DOMException('Aborted', 'AbortError');
    if (!global.pdfjsLib) {
      throw new Error('PDF.js not loaded');
    }
    const buf = await pdfFile.arrayBuffer();
    const tmp = await global.pdfjsLib.getDocument({ data: buf }).promise;
    const n = tmp.numPages;
    const idx = __parsePageIndices(pageRangeStr, n);
    const rendered = await __renderPdfToPreviews(new Uint8Array(buf), idx);
    return {
      success: true,
      previews: rendered.previews,
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
