document.addEventListener('DOMContentLoaded', function () {
    // Set header height as CSS variable for scroll alignment
    const updateHeaderHeight = () => {
        const header = document.querySelector('.header-card');
        if (header) {
            document.documentElement.style.setProperty('--header-height', header.offsetHeight + 'px');
        }
    };
    updateHeaderHeight();
    window.addEventListener('resize', updateHeaderHeight);
    // Also update after a short delay to account for logo loading
    setTimeout(updateHeaderHeight, 1000);

    // Helper to scroll to element with header offset
    const scrollToElement = (element) => {
        if (!element) return;
        const header = document.querySelector('.header-card');
        const headerHeight = header ? header.offsetHeight : 0;
        const elementPosition = element.getBoundingClientRect().top + window.pageYOffset;
        const offsetPosition = elementPosition - headerHeight - 20;

        window.scrollTo({
            top: Math.max(0, offsetPosition),
            behavior: 'smooth'
        });
    };

    // XEROX Scanner State
    let scannedPages = [];  // Array of {blob, thumbnail, id}
    let cameraStream = null;
    let currentCaptureBlob = null;
    let scannerPageIdCounter = 0;
    const MAX_SCANNED_PAGES = 20;  // Security limit (reduced from 50)
    const MAX_IMAGE_SIZE_MB = 5;  // Max size per image in MB
    const MAX_CROP_DIMENSION = 3000; // Clamp cropped image dimensions for perf
    const CROP_JPEG_QUALITY = 0.8;

    // Landing Page Elements
    const landingSection = document.getElementById('landingSection');
    const uploadSection = document.getElementById('uploadSection');
    const xeroxScannerSection = document.getElementById('xeroxScannerSection');
    const xeroxSettingsSection = document.getElementById('xeroxSettingsSection');
    const xeroxCard = document.getElementById('xeroxCard');
    const printCard = document.getElementById('printCard');
    const closeScannerBtn = document.getElementById('closeScannerBtn');
    const xeroxSettingsBackBtn = document.getElementById('xeroxSettingsBackBtn');

    // XEROX Settings Elements
    const xeroxSettingsForm = document.getElementById('xeroxSettingsForm');
    const xeroxPreviewBtn = document.getElementById('xeroxPreviewBtn');
    const xeroxUploadBtn = document.getElementById('xeroxUploadBtn');
    const xeroxDocumentName = document.getElementById('xeroxDocumentName');
    const xeroxDocumentSize = document.getElementById('xeroxDocumentSize');
    const xeroxDocumentPages = document.getElementById('xeroxDocumentPages');
    const xeroxCopies = document.getElementById('xeroxCopies');
    const xeroxPrintSide = document.getElementById('xeroxPrintSide');
    const xeroxColorMode = document.getElementById('xeroxColorMode');

    // Cropper Modal Elements
    const cropperModal = document.getElementById('cropperModal');
    const cropperModalBackdrop = cropperModal ? cropperModal.querySelector('.cropper-modal-backdrop') : null;
    const cropperImage = document.getElementById('cropperImage');
    const cropperPreview = document.getElementById('cropperPreview');
    const cropperConfirmBtn = document.getElementById('cropperConfirmBtn');
    const cropperRecaptureBtn = document.getElementById('cropperRecaptureBtn');
    const cropperRotateBtn = document.getElementById('cropperRotateBtn');
    const cropperAspectBtn = document.getElementById('cropperAspectBtn');
    const cropperDocNameBtn = document.getElementById('cropperDocNameBtn');
    const cropperDocNameModal = document.getElementById('cropperDocNameModal');
    const cropperDocNameInput = document.getElementById('cropperDocNameInput');
    const cropperDocNameSave = document.getElementById('cropperDocNameSave');
    const cropperDocNameCancel = document.getElementById('cropperDocNameCancel');
    let cropper = null; // Still kept for reference/null checks in existing code
    let sourceImage = new Image();
    let cropRotation = 0;
    let cropperObjectUrl = null;
    let cropperAspectMode = 'free'; // 'free' | 'a4' | 'square'
    let currentCroppingPageId = null; // null = new page
    let currentCropOriginalBlob = null;
    let currentCropOriginalThumb = null;
    let currentCropFilename = null;

    // Track current mode
    let currentMode = null; // 'xerox' or 'print'

    // Auto-preview state for XEROX mode
    let xeroxPreviewDebounceTimer = null;
    let xeroxPreviewAbortController = null;
    let xeroxPreviewTimeout = null;
    const XEROX_PREVIEW_DEBOUNCE_MS = 300; // Debounce delay: 300ms (reduced for better UX)
    const XEROX_PREVIEW_TIMEOUT_MS = 6000; // Show timeout message after 6 seconds

    // Preview lifecycle management (race condition fix)
    let previewGenerationId = 0;
    let currentPreviewPromise = null;
    let previewInProgress = false;
    let previewReadyForPrint = false;
    const PREVIEW_AWAIT_TIMEOUT_MS = 12000; // Max wait time for preview when Print is clicked

    // Scanner UI Elements
    const cameraVideo = document.getElementById('cameraVideo');
    const cameraCanvas = document.getElementById('cameraCanvas');
    const cameraPlaceholder = document.getElementById('cameraPlaceholder');
    const cameraPreviewContainer = document.getElementById('cameraPreviewContainer');
    const scannerControls = document.getElementById('scannerControls');
    const enableCameraBtn = document.getElementById('enableCameraBtn');
    const captureBtn = document.getElementById('captureBtn');
    const retakeBtn = document.getElementById('retakeBtn');
    const scannedPagesContainer = document.getElementById('scannedPagesContainer');
    const thumbnailsGrid = document.getElementById('thumbnailsGrid');
    const scannedPageCount = document.getElementById('scannedPageCount');
    const addMorePagesBtn = document.getElementById('addMorePagesBtn');
    const finishScanBtn = document.getElementById('finishScanBtn');
    const scannedReviewSection = document.getElementById('scannedReviewSection');
    const scannedReviewList = document.getElementById('scannedReviewList');
    const scannedReviewCount = document.getElementById('scannedReviewCount');
    const reviewAddMoreBtn = document.getElementById('reviewAddMoreBtn');
    const reviewProceedBtn = document.getElementById('reviewProceedBtn');


    // Form elements
    const uploadForm = document.getElementById('uploadForm');
    const fileInput = document.getElementById('file');
    const dropzone = document.getElementById('dropzone');
    const fileInfo = document.getElementById('fileInfo');
    const previewBtn = document.getElementById('previewBtn');

    // Preview section elements
    const previewSection = document.getElementById('previewSection');
    const previewImage = document.getElementById('previewImage');
    const previewFilename = document.getElementById('previewFilename');
    const previewSize = document.getElementById('previewSize');
    const previewPages = document.getElementById('previewPages');
    const previewLayout = document.getElementById('previewLayout');
    const previewOrientation = document.getElementById('previewOrientation');
    const previewPrintSide = document.getElementById('previewPrintSide');
    const previewColorMode = document.getElementById('previewColorMode');
    const previewCopies = document.getElementById('previewCopies');
    const previewPageRange = document.getElementById('previewPageRange');

    // Preview control buttons
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    const rotateBtn = document.getElementById('rotateBtn');
    const zoomLevel = document.getElementById('zoomLevel');
    const prevPageBtn = document.getElementById('prevPageBtn');
    const nextPageBtn = document.getElementById('nextPageBtn');
    const pageIndicator = document.getElementById('pageIndicator');

    // Customization elements
    const copies = document.getElementById('copies');
    const pageSize = document.getElementById('pageSize');
    const orientation = document.getElementById('orientation');
    const printSide = document.getElementById('printSide');
    const colorMode = document.getElementById('colorMode');
    const layoutPages = document.getElementById('layoutPages');
    const pageRangeInput = document.getElementById('pageRange');

    // Other elements
    const uploadBtn = document.getElementById('uploadBtn');
    const previewLoading = document.getElementById('previewLoading');
    const editBtn = document.getElementById('editBtn');
    const confirmPrintBtn = document.getElementById('confirmPrintBtn');
    const statusSection = document.getElementById('statusSection');
    const singleJobPanel = document.getElementById('singleJobPanel');
    const singleJobFile = document.getElementById('singleJobFile');
    const singleJobMeta = document.getElementById('singleJobMeta');
    const singleJobStepper = document.getElementById('singleJobStepper');
    const singleJobError = document.getElementById('singleJobError');
    const singleJobProgress = document.getElementById('singleJobProgress');
    const jobDetailsPanel = document.getElementById('jobDetailsPanel');
    const jobDetailsJobId = document.getElementById('jobDetailsJobId');
    const jobDetailsFilename = document.getElementById('jobDetailsFilename');
    const jobDetailsFilesize = document.getElementById('jobDetailsFilesize');
    const jobDetailsPages = document.getElementById('jobDetailsPages');
    const jobDetailsSettingsTags = document.getElementById('jobDetailsSettingsTags');
    const jobDetailsAmount = document.getElementById('jobDetailsAmount');
    const jobDetailsStatus = document.getElementById('jobDetailsStatus');

    // Preview state
    let currentZoom = 1;
    let currentRotation = 0;
    let currentFile = null;
    let previewTimeout = null;
    let currentJobId = null;
    let statusCheckInterval = null;
    let currentShopId = null;
    let _uploadInFlight = false; // Double-submit guard
    let printPreviewAbortController = null; // AbortController for PRINT preview requests

    // Multi-page preview state (BUG FIX: Added to support proper page navigation)
    let previewUrls = [];  // Array of all preview URLs
    let currentPageIndex = 0;  // Current page index (0-based)
    let totalPages = 0;  // Total number of pages

    // Pricing state
    let shopPricing = {
        bw_single: 2.0,
        bw_double: 1.5,
        color_single: 10.0,
        color_double: 8.0
    };
    let currentPageCount = 0;  // Current total pages for price calculation
    let backendTotalAmount = null;
    let backendColorSheets = null;
    let backendBWSheets = null;
    let isTrackingViewActive = false; // Race-condition guard: blocks preview UI after Print is clicked

    // Setup all controls
    setupPreviewControls();
    setupCustomizationListeners();
    setupPricing();

    // Initialize orientation suffix icons
    setupOrientationIcons();

    // Drag & Drop handlers
    if (dropzone) {
        ['dragenter', 'dragover'].forEach(evt => {
            dropzone.addEventListener(evt, function (e) { e.preventDefault(); e.stopPropagation(); dropzone.classList.add('dragover'); });
        });
        ['dragleave', 'drop'].forEach(evt => {
            dropzone.addEventListener(evt, function (e) { e.preventDefault(); e.stopPropagation(); dropzone.classList.remove('dragover'); });
        });
        dropzone.addEventListener('drop', function (e) {
            const files = e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files : null;
            if (files && files.length > 0) {
                fileInput.files = files;
                fileInput.dispatchEvent(new Event('change'));
            }
        });
    }

    // File input change handler
    fileInput.addEventListener('change', async function (e) {
        const files = Array.from(e.target.files);  // ← All selected files

        if (files.length === 0) return;

        // Check if all files are images
        const imageFiles = files.filter(f =>
            f.type.startsWith('image/') ||
            /\.(png|jpe?g|gif|bmp|tiff)$/i.test(f.name)
        );

        // If multiple images, combine into PDF
        if (imageFiles.length > 1) {
            console.log(`Combining ${imageFiles.length} images into PDF...`);

            // Show loading
            if (fileInfo) {
                fileInfo.innerHTML = `<div class="loading">Combining ${imageFiles.length} images...</div>`;
            }

            try {
                // Reuse XEROX PDF combination logic
                const pdfBlob = await combineImagesToPDFForPrint(imageFiles);
                const pdfFile = new File([pdfBlob], `combined_${Date.now()}.pdf`, { type: 'application/pdf' });

                currentFile = pdfFile;

                // Update UI
                if (fileInfo) {
                    fileInfo.innerHTML = `
                        <div class="file-selected">
                            <i class="fas fa-file-pdf"></i>
                            <span>${imageFiles.length} images combined into PDF</span>
                            <span class="file-size">${(pdfFile.size / (1024 * 1024)).toFixed(2)} MB</span>
                        </div>
                    `;
                }

                // Enable buttons
                previewBtn.disabled = false;
                uploadBtn.disabled = false;

                // Auto-preview
                setTimeout(() => generatePreview(true), 500);

            } catch (error) {
                console.error('PDF combination failed:', error);
                alert('Failed to combine images. Please try again.');
                return;
            }

        } else {
            // Single file - use as-is
            currentFile = files[0];

            // Show file info (existing code)
            if (fileInfo) {
                fileInfo.innerHTML = `
                    <div class="file-selected">
                        <i class="fas fa-file"></i>
                        <span>${currentFile.name}</span>
                        <span class="file-size">${(currentFile.size / (1024 * 1024)).toFixed(2)} MB</span>
                    </div>
                `;
            }

            // Enable buttons
            previewBtn.disabled = false;
            uploadBtn.disabled = false;

            // Auto-preview
            setTimeout(() => generatePreview(true), 500);
        }
    });

    /**
     * Combine multiple images into a single PDF (for PRINT multi-file upload)
     * Reuses XEROX PDF-lib logic
     */
    async function combineImagesToPDFForPrint(imageFiles) {
        // Load PDF-lib (should already be loaded for XEROX)
        const { PDFDocument } = PDFLib;

        const pdfDoc = await PDFDocument.create();

        for (let i = 0; i < imageFiles.length; i++) {
            const file = imageFiles[i];
            const imageBytes = await file.arrayBuffer();

            // Try to embed as JPEG first, fallback to PNG
            let pdfImage;
            try {
                pdfImage = await pdfDoc.embedJpg(imageBytes);
            } catch (e) {
                try {
                    pdfImage = await pdfDoc.embedPng(imageBytes);
                } catch (e2) {
                    console.error(`Failed to embed image ${i + 1}:`, e2);
                    continue;  // Skip this image
                }
            }

            // Create A4 page
            const pdfPage = pdfDoc.addPage([595, 842]);  // A4 in points (72 DPI)

            // Calculate scaling to fit image on page
            const pageWidth = 595;
            const pageHeight = 842;
            const margin = 20;

            const availableWidth = pageWidth - (2 * margin);
            const availableHeight = pageHeight - (2 * margin);

            const imgAspectRatio = pdfImage.width / pdfImage.height;
            const pageAspectRatio = availableWidth / availableHeight;

            let drawWidth, drawHeight;
            if (imgAspectRatio > pageAspectRatio) {
                // Image wider than page - fit to width
                drawWidth = availableWidth;
                drawHeight = availableWidth / imgAspectRatio;
            } else {
                // Image taller than page - fit to height
                drawHeight = availableHeight;
                drawWidth = availableHeight * imgAspectRatio;
            }

            // Center image on page
            const x = (pageWidth - drawWidth) / 2;
            const y = (pageHeight - drawHeight) / 2;

            pdfPage.drawImage(pdfImage, {
                x: x,
                y: y,
                width: drawWidth,
                height: drawHeight
            });
        }

        const pdfBytes = await pdfDoc.save();
        return new Blob([pdfBytes], { type: 'application/pdf' });
    }


    // Preview button handler (PRINT flow only)
    previewBtn.addEventListener('click', function () {
        if (currentMode !== 'xerox') {
            generatePreview();
        }
    });

    // Setup preview controls
    function setupPreviewControls() {
        // Zoom controls
        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', function () {
                currentZoom = Math.min(currentZoom * 1.2, 3);
                updateImageTransform();
            });
        }

        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', function () {
                currentZoom = Math.max(currentZoom / 1.2, 0.5);
                updateImageTransform();
            });
        }

        // Rotation control
        if (rotateBtn) {
            rotateBtn.addEventListener('click', function () {
                currentRotation = (currentRotation + 90) % 360;
                updateImageTransform();
            });
        }

        // Page navigation controls (BUG FIX: Added to enable multi-page navigation)
        if (prevPageBtn) {
            prevPageBtn.addEventListener('click', function () {
                if (currentPageIndex > 0) {
                    currentPageIndex--;
                    updatePreviewPage();
                }
            });
        }

        if (nextPageBtn) {
            nextPageBtn.addEventListener('click', function () {
                if (currentPageIndex < previewUrls.length - 1) {
                    currentPageIndex++;
                    updatePreviewPage();
                }
            });
        }
    }

    // Update preview page display (BUG FIX: Now actually changes the preview image)
    function updatePreviewPage() {
        if (previewUrls.length === 0 || !previewImage) {
            return;
        }

        // Update preview image source
        previewImage.src = previewUrls[currentPageIndex];

        // Update page indicator
        // PAGE RANGE FIX: Shows position within filtered pages (e.g., "Page 1 of 4" for first selected page)
        if (pageIndicator) {
            pageIndicator.textContent = `Page ${currentPageIndex + 1} of ${totalPages}`;
        }

        // Update navigation button states
        if (prevPageBtn) {
            prevPageBtn.disabled = currentPageIndex === 0;
            prevPageBtn.style.opacity = currentPageIndex === 0 ? '0.5' : '1';
        }

        if (nextPageBtn) {
            nextPageBtn.disabled = currentPageIndex >= previewUrls.length - 1;
            nextPageBtn.style.opacity = currentPageIndex >= previewUrls.length - 1 ? '0.5' : '1';
        }

        // Reset zoom and rotation when changing pages
        currentZoom = 1;
        currentRotation = 0;
        updateImageTransform();
    }

    // Setup customization listeners for dynamic preview updates
    // Uses a flag to prevent duplicate listener binding
    function setupCustomizationListeners() {
        if (window._printCustomizationListenersAttached) return;

        const customizationInputs = [copies, pageSize, orientation, printSide, colorMode, layoutPages];

        customizationInputs.forEach(input => {
            if (input) {
                input.addEventListener('change', function () {
                    updatePreviewWithDelay();
                });
            }
        });

        // PAGE RANGE FIX: Add listener for page range input to update preview when changed
        if (pageRangeInput) {
            // Use 'input' event for real-time updates as user types, with debounce
            let pageRangeTimeout = null;
            pageRangeInput.addEventListener('input', function () {
                const pageRangeVal = pageRangeInput.value.trim();

                // Validate and show error immediately
                if (pageRangeVal && !isValidPageRange(pageRangeVal)) {
                    showPageRangeError('Invalid format. Use: 1-3, 5, 7-9');
                } else {
                    showPageRangeError(''); // Clear error if valid
                }

                // Clear existing timeout
                if (pageRangeTimeout) {
                    clearTimeout(pageRangeTimeout);
                }
                // Debounce: wait for user to stop typing before updating preview
                pageRangeTimeout = setTimeout(() => {
                    const val = pageRangeInput.value.trim();
                    // Only update preview if valid or empty (empty = all pages)
                    if (!val || isValidPageRange(val)) {
                        if (currentFile) {
                            updatePreviewWithDelay();
                        }
                    }
                }, 1000); // Wait 1 second after user stops typing
            });

            // Also update on blur (when user leaves the field)
            // FIX: Route through updatePreviewWithDelay instead of calling generatePreview directly
            pageRangeInput.addEventListener('blur', function () {
                if (pageRangeTimeout) {
                    clearTimeout(pageRangeTimeout);
                    pageRangeTimeout = null;
                }
                const pageRangeVal = pageRangeInput.value.trim();
                if (!pageRangeVal || isValidPageRange(pageRangeVal)) {
                    showPageRangeError(''); // Clear error
                    if (currentFile) {
                        updatePreviewWithDelay();
                    }
                } else {
                    showPageRangeError('Invalid format. Use: 1-3, 5, 7-9');
                }
            });
        }

        window._printCustomizationListenersAttached = true;
    }

    // Setup pricing functionality
    function setupPricing() {
        // Fetch pricing on page load
        fetchPricing();

        // Add listeners for price calculation triggers
        const priceCalculationInputs = [copies, printSide, colorMode, pageRangeInput];
        priceCalculationInputs.forEach(input => {
            if (input) {
                input.addEventListener('change', updatePriceDisplay);
                input.addEventListener('input', updatePriceDisplay);
            }
        });

        // Also listen to xerox settings
        if (xeroxCopies) xeroxCopies.addEventListener('change', updateXeroxPriceDisplay);
        if (xeroxPrintSide) xeroxPrintSide.addEventListener('change', updateXeroxPriceDisplay);
        if (xeroxColorMode) xeroxColorMode.addEventListener('change', updateXeroxPriceDisplay);
    }

    // Public pricing API was Flask-only; FastAPI finalizes per-page pricing after upload. Keep defaults.
    async function fetchPricing() {
        return;
    }

    // Setup Orientation Icons
    function setupOrientationIcons() {
        const selects = [
            { id: 'orientation', iconId: 'orientationIcon' },
            { id: 'xeroxOrientation', iconId: 'xeroxOrientationIcon' }
        ];

        const portraitSvg = '<rect x="5" y="2" width="6" height="12" stroke="#000000" stroke-width="1.5" fill="none"/>';
        const landscapeSvg = '<rect x="2" y="5" width="12" height="6" stroke="#000000" stroke-width="1.5" fill="none"/>';

        selects.forEach(item => {
            const selectEl = document.getElementById(item.id);
            const iconWrapper = document.getElementById(item.iconId);
            if (!selectEl || !iconWrapper) return;

            const updateIcon = () => {
                const svg = iconWrapper.querySelector('svg');
                if (svg) {
                    svg.innerHTML = selectEl.value === 'Landscape' ? landscapeSvg : portraitSvg;
                }
            };

            selectEl.addEventListener('change', updateIcon);
            updateIcon(); // Initial set
        });
    }

    // Calculate price based on settings
    function calculatePrice(pageCount, colorMode, printSide, copies = 1) {
        // If we have backend result and the inputs match, use backend result
        if (backendTotalAmount !== null && backendTotalAmount !== undefined) {
            // FIX: backendTotalAmount is treated as per-copy base from backend preview.
            // Always multiply by current UI copies to match Dashboard behavior.
            const total = backendTotalAmount * copies;
            const pricePerPage = pageCount > 0 ? (total / copies / pageCount) : 0;
            return {
                pricePerPage: pricePerPage,
                total: total,
                isMixed: backendColorSheets > 0 && backendBWSheets > 0
            };
        }

        if (!pageCount || pageCount <= 0) return { pricePerPage: 0, total: 0 };

        const isColor = colorMode === 'Color';
        const isDouble = printSide === 'Double';

        let pricePerPage;
        if (isColor) {
            pricePerPage = isDouble ? shopPricing.color_double : shopPricing.color_single;
        } else {
            pricePerPage = isDouble ? shopPricing.bw_double : shopPricing.bw_single;
        }

        const total = pageCount * pricePerPage * copies;

        return {
            pricePerPage: pricePerPage,
            total: total
        };
    }

    // Update price display for upload form
    function updatePriceDisplay() {
        if (!currentFile && currentMode !== 'xerox') return;

        // BILLING FIX: Use effective sheet count for price calculation if layout is applied
        let pageCount = currentPageCount || 0;
        const layoutVal = parseInt(layoutPages ? layoutPages.value : 1) || 1;
        if (layoutVal > 1 && pageCount > 0 && currentPageCount === (currentFile ? currentFile.totalPages : 0)) {
            // In some cases currentPageCount might still be raw document pages
            // However, below we ensure it's always sheets. Adding defensive layoutVal > 1 check.
        }
        const colorModeVal = colorMode ? colorMode.value : 'Black & White';
        const printSideVal = printSide ? printSide.value : 'Single';
        const copiesVal = copies ? parseInt(copies.value) || 1 : 1;

        if (pageCount <= 0) {
            // Hide price info if no pages
            const uploadPriceInfo = document.getElementById('uploadPriceInfo');
            if (uploadPriceInfo) uploadPriceInfo.style.display = 'none';
            return;
        }

        const price = calculatePrice(pageCount, colorModeVal, printSideVal, copiesVal);

        // Update upload form price display
        const uploadPriceInfo = document.getElementById('uploadPriceInfo');
        const uploadTotalPages = document.getElementById('uploadTotalPages');
        const uploadPricePerPage = document.getElementById('uploadPricePerPage');
        const uploadTotalAmount = document.getElementById('uploadTotalAmount');

        if (uploadPriceInfo && uploadTotalPages && uploadPricePerPage && uploadTotalAmount) {
            uploadTotalPages.textContent = pageCount;
            const pRow = uploadPricePerPage.closest('.price-row');
            if (price.isMixed) {
                const isDouble = printSideVal === 'Double';
                const bwPrice = isDouble ? shopPricing.bw_double : shopPricing.bw_single;
                const colorPrice = isDouble ? shopPricing.color_double : shopPricing.color_single;

                if (pRow) {
                    pRow.style.flexDirection = 'column';
                    pRow.style.alignItems = 'flex-start';
                }
                uploadPricePerPage.style.width = '100%';
                uploadPricePerPage.innerHTML = `
                    <div style="display: flex; justify-content: space-between; width: 100%; margin-top: 5px; font-size: 13px;">
                        <span>Black & White:</span>
                        <span>₹${bwPrice.toFixed(2)}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; width: 100%; margin-top: 2px; font-size: 13px;">
                        <span>Color:</span>
                        <span>₹${colorPrice.toFixed(2)}</span>
                    </div>
                `;
            } else {
                if (pRow) {
                    pRow.style.flexDirection = 'row';
                    pRow.style.alignItems = 'center';
                }
                uploadPricePerPage.style.width = 'auto';
                uploadPricePerPage.textContent = `₹${price.pricePerPage.toFixed(2)}`;
            }
            uploadTotalAmount.textContent = `₹${price.total.toFixed(2)}`;
            uploadPriceInfo.style.display = 'block';
        }

        // Also update preview section if visible
        updatePreviewPriceDisplay(pageCount, colorModeVal, printSideVal, copiesVal);
    }

    // Update price display for xerox form
    function updateXeroxPriceDisplay() {
        if (currentMode !== 'xerox') return;

        // Use backend-calculated page count (sheets) if available, otherwise fallback to local calculation
        let pageCount = (backendTotalAmount !== null && currentPageCount !== undefined) ?
            currentPageCount : (scannedPages.length || 0);

        if (pageCount <= 0 && scannedPages.length === 0) {
            const xeroxPriceInfo = document.getElementById('xeroxPriceInfo');
            if (xeroxPriceInfo) xeroxPriceInfo.style.display = 'none';
            return;
        }

        const colorModeVal = xeroxColorMode ? xeroxColorMode.value : 'Black & White';
        const printSideVal = xeroxPrintSide ? xeroxPrintSide.value : 'Single';
        const copiesVal = xeroxCopies ? parseInt(xeroxCopies.value) || 1 : 1;

        // BILLING FIX: Apply layout-based sheet calculation for Xerox pricing (before preview)
        // If we don't have a backend result yet, we calculate the number of sheets locally
        if (backendTotalAmount === null) {
            const xeroxLayoutPages = document.getElementById('xeroxLayoutPages');
            const layoutVal = parseInt(xeroxLayoutPages ? xeroxLayoutPages.value : 1) || 1;
            if (layoutVal > 1 && pageCount > 0) {
                pageCount = Math.ceil(pageCount / layoutVal);
            }
        }

        const price = calculatePrice(pageCount, colorModeVal, printSideVal, copiesVal);

        const xeroxPriceInfo = document.getElementById('xeroxPriceInfo');
        const xeroxTotalPages = document.getElementById('xeroxTotalPages');
        const xeroxPricePerPage = document.getElementById('xeroxPricePerPage');
        const xeroxTotalAmount = document.getElementById('xeroxTotalAmount');

        if (xeroxPriceInfo && xeroxTotalPages && xeroxPricePerPage && xeroxTotalAmount) {
            xeroxTotalPages.textContent = pageCount;
            const pRow = xeroxPricePerPage.closest('.price-row');
            if (price.isMixed) {
                const isDouble = printSideVal === 'Double';
                const bwPrice = isDouble ? shopPricing.bw_double : shopPricing.bw_single;
                const colorPrice = isDouble ? shopPricing.color_double : shopPricing.color_single;

                if (pRow) {
                    pRow.style.flexDirection = 'column';
                    pRow.style.alignItems = 'flex-start';
                }
                xeroxPricePerPage.style.width = '100%';
                xeroxPricePerPage.innerHTML = `
                    <div style="display: flex; justify-content: space-between; width: 100%; margin-top: 5px; font-size: 13px;">
                        <span>Black & White:</span>
                        <span>₹${bwPrice.toFixed(2)}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; width: 100%; margin-top: 2px; font-size: 13px;">
                        <span>Color:</span>
                        <span>₹${colorPrice.toFixed(2)}</span>
                    </div>
                `;
            } else {
                if (pRow) {
                    pRow.style.flexDirection = 'row';
                    pRow.style.alignItems = 'center';
                }
                xeroxPricePerPage.style.width = 'auto';
                xeroxPricePerPage.textContent = `₹${price.pricePerPage.toFixed(2)}`;
            }
            xeroxTotalAmount.textContent = `₹${price.total.toFixed(2)}`;
            xeroxPriceInfo.style.display = 'block';
        }

        // Also update the preview Total Amount card for Xerox to match Print flow
        const effectivePageCount = currentPageCount || pageCount;
        updatePreviewPriceDisplay(effectivePageCount, colorModeVal, printSideVal, copiesVal);
    }

    // Update price display in preview section
    function updatePreviewPriceDisplay(pageCount, colorModeVal, printSideVal, copiesVal) {
        const previewPriceInfo = document.getElementById('previewPriceInfo');
        const previewTotalPages = document.getElementById('previewTotalPages');
        const previewPricePerPage = document.getElementById('previewPricePerPage');
        const previewTotalAmount = document.getElementById('previewTotalAmount');

        if (!previewPriceInfo || !previewTotalPages || !previewPricePerPage || !previewTotalAmount) return;

        if (pageCount <= 0) {
            previewPriceInfo.style.display = 'none';
            return;
        }

        const price = calculatePrice(pageCount, colorModeVal, printSideVal, copiesVal);

        // Fix: Update total pages in preview billing summary
        previewTotalPages.textContent = pageCount;

        if (price.isMixed) {
            const isDouble = printSideVal === 'Double';
            const bwPrice = isDouble ? shopPricing.bw_double : shopPricing.bw_single;
            const colorPrice = isDouble ? shopPricing.color_double : shopPricing.color_single;

            const pRow = previewPricePerPage.closest('.price-row');
            if (pRow) {
                pRow.style.flexDirection = 'column';
                pRow.style.alignItems = 'flex-start';
            }
            previewPricePerPage.style.width = '100%';
            previewPricePerPage.innerHTML = `
                <div style="display: flex; justify-content: space-between; width: 100%; margin-top: 5px; font-size: 13px;">
                    <span>Black & White:</span>
                    <span>₹${bwPrice.toFixed(2)}</span>
                </div>
                <div style="display: flex; justify-content: space-between; width: 100%; margin-top: 2px; font-size: 13px;">
                    <span>Color:</span>
                    <span>₹${colorPrice.toFixed(2)}</span>
                </div>
            `;
        } else {
            const pRow = previewPricePerPage.closest('.price-row');
            if (pRow) {
                pRow.style.flexDirection = 'row';
                pRow.style.alignItems = 'center';
            }
            previewPricePerPage.style.width = 'auto';
            previewPricePerPage.textContent = `₹${price.pricePerPage.toFixed(2)}`;
        }
        previewTotalAmount.textContent = `₹${price.total.toFixed(2)}`;
        previewPriceInfo.style.display = 'block';
    }

    function updateImageTransform() {
        if (previewImage) {
            previewImage.style.transform = `scale(${currentZoom}) rotate(${currentRotation}deg)`;
        }
        if (zoomLevel) {
            zoomLevel.textContent = Math.round(currentZoom * 100) + '%';
        }
    }

    // Update preview with delay to prevent excessive requests
    // DEBOUNCE FIX: 500ms debounce + cancels any in-flight PRINT preview request
    function updatePreviewWithDelay() {
        if (previewTimeout) {
            clearTimeout(previewTimeout);
        }
        // Cancel any in-flight print preview request immediately on new input
        if (printPreviewAbortController) {
            printPreviewAbortController.abort();
            printPreviewAbortController = null;
        }
        previewTimeout = setTimeout(() => {
            if (currentFile) {
                // Clear backend amount when settings change, so we don't show stale mixed pricing
                backendTotalAmount = null;
                generatePreview(false);
            }
        }, 500);
    }

    // Function to generate preview
    function generatePreview(showLoading = true) {
        // RACE-CONDITION GUARD: Do not show preview if we have transitioned to Tracking view
        if (isTrackingViewActive) return;

        if (!currentFile) {
            alert('Please select a file first');
            return;
        }

        // Show loading if requested
        if (showLoading && previewLoading) {
            previewLoading.style.display = 'flex';
        }

        // PAGE RANGE FIX: Validate page range with better error handling
        const pageRangeVal = (pageRangeInput && pageRangeInput.value || '').trim();
        if (pageRangeVal && !isValidPageRange(pageRangeVal)) {
            showPageRangeError('Invalid page range. Use format: 1-3, 5, 7-9 (numbers, commas, dashes only)');
            return;
        } else {
            // Clear error if valid
            showPageRangeError('');
        }

        // Get current print settings
        // PAGE RANGE FIX: Send page_range (can be empty string for "all pages")
        const printSettings = {
            page_range: pageRangeVal || '', // Empty string means "all pages"
            page_size: pageSize.value,
            orientation: orientation.value,
            print_side: printSide.value,
            color_mode: colorMode.value,
            layout_pages: layoutPages.value,
            copies: copies.value,
            layout_type: (function (v) {
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
            })(layoutPages.value)
        };

        // Cancel any previous in-flight PRINT preview request
        if (printPreviewAbortController) {
            printPreviewAbortController.abort();
        }
        printPreviewAbortController = new AbortController();

        // In-browser PDF/image preview (replaces legacy Flask /api/preview)
        __ezprintClientPrintPreview(
            currentFile,
            pageRangeVal,
            printSettings,
            printPreviewAbortController.signal
        )
            .then(data => {
                // RACE-CONDITION GUARD: Do not update DOM if user navigated to Tracking view
                if (isTrackingViewActive) return;
                if (data.success) {
                    // Update backend calculation results as per-copy base values
                    const currentCopies = parseInt(copies ? copies.value : 1) || 1;
                    backendTotalAmount = (data.total_amount && data.total_amount > 0)
                        ? (data.total_amount / currentCopies) : null;
                    backendColorSheets = data.color_sheets;
                    backendBWSheets = data.bw_sheets;

                    // PAGE RANGE FIX: Store filtered preview URLs based on page range
                    if (data.previews && Array.isArray(data.previews) && data.previews.length > 0) {
                        previewUrls = data.previews;
                        // total_pages now represents the number of SELECTED pages (after filtering)
                        totalPages = data.total_pages || data.previews.length;
                    } else if (data.preview_url) {
                        // Backward compatibility: single preview URL
                        previewUrls = [data.preview_url];
                        totalPages = data.total_pages || 1;
                    } else {
                        throw new Error('No preview URLs received');
                    }

                    // Reset to first page of filtered selection
                    currentPageIndex = 0;

                    // Update preview image
                    if (previewImage) {
                        previewImage.src = previewUrls[0];
                    }
                    if (previewSection) {
                        previewSection.dataset.source = 'print';
                        if (currentMode === 'print') {
                            previewSection.style.display = 'block';
                        }
                    }

                    // Update file information
                    const fileSize = (currentFile.size / 1024 / 1024).toFixed(2);
                    previewFilename.textContent = currentFile.name;
                    previewSize.textContent = `${fileSize} MB`;

                    // LAYOUT FIX: Show correct preview page count based on layout
                    // totalPages now represents preview sheets (after layout combining)
                    // If layout is applied, show layout info; if page range is applied, show range info
                    let pageCountText = totalPages.toString();

                    if (data.layout_pages && data.layout_pages > 1) {
                        // Layout is applied - show sheet count
                        if (data.selected_document_pages && data.total_document_pages) {
                            // Page range might also be applied
                            if (data.selected_document_pages !== data.total_document_pages) {
                                pageCountText = `${totalPages} sheets (${data.selected_document_pages} pages, ${data.layout_pages} per sheet)`;
                            } else {
                                pageCountText = `${totalPages} sheets (${data.layout_pages} per sheet)`;
                            }
                        } else {
                            pageCountText = `${totalPages} sheets (${data.layout_pages} per sheet)`;
                        }
                    } else if (data.total_document_pages && data.total_document_pages !== totalPages) {
                        // Only page range is applied (no layout)
                        pageCountText = `${totalPages} (of ${data.total_document_pages})`;
                    }

                    previewPages.textContent = pageCountText;

                    // Update current page count for price calculation
                    // Use selected_document_pages if available (actual pages to print), otherwise use totalPages
                    // BILLING FIX: Price is CALCULATED per physical sheet (printed side)
                    // totalPages already represents calculated preview sheets (after layout).
                    currentPageCount = totalPages;

                    // Update price display
                    updatePriceDisplay();

                    // PAGE RANGE FIX: Show warning if page range had issues
                    if (data.page_range_warning) {
                        showPageRangeError(data.page_range_warning);
                    }

                    // Update layout info
                    const layoutText = (function (v) {
                        switch (v) {
                            case '1': return '1 per sheet';
                            case '2': return '2 per sheet';
                            case '4': return '4 per sheet';
                            case '6': return '6 per sheet';
                            case '8': return '8 per sheet';
                            case '9': return '9 per sheet';
                            case '16': return '16 per sheet';
                            default: return '1 per sheet';
                        }
                    })(layoutPages.value);
                    previewLayout.textContent = layoutText;

                    // Update other customization details
                    if (previewOrientation) previewOrientation.textContent = orientation.value;
                    if (previewPrintSide) previewPrintSide.textContent = printSide.value;
                    if (previewColorMode) previewColorMode.textContent = colorMode.value;
                    if (previewCopies) previewCopies.textContent = copies.value;
                    if (previewPageRange) previewPageRange.textContent = pageRangeInput.value || 'All Pages';

                    // Show/hide navigation controls based on page count
                    if (totalPages > 1) {
                        if (prevPageBtn) {
                            prevPageBtn.style.display = 'inline-block';
                            prevPageBtn.disabled = true;
                            prevPageBtn.style.opacity = '0.5';
                        }
                        if (nextPageBtn) {
                            nextPageBtn.style.display = 'inline-block';
                            nextPageBtn.disabled = totalPages <= 1;
                            nextPageBtn.style.opacity = totalPages <= 1 ? '0.5' : '1';
                        }
                        if (pageIndicator) {
                            pageIndicator.style.display = 'inline-block';
                            pageIndicator.textContent = `Page 1 of ${totalPages}`;
                        }
                    } else {
                        // Single page: hide navigation
                        if (prevPageBtn) prevPageBtn.style.display = 'none';
                        if (nextPageBtn) nextPageBtn.style.display = 'none';
                        if (pageIndicator) pageIndicator.style.display = 'none';
                    }

                    // Reset zoom and rotation
                    currentZoom = 1;
                    currentRotation = 0;
                    updateImageTransform();

                    if (showLoading) {
                        scrollToElement(previewSection);
                    } else {
                        setTimeout(() => scrollToElement(previewSection), 300);
                    }
                } else {
                    throw new Error(data.error || 'Preview failed');
                }
            })
            .catch(error => {
                // Silently ignore aborted requests (user changed settings again)
                if (error.name === 'AbortError') {
                    console.info('PRINT preview request aborted (superseded by newer request)');
                    return;
                }
                console.error('Preview error:', error);
                if (showLoading) {
                    alert('Failed to create preview: ' + error.message);
                }
            })
            .finally(() => {
                if (previewLoading) {
                    previewLoading.style.display = 'none';
                }
            });
    }

    // Edit button handler
    editBtn.addEventListener('click', function () {
        previewSection.style.display = 'none';
        if (currentMode === 'xerox' && xeroxSettingsSection) {
            scrollToElement(xeroxSettingsSection);
        } else if (uploadForm) {
            scrollToElement(uploadForm);
        }
    });

    // Confirm print button handler
    confirmPrintBtn.addEventListener('click', function () {
        if (currentJobId) {
            // Job already created, just show status
            showStatusSection();
        } else {
            // Create new job
            if (currentMode === 'xerox') {
                uploadXeroxDocument();
            } else {
                uploadForm.dispatchEvent(new Event('submit'));
            }
        }
    });

    // XEROX Preview handler (bypasses debounce for immediate preview)
    if (xeroxPreviewBtn) {
        xeroxPreviewBtn.addEventListener('click', function () {
            // Cancel any pending debounced preview
            if (xeroxPreviewDebounceTimer) {
                clearTimeout(xeroxPreviewDebounceTimer);
                xeroxPreviewDebounceTimer = null;
            }
            // Generate preview immediately
            currentPreviewPromise = generateXeroxPreview(true).catch(err => {
                // Ignore stale errors
                if (err && err.stale) return;
                console.warn('XEROX: Preview generation failed:', err);
            });
        });
    }

    // Wire all XEROX customization inputs to trigger auto-preview
    function setupXeroxAutoPreview() {
        // Get all XEROX customization inputs
        const xeroxCopiesInput = document.getElementById('xeroxCopies');
        const xeroxPageRangeInput = document.getElementById('xeroxPageRange');
        const xeroxPageSizeInput = document.getElementById('xeroxPageSize');
        const xeroxOrientationInput = document.getElementById('xeroxOrientation');
        const xeroxPrintSideInput = document.getElementById('xeroxPrintSide');
        const xeroxColorModeInput = document.getElementById('xeroxColorMode');
        const xeroxLayoutPagesInput = document.getElementById('xeroxLayoutPages');

        // Helper function to validate and schedule preview
        const schedulePreview = function () {
            // Validate page range if present
            if (xeroxPageRangeInput && xeroxPageRangeInput.value.trim()) {
                const prVal = xeroxPageRangeInput.value.trim();
                if (!isValidPageRange(prVal)) {
                    // Invalid page range - don't schedule preview, show error
                    showXeroxPreviewError('Invalid page range format');
                    return;
                }
            }

            // Validate copies
            if (xeroxCopiesInput) {
                const copies = parseInt(xeroxCopiesInput.value, 10);
                if (isNaN(copies) || copies < 1 || copies > 10) {
                    return; // Invalid copies - don't schedule preview
                }
            }

            // Schedule preview update
            scheduleXeroxPreviewUpdate();
        };

        // Wire up all inputs
        if (xeroxCopiesInput) {
            xeroxCopiesInput.addEventListener('change', schedulePreview);
            xeroxCopiesInput.addEventListener('input', schedulePreview); // For keyboard input
        }

        if (xeroxPageRangeInput) {
            xeroxPageRangeInput.addEventListener('change', schedulePreview);
            xeroxPageRangeInput.addEventListener('input', schedulePreview);
        }

        if (xeroxPageSizeInput) {
            xeroxPageSizeInput.addEventListener('change', schedulePreview);
        }

        if (xeroxOrientationInput) {
            xeroxOrientationInput.addEventListener('change', schedulePreview);
        }

        if (xeroxPrintSideInput) {
            xeroxPrintSideInput.addEventListener('change', schedulePreview);
        }

        if (xeroxColorModeInput) {
            xeroxColorModeInput.addEventListener('change', schedulePreview);
        }

        if (xeroxLayoutPagesInput) {
            xeroxLayoutPagesInput.addEventListener('change', schedulePreview);
        }
    }

    // Setup auto-preview when DOM is ready
    setupXeroxAutoPreview();

    // XEROX Upload handler
    if (xeroxSettingsForm) {
        xeroxSettingsForm.addEventListener('submit', function (e) {
            e.preventDefault();
            uploadXeroxDocument();
        });
    }

    // Generate preview for XEROX scanned images (internal function, can be called with or without debounce)
    // Returns a promise that resolves when preview is ready, rejects on error
    async function generateXeroxPreview(immediate = false) {
        // RACE-CONDITION GUARD: Do not show preview if we have transitioned to Tracking view
        if (isTrackingViewActive) return Promise.reject(new Error('Tracking active'));

        if (!scannedPages || scannedPages.length === 0) {
            // Show "No scanned document" indicator if preview section is visible
            if (previewSection && previewSection.style.display !== 'none') {
                showXeroxPreviewError('No scanned document available');
            }
            previewInProgress = false;
            previewReadyForPrint = false;
            updatePreviewUIState();
            return Promise.reject(new Error('No scanned document available'));
        }

        // Increment generation ID to invalidate stale previews
        previewGenerationId += 1;
        const myGen = previewGenerationId;

        // Cancel any previous request
        if (xeroxPreviewAbortController) {
            xeroxPreviewAbortController.abort();
        }

        // Create new AbortController for this request
        xeroxPreviewAbortController = new AbortController();

        // Clear timeout message timer
        if (xeroxPreviewTimeout) {
            clearTimeout(xeroxPreviewTimeout);
            xeroxPreviewTimeout = null;
        }

        // Set preview state
        previewInProgress = true;
        previewReadyForPrint = false;
        updatePreviewUIState();

        // Create promise that resolves only if this generation is still current
        const previewPromise = (async () => {
            // RACE-CONDITION GUARD: Do not touch DOM if tracking view is active
            if (isTrackingViewActive) return;

            try {
                // Validate image sizes & collect metadata
                const { metadata } = getXeroxDocumentFiles();

                // Show loading spinner
                if (previewLoading) {
                    previewLoading.style.display = 'block';
                    previewLoading.querySelector('span').textContent = 'Updating preview...';
                }
                if (previewSection) {
                    previewSection.dataset.source = 'xerox';
                    if (currentMode === 'xerox') {
                        previewSection.style.display = 'block';
                    }
                }

                // Hide any previous error
                hideXeroxPreviewError();

                // Set timeout message after 6 seconds
                xeroxPreviewTimeout = setTimeout(() => {
                    if (previewLoading) {
                        previewLoading.querySelector('span').textContent = 'Preview taking longer than expected — please wait';
                    }
                }, XEROX_PREVIEW_TIMEOUT_MS);

                // Get customization options
                const opts = {
                    page_size: document.getElementById('xeroxPageSize').value,
                    orientation: document.getElementById('xeroxOrientation').value,
                    color_mode: document.getElementById('xeroxColorMode').value,
                    print_side: document.getElementById('xeroxPrintSide').value,
                    page_range: document.getElementById('xeroxPageRange').value.trim(),
                    layout_pages: document.getElementById('xeroxLayoutPages').value,
                    copies: document.getElementById('xeroxCopies') ? document.getElementById('xeroxCopies').value : 1
                };

                console.info('XEROX auto-preview: request started', opts);

                // Convert scanned images to PDF for preview
                const pdfBlob = await convertScannedPagesToPDF();
                const pdfFile = new File([pdfBlob], `scanned_document_${Date.now()}.pdf`, {
                    type: 'application/pdf'
                });

                const data = await __ezprintClientXeroxPreview(
                    pdfFile,
                    opts.page_range,
                    xeroxPreviewAbortController.signal
                );

                // Check if request was aborted
                if (xeroxPreviewAbortController.signal.aborted) {
                    return;
                }

                // RACE-CONDITION GUARD: Stop if we navigated away
                if (isTrackingViewActive) return;

                if (data.success && data.previews && data.previews.length > 0) {
                    // Update backend calculation results for XEROX as per-copy base values
                    const currentCopies = parseInt(document.getElementById('xeroxCopies') ? document.getElementById('xeroxCopies').value : 1) || 1;
                    backendTotalAmount = (data.total_amount && data.total_amount > 0)
                        ? (data.total_amount / currentCopies) : null;
                    backendColorSheets = data.color_sheets;
                    backendBWSheets = data.bw_sheets;

                    previewUrls = data.previews;
                    totalPages = previewUrls.length;

                    // Keep current page index if still valid, otherwise reset to 0
                    if (currentPageIndex >= totalPages) {
                        currentPageIndex = 0;
                    }

                    // Check if this preview is still current (not stale)
                    if (myGen !== previewGenerationId) {
                        console.info('XEROX: Preview result is stale, discarding', { myGen, current: previewGenerationId });
                        return Promise.reject({ stale: true });
                    }

                    // Show current page and wait for image to load
                    await new Promise((resolve, reject) => {
                        const img = previewImage;
                        const timeout = setTimeout(() => {
                            reject(new Error('Preview image load timeout'));
                        }, 10000);

                        img.onload = () => {
                            clearTimeout(timeout);
                            resolve();
                        };
                        img.onerror = () => {
                            clearTimeout(timeout);
                            reject(new Error('Preview image failed to load'));
                        };

                        img.src = previewUrls[currentPageIndex];
                    });

                    // Double-check generation ID after image load
                    if (myGen !== previewGenerationId) {
                        console.info('XEROX: Preview image loaded but generation is stale, discarding', { myGen, current: previewGenerationId });
                        return Promise.reject({ stale: true });
                    }

                    // Update preview info
                    previewFilename.textContent = `scanned_document_${Date.now()}.pdf`;
                    const totalSize = scannedPages.reduce((sum, p) => sum + p.blob.size, 0) / 1024 / 1024;
                    previewSize.textContent = `${totalSize.toFixed(2)} MB`;
                    previewPages.textContent = totalPages.toString();

                    // Update price display for xerox
                    currentPageCount = totalPages;
                    updateXeroxPriceDisplay();
                    try {
                        const colorModeVal = document.getElementById('xeroxColorMode') ? document.getElementById('xeroxColorMode').value : 'Black & White';
                        const printSideVal = document.getElementById('xeroxPrintSide') ? document.getElementById('xeroxPrintSide').value : 'Single';
                        const copiesVal = document.getElementById('xeroxCopies') ? (parseInt(document.getElementById('xeroxCopies').value) || 1) : 1;
                        updatePreviewPriceDisplay(totalPages, colorModeVal, printSideVal, copiesVal);
                    } catch (e) { }

                    // Update layout info
                    const layoutText = (function (v) {
                        switch (v) {
                            case '1': return '1 per sheet';
                            case '2': return '2 per sheet';
                            case '4': return '4 per sheet';
                            case '6': return '6 per sheet';
                            case '8': return '8 per sheet';
                            case '9': return '9 per sheet';
                            case '16': return '16 per sheet';
                            default: return '1 per sheet';
                        }
                    })(opts.layout_pages);
                    previewLayout.textContent = layoutText;

                    // Update other customization details
                    if (previewOrientation) previewOrientation.textContent = opts.orientation;
                    if (previewPrintSide) previewPrintSide.textContent = xeroxPrintSide.value;
                    if (previewColorMode) previewColorMode.textContent = opts.color_mode;
                    if (previewCopies) previewCopies.textContent = xeroxCopies.value;
                    if (previewPageRange) previewPageRange.textContent = opts.page_range || 'All Pages';

                    // Show/hide navigation controls
                    if (totalPages > 1) {
                        if (prevPageBtn) {
                            prevPageBtn.style.display = 'inline-block';
                            prevPageBtn.disabled = currentPageIndex === 0;
                        }
                        if (nextPageBtn) {
                            nextPageBtn.style.display = 'inline-block';
                            nextPageBtn.disabled = currentPageIndex >= totalPages - 1;
                        }
                        if (pageIndicator) {
                            pageIndicator.style.display = 'inline-block';
                            pageIndicator.textContent = `Page ${currentPageIndex + 1} of ${totalPages}`;
                        }
                    } else {
                        if (prevPageBtn) prevPageBtn.style.display = 'none';
                        if (nextPageBtn) nextPageBtn.style.display = 'none';
                        if (pageIndicator) pageIndicator.style.display = 'none';
                    }

                    // Reset zoom and rotation if this is a new preview (not just updating)
                    if (currentPageIndex === 0 && previewUrls.length !== previewUrls.length) {
                        currentZoom = 1;
                        currentRotation = 0;
                    }
                    updateImageTransform();

                    // Show success toast (optional UX polish)
                    showXeroxPreviewToast('Preview updated');
                    setTimeout(() => scrollToElement(previewSection), 300);

                    console.info('XEROX auto-preview: request complete', { pages: totalPages, generationId: myGen });

                    // Mark preview as ready only if still current
                    if (myGen === previewGenerationId) {
                        previewInProgress = false;
                        previewReadyForPrint = true;
                        updatePreviewUIState();
                    }

                    return { generationId: myGen, previews: previewUrls, totalPages };
                } else {
                    throw new Error(data.error || 'Preview failed');
                }
            } catch (error) {
                // Don't show error if request was aborted (user changed options again) or stale
                if (error.name === 'AbortError' || (error && error.stale)) {
                    throw { stale: true };
                }

                // Only update state if this generation is still current
                if (myGen === previewGenerationId) {
                    previewInProgress = false;
                    previewReadyForPrint = false;
                    updatePreviewUIState(error);
                    console.error('XEROX Preview error:', error);
                    showXeroxPreviewError('Preview not available — try again');
                }

                throw error;
            } finally {
                // Clear timeout
                if (xeroxPreviewTimeout) {
                    clearTimeout(xeroxPreviewTimeout);
                    xeroxPreviewTimeout = null;
                }

                // Hide loading spinner (only if this generation is still current)
                if (myGen === previewGenerationId && previewLoading) {
                    previewLoading.style.display = 'none';
                    previewLoading.querySelector('span').textContent = 'Updating preview...';
                }
            }
        })();

        // Store promise reference
        currentPreviewPromise = previewPromise;

        // Handle promise rejection silently for stale results
        previewPromise.catch(err => {
            if (err && err.stale) {
                // Silently ignore stale results
                return;
            }
        });

        return previewPromise;
    }

    // Schedule XEROX preview update with debounce (called on customization option changes)
    function scheduleXeroxPreviewUpdate() {
        // Only schedule if in XEROX mode and have scanned pages
        if (currentMode !== 'xerox' || !scannedPages || scannedPages.length === 0) {
            previewReadyForPrint = false;
            updatePreviewUIState();
            return;
        }

        // Reset preview ready state when customization changes
        previewReadyForPrint = false;
        backendTotalAmount = null; // Clear backend amount for XEROX settings change
        updatePreviewUIState();

        // Clear existing debounce timer
        if (xeroxPreviewDebounceTimer) {
            clearTimeout(xeroxPreviewDebounceTimer);
        }

        // Schedule new preview update after debounce delay
        xeroxPreviewDebounceTimer = setTimeout(() => {
            xeroxPreviewDebounceTimer = null;
            currentPreviewPromise = generateXeroxPreview(false).catch(err => {
                // Ignore stale errors
                if (err && err.stale) return;
                console.warn('XEROX: Preview generation failed:', err);
            });
        }, XEROX_PREVIEW_DEBOUNCE_MS);
    }

    // Helper: Promise with timeout
    function promiseTimeout(promise, timeoutMs) {
        return Promise.race([
            promise,
            new Promise((_, reject) =>
                setTimeout(() => reject(new Error('Preview timeout')), timeoutMs)
            )
        ]);
    }

    // Update UI state based on preview status
    function updatePreviewUIState(error = null) {
        const printBtn = xeroxUploadBtn || document.getElementById('xeroxUploadBtn');
        const previewBtn = xeroxPreviewBtn || document.getElementById('xeroxPreviewBtn');

        if (!printBtn) return;

        // Remove all state classes
        printBtn.classList.remove('preview-in-progress', 'preview-ready', 'preview-failed');

        if (error) {
            printBtn.classList.add('preview-failed');
            printBtn.disabled = false; // Allow retry
        } else if (previewInProgress) {
            printBtn.classList.add('preview-in-progress');
            printBtn.disabled = false; // Allow click to wait
        } else if (previewReadyForPrint) {
            printBtn.classList.add('preview-ready');
            printBtn.disabled = false;
        } else {
            printBtn.disabled = false; // Default: allow print (may trigger preview)
        }
    }

    // Show preview error message (non-blocking)
    function showXeroxPreviewError(message) {
        // Remove existing error if any
        hideXeroxPreviewError();

        // Create error banner
        const errorBanner = document.createElement('div');
        errorBanner.id = 'xeroxPreviewError';
        errorBanner.className = 'xerox-preview-error';
        errorBanner.textContent = message;

        // Insert before preview viewport
        if (previewSection) {
            const viewport = previewSection.querySelector('.preview-viewport');
            if (viewport && viewport.parentNode) {
                viewport.parentNode.insertBefore(errorBanner, viewport);
            }
        }
    }

    // Hide preview error message
    function hideXeroxPreviewError() {
        const errorBanner = document.getElementById('xeroxPreviewError');
        if (errorBanner) {
            errorBanner.remove();
        }
    }

    // Show success toast (optional UX polish)
    function showXeroxPreviewToast(message) {
        // Remove existing toast if any
        const existingToast = document.getElementById('xeroxPreviewToast');
        if (existingToast) {
            existingToast.remove();
        }

        // Create toast
        const toast = document.createElement('div');
        toast.id = 'xeroxPreviewToast';
        toast.className = 'xerox-preview-toast';
        toast.textContent = message;

        // Insert in preview section
        if (previewSection) {
            previewSection.appendChild(toast);

            // Fade out after 2 seconds
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.3s';
                setTimeout(() => toast.remove(), 300);
            }, 2000);
        }
    }

    // Upload XEROX document
    async function uploadXeroxDocument() {
        if (!scannedPages || scannedPages.length === 0) {
            alert('No scanned document available');
            return;
        }

        // If preview is ready, proceed immediately
        if (previewReadyForPrint) {
            return await submitXeroxPrintJob();
        }

        // If preview is in progress, wait for it with timeout
        if (previewInProgress && currentPreviewPromise) {
            const printBtn = xeroxUploadBtn || document.getElementById('xeroxUploadBtn');
            const originalText = printBtn ? printBtn.innerHTML : '';

            // Show waiting state
            if (printBtn) {
                printBtn.innerHTML = '<span class="preview-spinner"></span> Waiting for preview...';
                printBtn.disabled = true;
            }

            try {
                // Wait for preview with timeout
                await promiseTimeout(currentPreviewPromise, PREVIEW_AWAIT_TIMEOUT_MS);

                // Restore button
                if (printBtn) {
                    printBtn.innerHTML = originalText;
                    printBtn.disabled = false;
                }

                // Check if preview is now ready
                if (previewReadyForPrint) {
                    return await submitXeroxPrintJob();
                } else {
                    showXeroxPreviewError('Preview failed — please retry preview or re-upload');
                    return;
                }
            } catch (error) {
                // Restore button
                if (printBtn) {
                    printBtn.innerHTML = originalText;
                    printBtn.disabled = false;
                }

                if (error.message === 'Preview timeout') {
                    showXeroxPreviewError('Preview timed out — please retry preview');
                } else if (error && error.stale) {
                    // Stale preview, try again
                    return await uploadXeroxDocument();
                } else {
                    showXeroxPreviewError('Preview generation failed — please retry');
                }
                return;
            }
        }

        // No preview requested yet — start one then wait
        try {
            currentPreviewPromise = generateXeroxPreview(true);
            await promiseTimeout(currentPreviewPromise, PREVIEW_AWAIT_TIMEOUT_MS);

            if (previewReadyForPrint) {
                return await submitXeroxPrintJob();
            } else {
                showXeroxPreviewError('Unable to generate preview — please retry');
                return;
            }
        } catch (error) {
            if (error && error.stale) {
                // Try again if stale
                return await uploadXeroxDocument();
            }
            showXeroxPreviewError('Preview generation failed — please retry');
            return;
        }
    }

    // Extract print job submission logic
    async function submitXeroxPrintJob() {
        // Double-submit guard
        if (_uploadInFlight) return;
        _uploadInFlight = true;
        try {
            const prVal = (document.getElementById('xeroxPageRange') && document.getElementById('xeroxPageRange').value || '').trim();
            if (prVal && !isValidPageRange(prVal)) {
                alert('Invalid page range. Use format: 1-3, 5, 7-9 (numbers, commas, dashes only)');
                return;
            }

            if (!scannedPages || scannedPages.length === 0) {
                alert('No scanned pages to upload');
                return;
            }

            const pdfBlob = await convertScannedPagesToPDF();
            const upFile = new File([pdfBlob], 'scanned_' + Date.now() + '.pdf', { type: 'application/pdf' });
            const lp = parseInt(document.getElementById('xeroxLayoutPages').value, 10) || 1;

            // Show loading
            xeroxUploadBtn.innerHTML = '<span class="loading"></span> Uploading...';
            xeroxUploadBtn.disabled = true;

            const res = await __ezprintSubmitFile(upFile, {
                copies: parseInt(document.getElementById('xeroxCopies').value, 10) || 1,
                page_size: document.getElementById('xeroxPageSize').value,
                orientation: document.getElementById('xeroxOrientation').value,
                print_side: document.getElementById('xeroxPrintSide').value,
                color_mode: document.getElementById('xeroxColorMode').value,
                layout_pages: lp,
                layout_type: __ezprintLayoutType(String(lp)),
                page_range: prVal || null,
                customer_name: null,
                customer_phone: null,
            });

            currentJobId = res.job_id;
            showStatusSection();
            initSingleJobPanel();
            startSingleJobPolling();

            if (previewSection) previewSection.style.display = 'none';
            if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';

            scannedPages = [];
            updateThumbnails();

            if (xeroxPreviewBtn) xeroxPreviewBtn.disabled = true;
            if (xeroxUploadBtn) xeroxUploadBtn.disabled = true;
        } catch (error) {
            console.error('XEROX Upload error:', error);
            alert('Upload failed: ' + error.message);
        } finally {
            _uploadInFlight = false;
            xeroxUploadBtn.innerHTML = 'Print Document';
            xeroxUploadBtn.disabled = false;
        }
    }

    // Upload form handler (PRINT flow only)
    uploadForm.addEventListener('submit', function (e) {
        e.preventDefault();

        // Double-submit guard
        if (_uploadInFlight) return;

        // Skip if in XEROX mode
        if (currentMode === 'xerox') {
            return;
        }

        if (!currentFile) {
            alert('Please select a file first');
            return;
        }

        // PAGE RANGE FIX: Validate page range before upload
        const prVal = (pageRangeInput && pageRangeInput.value || '').trim();
        if (prVal && !isValidPageRange(prVal)) {
            showPageRangeError('Invalid page range. Use format: 1-3, 5, 7-9 (numbers, commas, dashes only)');
            return;
        } else {
            // Clear error if valid
            showPageRangeError('');
        }


        const lp = parseInt(layoutPages.value, 10) || 1;

        // Show loading
        _uploadInFlight = true;
        uploadBtn.innerHTML = '<span class="loading"></span> Uploading...';
        uploadBtn.disabled = true;

        (async function () {
            try {
                const res = await __ezprintSubmitFile(currentFile, {
                    copies: parseInt(copies.value, 10) || 1,
                    page_size: pageSize.value,
                    orientation: orientation.value,
                    print_side: printSide.value,
                    color_mode: colorMode.value,
                    layout_pages: lp,
                    layout_type: __ezprintLayoutType(String(lp)),
                    page_range: prVal || null,
                    customer_name: null,
                    customer_phone: null,
                });
                currentJobId = res.job_id;
                showStatusSection();
                initSingleJobPanel();
                startSingleJobPolling();
                if (previewSection) previewSection.style.display = 'none';
                uploadForm.reset();
                currentFile = null;
                fileInfo.innerHTML = '';
                previewBtn.disabled = true;
                uploadBtn.disabled = true;
            } catch (error) {
                console.error('Upload error:', error);
                alert('Upload failed: ' + error.message);
            } finally {
                _uploadInFlight = false;
                uploadBtn.innerHTML = 'Upload & Print';
                uploadBtn.disabled = false;
            }
        })();
    });

    // Show status section
    function showStatusSection() {
        isTrackingViewActive = true; // Activating Track Your Printing view
        currentShopId = (typeof __ezprintSlug !== 'undefined') ? __ezprintSlug : null;
        const headerCard = document.querySelector('.header-card');
        const instructions = document.querySelector('.instructions');
        if (headerCard) headerCard.style.display = 'none';
        if (landingSection) landingSection.style.display = 'none';
        if (uploadSection) uploadSection.style.display = 'none';
        if (xeroxScannerSection) xeroxScannerSection.style.display = 'none';
        if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
        if (scannedReviewSection) scannedReviewSection.style.display = 'none';
        if (previewSection) previewSection.style.display = 'none';

        if (instructions) instructions.style.display = 'none';
        statusSection.style.display = 'block';
        if (jobDetailsPanel) jobDetailsPanel.style.display = 'block';
        updateJobDetailsPanel();
        scrollToElement(statusSection);
    }

    function updateJobDetailsStatus(statusText) {
        if (!jobDetailsStatus) return;
        const status = (statusText || '').toString().trim() || '-';
        jobDetailsStatus.textContent = status;
        jobDetailsStatus.classList.remove('is-pending', 'is-queue', 'is-printing', 'is-completed', 'is-failed');
        const s = status.toLowerCase();
        if (s.includes('failed')) jobDetailsStatus.classList.add('is-failed');
        else if (s.includes('completed')) jobDetailsStatus.classList.add('is-completed');
        else if (s.includes('printing')) jobDetailsStatus.classList.add('is-printing');
        else if (s.includes('queue')) jobDetailsStatus.classList.add('is-queue');
        else jobDetailsStatus.classList.add('is-pending');
    }

    const formatUniformDateTime = (d) => {
        const dateObj = d instanceof Date ? d : new Date(d);
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const dd = String(dateObj.getDate()).padStart(2, '0');
        const mon = months[dateObj.getMonth()];
        const yyyy = dateObj.getFullYear();
        let h = dateObj.getHours();
        const m = String(dateObj.getMinutes()).padStart(2, '0');
        const ampm = h >= 12 ? 'PM' : 'AM';
        h = h % 12;
        if (h === 0) h = 12;
        const hh = String(h).padStart(2, '0');
        return `${dd} ${mon} ${yyyy} , ${hh}:${m} ${ampm}`;
    };

    const formatTimeAgo = (date) => {
        if (!date) return 'Just now';
        const now = new Date();
        const diffInSeconds = Math.floor((now - date) / 1000);
        if (diffInSeconds < 60) return 'Just now';
        const diffInMinutes = Math.floor(diffInSeconds / 60);
        if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
        const diffInHours = Math.floor(diffInMinutes / 60);
        if (diffInHours < 24) return `${diffInHours}h ago`;
        return date.toLocaleDateString();
    };

    function updateJobDetailsPanel() {
        const safeText = (v) => (v && v.toString().trim() ? v.toString().trim() : '-');
        const textFromEl = (el) => (el && el.textContent ? el.textContent.toString().trim() : '');
        const selectText = (el) => {
            if (!el) return '';
            const opt = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
            return opt && opt.text ? opt.text : (el.value || '');
        };

        const filename =
            (currentFile && currentFile.name) ||
            textFromEl(previewFilename) ||
            textFromEl(singleJobFile);
        const filesize =
            textFromEl(previewSize) ||
            textFromEl(xeroxDocumentSize);
        const pages =
            textFromEl(previewPages) ||
            textFromEl(xeroxDocumentPages);

        if (jobDetailsJobId) {
            jobDetailsJobId.textContent = currentJobId ? `${currentJobId.slice(0, 8)}` : '-';
        }
        if (jobDetailsFilename) jobDetailsFilename.textContent = safeText(filename);
        if (jobDetailsFilesize) jobDetailsFilesize.textContent = safeText(filesize);
        if (jobDetailsPages) jobDetailsPages.textContent = safeText(pages);

        if (jobDetailsSettingsTags) {
            const pageSizeEl = currentMode === 'xerox' ? document.getElementById('xeroxPageSize') : pageSize;
            const orientationEl = currentMode === 'xerox' ? document.getElementById('xeroxOrientation') : orientation;
            const colorModeEl = currentMode === 'xerox' ? xeroxColorMode : colorMode;
            const printSideEl = currentMode === 'xerox' ? xeroxPrintSide : printSide;
            const copiesEl = currentMode === 'xerox' ? xeroxCopies : copies;
            const pageRangeEl = currentMode === 'xerox' ? document.getElementById('xeroxPageRange') : pageRangeInput;

            const tags = [];
            const ps = selectText(pageSizeEl);
            const ori = selectText(orientationEl);
            const cm = selectText(colorModeEl);
            const side = selectText(printSideEl);
            const layout = textFromEl(previewLayout);
            const c = copiesEl ? copiesEl.value : '';
            const pr = pageRangeEl ? (pageRangeEl.value || '').trim() : '';

            if (ps) tags.push(ps);
            if (ori) tags.push(ori);
            if (cm) tags.push(cm);
            if (side) tags.push(side);
            if (layout) tags.push(layout);
            if (c) tags.push(`Copies: ${c}`);
            tags.push(`Pages: ${pr || 'All'}`);

            jobDetailsSettingsTags.innerHTML = tags
                .map(t => `<span class="job-details-tag">${t}</span>`)
                .join('');
        }

        if (jobDetailsAmount) {
            const amountEls = [
                document.getElementById('previewTotalAmount'),
                document.getElementById('uploadTotalAmount'),
                document.getElementById('xeroxTotalAmount')
            ];
            let amountText = '';
            for (const el of amountEls) {
                const t = textFromEl(el);
                if (t) {
                    amountText = t;
                    break;
                }
            }
            jobDetailsAmount.textContent = safeText(amountText);
        }
        updateJobDetailsStatus(textFromEl(jobDetailsStatus) || 'Pending');
    }

    // Start status checking
    function startSingleJobPolling() {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }
        statusCheckInterval = setInterval(() => {
            fetchSingleJobStatus();
        }, 3000);
        fetchSingleJobStatus();
    }

    // Check job status
    function initSingleJobPanel() {
        if (!singleJobPanel) return;
        singleJobFile.textContent = currentFile ? currentFile.name : '';
        singleJobFile.title = currentFile ? currentFile.name : '';
        const type = currentFile && currentFile.name ? (currentFile.name.split('.').pop() || '').toUpperCase() : '';
        const fileTypeEl = document.getElementById('singleJobFileType');
        if (fileTypeEl) fileTypeEl.textContent = type ? `• ${type}` : '';
        singleJobMeta.textContent = `#${currentJobId.slice(0, 8)} · ${formatUniformDateTime(new Date())}`;
        singleJobError.style.display = 'none';
        singleJobPanel.style.display = 'block';
        renderSingleStepper('Pending');
        updateJobDetailsPanel();
        updateJobDetailsStatus('Pending');
    }

    function mapApiJobStatusForUi(s) {
        if (!s) return 'Pending';
        if (s === 'AwaitingUpload' || s === 'Queued') return 'In Queue';
        if (s === 'Printing') return 'Printing';
        if (s === 'Completed') return 'Completed';
        if (s === 'Failed' || s === 'Cancelled') return 'Failed';
        return s;
    }

    function fetchSingleJobStatus() {
        if (!currentJobId) return;
        __ezprintFetchJob(currentJobId)
            .then((data) => {
                if (!data || !data.status) return;
                const status = mapApiJobStatusForUi(data.status);
                renderSingleStepper(status);
                updateProgressBar(status, null);
                // Use backend-calculated amount once it's available (overrides local estimate)
                if (data.amount != null && jobDetailsAmount) {
                    jobDetailsAmount.textContent = '₹' + Number(data.amount).toFixed(2);
                }
                if (data.status === 'Failed' || data.status === 'Cancelled') {
                    singleJobError.textContent = 'This job could not be completed. Please ask the shop for help.';
                    singleJobError.style.display = 'block';
                    if (singleJobProgress) singleJobProgress.style.width = '100%';
                }
                if (data.status === 'Completed' || data.status === 'Failed' || data.status === 'Cancelled') {
                    clearInterval(statusCheckInterval);
                    statusCheckInterval = null;
                }
            })
            .catch((err) => console.error('Job status error:', err));
    }

    function renderSingleStepper(status) {
        // Redesigned Stepper to match reference:
        // Steps: In Queue, Printing, Ready for Pickup
        // Icons: SVGs for professional SaaS look

        const iconQueue = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`;
        const iconPrint = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>`;
        const iconCheck = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;

        const steps = [
            {
                title: 'In Queue',
                icon: iconQueue,
                desc: 'This step has been completed.',
                activeDesc: 'Your document is waiting in the queue.'
            },
            {
                title: 'Printing',
                icon: iconPrint,
                desc: 'This step has been completed.',
                activeDesc: 'Your document is currently printing.'
            },
            {
                title: 'Ready for Pickup',
                icon: iconCheck,
                desc: 'Your document is ready for pickup.<br>Show your Job ID at the counter.',
                activeDesc: 'Your document is ready for pickup.<br>Show your Job ID at the counter.'
            }
        ];

        let normalizedStatus = status;
        if (status === 'Printing Completed' || status.includes('Completed')) {
            normalizedStatus = 'Completed';
        }

        // Map status to step index
        let activeIdx = 0;
        if (normalizedStatus === 'Completed') {
            activeIdx = 2; // Ready for Pickup
        } else if (normalizedStatus === 'Printing Started' || normalizedStatus.includes('Printing')) {
            activeIdx = 1; // Printing
        } else {
            activeIdx = 0; // In Queue (covers Pending too)
        }

        // Update Job ID Timestamp if not set (Mocking the timestamp for SaaS feel if data missing)
        const timeEl = document.getElementById('jobEstimatedTime');
        if (timeEl && timeEl.style.display === 'none') {
            const now = new Date();
            timeEl.textContent = formatUniformDateTime(now);
            timeEl.style.display = 'block';
        }

        const html = steps.map((s, i) => {
            let cls = 'timeline-step';
            let iconContent = s.icon;
            let descContent = s.activeDesc; // Default description

            if (i < activeIdx) {
                // Completed steps
                cls += ' completed';
                descContent = s.desc;
            } else if (i === activeIdx) {
                // Current step
                cls += ' current';
            } else {
                // Future steps
                cls += ' pending';
                descContent = ''; // No description for future steps
            }

            return `
            <div class="${cls}">
                <div class="step-line"></div>
                <div class="step-icon">${iconContent}</div>
                <div class="step-content">
                    <div class="step-title">${s.title}</div>
                    <div class="step-desc">${descContent}</div>
                </div>
            </div>`;
        }).join('');

        singleJobStepper.innerHTML = html;
        updateJobDetailsStatus(normalizedStatus);

        const previewAmountEl = document.getElementById('previewTotalAmount');
        if (previewAmountEl && jobDetailsAmount) {
            const val = previewAmountEl.textContent && previewAmountEl.textContent.trim();
            if (val) jobDetailsAmount.textContent = val;
        }
    }

    function updateProgressBar(status, progress = null) {
        if (!singleJobProgress) return;
        let pct = 0;

        // Normalize status for consistent handling
        let normalizedStatus = status;
        if (status === 'Printing Completed' || status.includes('Completed')) {
            normalizedStatus = 'Completed';
        }

        if (progress !== null) {
            // Use real progress from spooler
            pct = Math.min(100, Math.max(0, progress));
        } else {
            // Fallback to status-based progress
            if (normalizedStatus === 'Pending') pct = 10;
            else if (normalizedStatus === 'In Queue') pct = 30;
            else if (normalizedStatus === 'Printing Started' || normalizedStatus === 'Printing') pct = 70;
            else if (normalizedStatus === 'Completed') pct = 100;
            else if (normalizedStatus === 'Failed') pct = 100;
        }

        singleJobProgress.style.width = pct + '%';
        const text = document.getElementById('singleJobProgressText');
        if (text) text.textContent = pct + '%';

        // Update progress bar color based on normalized status
        if (normalizedStatus === 'Failed') {
            singleJobProgress.style.backgroundColor = '#f44336';
        } else if (normalizedStatus === 'Completed') {
            singleJobProgress.style.backgroundColor = '#4caf50';
        } else if (normalizedStatus === 'Printing' || normalizedStatus === 'Printing Started') {
            singleJobProgress.style.backgroundColor = '#2196f3';
        } else {
            singleJobProgress.style.backgroundColor = '#ff9800';
        }
    }

    // ============================================
    // XEROX SCANNER FUNCTIONALITY
    // ============================================

    // Initialize landing page behavior
    function initLandingPage() {
        // Backward compatibility: if landing section doesn't exist, show upload form normally
        if (!landingSection) {
            if (uploadSection) uploadSection.style.display = 'block';
            return;
        }

        // Show landing page by default (new behavior)
        if (landingSection) landingSection.style.display = 'block';
        if (uploadSection) uploadSection.style.display = 'none';
        if (xeroxScannerSection) xeroxScannerSection.style.display = 'none';
        if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
        if (previewSection) previewSection.style.display = 'none';

        // Combined Close/Back button handler - return to landing
        if (closeScannerBtn) {
            closeScannerBtn.addEventListener('click', function () {
                currentMode = null;
                stopCamera();
                scannedPages = [];
                updateThumbnails();
                if (xeroxScannerSection) xeroxScannerSection.style.display = 'none';
                if (scannedReviewSection) scannedReviewSection.style.display = 'none';
                if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
                if (uploadSection) uploadSection.style.display = 'none';
                if (previewSection) previewSection.style.display = 'none';
                if (statusSection) statusSection.style.display = 'none';
                if (landingSection) landingSection.style.display = 'block';

            });
        }

        if (printCard) {
            printCard.addEventListener('click', function () {
                currentMode = 'print';
                stopCamera(); // Stop camera when switching to Print mode
                if (landingSection) landingSection.style.display = 'none';
                if (uploadSection) uploadSection.style.display = 'block';
                if (xeroxScannerSection) xeroxScannerSection.style.display = 'none';
                if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';

                // Restore Print preview if it exists and belongs to this section
                if (previewUrls && previewUrls.length > 0 && currentFile && previewSection && previewSection.dataset.source === 'print') {
                    previewSection.style.display = 'block';
                } else if (previewSection) {
                    previewSection.style.display = 'none';
                }
            });
        }

        // XEROX card: show scanner UI
        if (xeroxCard) {
            xeroxCard.addEventListener('click', function () {
                currentMode = 'xerox';
                if (landingSection) landingSection.style.display = 'none';
                if (uploadSection) uploadSection.style.display = 'none';
                if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';

                // Hide Print preview when entering Xerox
                if (previewSection) {
                    if (previewSection.dataset.source === 'xerox' && previewUrls && previewUrls.length > 0) {
                        previewSection.style.display = 'block';
                    } else {
                        previewSection.style.display = 'none';
                    }
                }

                if (xeroxScannerSection) xeroxScannerSection.style.display = 'block';
                initXeroxScanner();
            });
        }

        // Return to scanner from settings (header arrow)
        if (xeroxSettingsBackBtn) {
            xeroxSettingsBackBtn.addEventListener('click', function () {
                if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
                if (xeroxScannerSection) xeroxScannerSection.style.display = 'block';
                resetScannerUIState(); // Reset UI state when returning to scanner
                enableCamera(); // Restart camera when returning to scanner
            });
        }
    }

    // Reset scanner UI state (fix stuck "Processing..." labels)
    function resetScannerUIState() {
        console.log('XEROX: Resetting scanner UI state');
        if (finishScanBtn) {
            finishScanBtn.disabled = false;
            finishScanBtn.textContent = '✓';
        }
        if (captureBtn) {
            captureBtn.disabled = false;
        }
        // Ensure preview state is consistent
        previewInProgress = false;
    }

    // Initialize XEROX scanner
    function initXeroxScanner() {
        console.log('XEROX: Initializing scanner...');
        scannedPages = [];
        currentCaptureBlob = null;
        scannerPageIdCounter = 0;
        updateThumbnails();
        resetScannerUIState(); // Ensure UI is fresh

        // Try to enable camera automatically
        enableCamera();
    }

    // Enable camera access
    async function enableCamera() {
        stopCamera(); // Ensure existing stream is stopped before starting a new one
        try {
            // Check if getUserMedia is available
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error('Camera API not available');
            }

            // Request camera access (prefer rear camera on mobile)
            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: 'environment',  // Rear camera on mobile
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                }
            });

            // Show video stream
            if (cameraVideo) {
                cameraVideo.srcObject = cameraStream;
                cameraVideo.style.display = 'block';
                cameraPlaceholder.style.display = 'none';
                scannerControls.style.display = 'flex';
            }

            console.log('XEROX: Camera enabled successfully');
        } catch (error) {
            console.warn('XEROX: Camera access failed:', error);
            // Show fallback UI
            if (cameraPlaceholder) cameraPlaceholder.style.display = 'flex';
            if (cameraVideo) cameraVideo.style.display = 'none';
            if (scannerControls) scannerControls.style.display = 'none';

            // Show error message
            if (cameraPlaceholder) {
                const errorMsg = error.name === 'NotAllowedError'
                    ? 'Camera permission denied. Please allow camera access or use "Upload Images" instead.'
                    : 'Camera not available. Please use "Upload Images" instead.';
                const errorP = document.createElement('p');
                errorP.style.color = '#e53e3e';
                errorP.style.marginTop = '10px';
                errorP.textContent = errorMsg;
                cameraPlaceholder.appendChild(errorP);
            }
        }
    }

    // Stop camera stream
    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
            cameraStream = null;
        }
        if (cameraVideo) {
            cameraVideo.srcObject = null;
            cameraVideo.style.display = 'none';
        }
        if (cameraPlaceholder) cameraPlaceholder.style.display = 'flex';
        if (scannerControls) scannerControls.style.display = 'none';
    }

    // ---------------------------
    // Cropper helpers (XEROX flow)
    // ---------------------------
    function loadImageForCrop(dataUrl) {
        const canvas = document.getElementById('cropCanvas');
        if (!canvas) return;
        sourceImage.onload = () => {
            cropRotation = 0;
            resizeCanvas();
            renderImage();
            resetCropFrame();
        };
        sourceImage.src = dataUrl;
    }

    function resizeCanvas() {
        const canvas = document.getElementById('cropCanvas');
        if (!canvas || !sourceImage) return;
        const isRotated = cropRotation % 180 !== 0;
        canvas.width = isRotated ? sourceImage.naturalHeight : sourceImage.naturalWidth;
        canvas.height = isRotated ? sourceImage.naturalWidth : sourceImage.naturalHeight;
    }

    function renderImage() {
        const canvas = document.getElementById('cropCanvas');
        if (!canvas || !sourceImage) return;
        const ctx = canvas.getContext('2d');
        ctx.save();
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate(cropRotation * Math.PI / 180);
        ctx.drawImage(
            sourceImage,
            -sourceImage.naturalWidth / 2,
            -sourceImage.naturalHeight / 2
        );
        ctx.restore();
    }

    function rotateCropFrameCSS() {
        const frame = document.getElementById('cropFrame');
        if (frame) {
            frame.style.transform = `rotate(${cropRotation}deg)`;
            frame.style.transformOrigin = 'center center';
        }
    }

    function resetCropFrame() {
        const frame = document.getElementById('cropFrame');
        const canvas = document.getElementById('cropCanvas');
        if (!frame || !canvas) return;

        // Use a slight delay to ensure canvas layout is stable
        setTimeout(() => {
            const rect = canvas.getBoundingClientRect();
            const containerRect = canvas.parentElement.getBoundingClientRect();

            // Calculate coordinates relative to parent container (.cropper-canvas-wrap)
            const relLeft = rect.left - containerRect.left;
            const relTop = rect.top - containerRect.top;

            frame.style.width = (rect.width * 0.9) + 'px';
            frame.style.height = (rect.height * 0.9) + 'px';
            frame.style.left = (relLeft + rect.width * 0.05) + 'px';
            frame.style.top = (relTop + rect.height * 0.05) + 'px';

            if (!frame.dataset.initialized) {
                initCropFrameHandlers();
                frame.dataset.initialized = "true";
            }
        }, 100);
    }

    function initCropFrameHandlers() {
        const frame = document.getElementById('cropFrame');
        if (!frame) return;

        let isDragging = false;
        let isResizing = false;
        let currentHandle = null;
        let startX, startY, startLeft, startTop, startWidth, startHeight;

        const onStart = (e) => {
            const touch = e.type === 'touchstart';
            const clientX = touch ? e.touches[0].clientX : e.clientX;
            const clientY = touch ? e.touches[0].clientY : e.clientY;

            if (e.target.classList.contains('crop-handle')) {
                isResizing = true;
                currentHandle = e.target;
            } else {
                isDragging = true;
            }

            startX = clientX;
            startY = clientY;
            startLeft = frame.offsetLeft;
            startTop = frame.offsetTop;
            startWidth = frame.offsetWidth;
            startHeight = frame.offsetHeight;

            // Prevent scrolling on mobile while dragging
            if (touch) e.preventDefault();
        };

        const onMove = (e) => {
            if (!isDragging && !isResizing) return;
            const touch = e.type === 'touchmove';
            const clientX = touch ? e.touches[0].clientX : e.clientX;
            const clientY = touch ? e.touches[0].clientY : e.clientY;

            const dx = clientX - startX;
            const dy = clientY - startY;

            const canvas = document.getElementById('cropCanvas');
            const rect = canvas.getBoundingClientRect();
            const containerRect = canvas.parentElement.getBoundingClientRect();

            // Image boundaries relative to the offset parent (.cropper-canvas-wrap)
            const minX = rect.left - containerRect.left;
            const minY = rect.top - containerRect.top;
            const maxX = rect.right - containerRect.left;
            const maxY = rect.bottom - containerRect.top;

            if (isDragging) {
                let newLeft = startLeft + dx;
                let newTop = startTop + dy;

                // Clamp to image boundaries using relative coordinates
                newLeft = Math.max(minX, Math.min(newLeft, maxX - frame.offsetWidth));
                newTop = Math.max(minY, Math.min(newTop, maxY - frame.offsetHeight));

                frame.style.left = `${newLeft}px`;
                frame.style.top = `${newTop}px`;
            } else if (isResizing) {
                let newWidth = startWidth;
                let newHeight = startHeight;
                let newLeft = startLeft;
                let newTop = startTop;

                const ratio = cropperAspectMode === 'a4' ? 210 / 297 : (cropperAspectMode === 'square' ? 1 : null);

                if (currentHandle.classList.contains('se')) {
                    newWidth = Math.max(50, startWidth + dx);
                    newHeight = Math.max(50, startHeight + dy);

                    // Clamp to image bounds
                    newWidth = Math.min(newWidth, maxX - startLeft);
                    newHeight = Math.min(newHeight, maxY - startTop);

                    if (ratio) {
                        if (newWidth / newHeight > ratio) newWidth = newHeight * ratio;
                        else newHeight = newWidth / ratio;
                        // Final bound check after ratio adjustment
                        if (startLeft + newWidth > maxX) { newWidth = maxX - startLeft; newHeight = newWidth / ratio; }
                        if (startTop + newHeight > maxY) { newHeight = maxY - startTop; newWidth = newHeight * ratio; }
                    }
                } else if (currentHandle.classList.contains('sw')) {
                    newWidth = Math.max(50, startWidth - dx);
                    newHeight = Math.max(50, startHeight + dy);

                    // Clamp to image bounds
                    newWidth = Math.min(newWidth, startLeft + startWidth - minX);
                    newHeight = Math.min(newHeight, maxY - startTop);

                    if (ratio) {
                        if (newWidth / newHeight > ratio) newWidth = newHeight * ratio;
                        else newHeight = newWidth / ratio;
                        if (startLeft + startWidth - newWidth < minX) { newWidth = startLeft + startWidth - minX; newHeight = newWidth / ratio; }
                        if (startTop + newHeight > maxY) { newHeight = maxY - startTop; newWidth = newHeight * ratio; }
                    }
                    newLeft = startLeft + (startWidth - newWidth);
                } else if (currentHandle.classList.contains('ne')) {
                    newWidth = Math.max(50, startWidth + dx);
                    newHeight = Math.max(50, startHeight - dy);

                    // Clamp to image bounds
                    newWidth = Math.min(newWidth, maxX - startLeft);
                    newHeight = Math.min(newHeight, startTop + startHeight - minY);

                    if (ratio) {
                        if (newWidth / newHeight > ratio) newWidth = newHeight * ratio;
                        else newHeight = newWidth / ratio;
                        if (startLeft + newWidth > maxX) { newWidth = maxX - startLeft; newHeight = newWidth / ratio; }
                        if (startTop + startHeight - newHeight < minY) { newHeight = startTop + startHeight - minY; newWidth = newHeight * ratio; }
                    }
                    newTop = startTop + (startHeight - newHeight);
                } else if (currentHandle.classList.contains('nw')) {
                    newWidth = Math.max(50, startWidth - dx);
                    newHeight = Math.max(50, startHeight - dy);

                    // Clamp to image bounds
                    newWidth = Math.min(newWidth, startLeft + startWidth - minX);
                    newHeight = Math.min(newHeight, startTop + startHeight - minY);

                    if (ratio) {
                        if (newWidth / newHeight > ratio) newWidth = newHeight * ratio;
                        else newHeight = newWidth / ratio;
                        if (startLeft + startWidth - newWidth < minX) { newWidth = startLeft + startWidth - minX; newHeight = newWidth / ratio; }
                        if (startTop + startHeight - newHeight < minY) { newHeight = startTop + startHeight - minY; newWidth = newHeight * ratio; }
                    }
                    newLeft = startLeft + (startWidth - newWidth);
                    newTop = startTop + (startHeight - newHeight);
                }

                frame.style.width = Math.round(newWidth) + 'px';
                frame.style.height = Math.round(newHeight) + 'px';
                frame.style.left = Math.round(newLeft) + 'px';
                frame.style.top = Math.round(newTop) + 'px';
            }
        };

        const onEnd = () => {
            isDragging = false;
            isResizing = false;
            updateCropperPreview();
        };

        frame.addEventListener('mousedown', onStart);
        frame.addEventListener('touchstart', onStart, { passive: false });
        window.addEventListener('mousemove', onMove);
        window.addEventListener('touchmove', onMove, { passive: false });
        window.addEventListener('mouseup', onEnd);
        window.addEventListener('touchend', onEnd);
    }

    function openCropperModal(blob, options = {}) {
        if (!cropperModal) {
            console.error('XEROX: Cropper modal elements not found');
            return;
        }

        currentCroppingPageId = options.pageId || null;
        currentCropOriginalBlob = blob;
        currentCropOriginalThumb = options.originalThumbnail || null;
        currentCropFilename = options.filename || `scan_${(scannerPageIdCounter + 1)}.jpg`;

        // Revoke previous object URL
        if (cropperObjectUrl) {
            URL.revokeObjectURL(cropperObjectUrl);
            cropperObjectUrl = null;
        }

        // Hide and disable scanner section
        if (xeroxScannerSection) xeroxScannerSection.classList.add('inactive');
        if (cameraPreviewContainer) cameraPreviewContainer.classList.add('inactive');

        if (cameraVideo && cameraVideo.srcObject) {
            cameraVideo.pause();
        }

        document.body.style.overflow = 'hidden';
        document.body.classList.add('modal-open');

        cropperObjectUrl = URL.createObjectURL(blob);

        cropperModal.classList.add('open');
        cropperModal.style.display = 'flex';

        loadImageForCrop(cropperObjectUrl);
    }

    // Update cropper preview pane with live crop result
    function updateCropperPreview() {
        if (!sourceImage || !cropperPreview) return;

        try {
            const canvas = document.getElementById('cropCanvas');
            const frame = document.getElementById('cropFrame');
            if (!canvas || !frame) return;

            const frameRect = frame.getBoundingClientRect();
            const canvasRect = canvas.getBoundingClientRect();

            const scaleX = canvas.width / canvasRect.width;
            const scaleY = canvas.height / canvasRect.height;

            const cropX = (frameRect.left - canvasRect.left) * scaleX;
            const cropY = (frameRect.top - canvasRect.top) * scaleY;
            const cropW = frameRect.width * scaleX;
            const cropH = frameRect.height * scaleY;

            const out = document.createElement('canvas');
            out.width = Math.min(300, cropW);
            out.height = Math.min(400, cropH);
            const outCtx = out.getContext('2d');

            outCtx.drawImage(
                canvas,
                cropX, cropY, cropW, cropH,
                0, 0, out.width, out.height
            );

            cropperPreview.src = out.toDataURL('image/jpeg', 0.8);
        } catch (error) {
            console.warn('XEROX: Preview update error:', error);
        }
    }

    function closeCropperModal() {
        // Destroy cropper instance
        if (cropper) {
            cropper.destroy();
            cropper = null;
        }
        // Revoke object URL
        if (cropperObjectUrl) {
            URL.revokeObjectURL(cropperObjectUrl);
            cropperObjectUrl = null;
        }

        // Clear state
        currentCroppingPageId = null;
        currentCropOriginalBlob = null;
        currentCropOriginalThumb = null;
        currentCropFilename = null;

        // Hide modal
        if (cropperModal) {
            cropperModal.classList.remove('open');
            cropperModal.style.display = 'none';
            cropperModal.removeAttribute('aria-modal');
            cropperModal.removeAttribute('role');
            cropperModal.removeAttribute('aria-label');
        }

        // Restore scanner section visibility
        if (xeroxScannerSection) {
            xeroxScannerSection.classList.remove('inactive');
        }
        if (cameraPreviewContainer) {
            cameraPreviewContainer.classList.remove('inactive');
        }

        // Resume camera video if stream is still active
        if (cameraVideo && cameraVideo.srcObject && cameraStream) {
            cameraVideo.play().catch(err => {
                console.warn('XEROX: Could not resume camera video:', err);
            });
        }

        // Restore body scrolling
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
    }

    function updateAspectButtonLabel() {
        if (!cropperAspectBtn) return;
        const labelEl = cropperAspectBtn.querySelector('.cropper-btn-label');
        if (labelEl) {
            const label = cropperAspectMode === 'a4' ? 'A4' : (cropperAspectMode === 'square' ? '1:1' : 'Crop free');
            labelEl.textContent = label;
        }
    }

    /**
     * Safe helper function to clamp and center the crop frame inside the image boundaries.
     * Prevents the crop frame from moving outside or below the visible image.
     */
    function clampCropBoxToImage(frame, canvas, ratio) {
        if (!frame || !canvas) return;

        const rect = canvas.getBoundingClientRect();
        const containerRect = canvas.parentElement.getBoundingClientRect();

        // Coordinates relative to the parent container (.cropper-canvas-wrap)
        const relLeft = rect.left - containerRect.left;
        const relTop = rect.top - containerRect.top;

        // Calculate size: Fit inside 90% of image dimensions for better visibility
        let nextWidth = rect.width * 0.9;
        let nextHeight = nextWidth / ratio;

        if (nextHeight > rect.height * 0.9) {
            nextHeight = rect.height * 0.9;
            nextWidth = nextHeight * ratio;
        }

        // Center within the image bounds
        const left = relLeft + (rect.width - nextWidth) / 2;
        const top = relTop + (rect.height - nextHeight) / 2;

        // Apply styles to frame
        frame.style.width = Math.round(nextWidth) + 'px';
        frame.style.height = Math.round(nextHeight) + 'px';
        frame.style.left = Math.round(left) + 'px';
        frame.style.top = Math.round(top) + 'px';

        // Update the preview
        updateCropperPreview();
    }

    function toggleAspectMode() {
        if (cropperAspectMode === 'free') {
            cropperAspectMode = 'a4';
        } else if (cropperAspectMode === 'a4') {
            cropperAspectMode = 'square';
        } else {
            cropperAspectMode = 'free';
        }
        updateAspectButtonLabel();

        const frame = document.getElementById('cropFrame');
        const canvas = document.getElementById('cropCanvas');
        if (frame && canvas && cropperAspectMode !== 'free') {
            const ratio = cropperAspectMode === 'a4' ? 210 / 297 : 1;
            // Use the safe helper to recalculate, clamp and center the crop box
            clampCropBoxToImage(frame, canvas, ratio);
        }
    }

    function compressCanvas(canvas) {
        // Clamp output dimensions to keep uploads light
        const maxDim = MAX_CROP_DIMENSION;
        const ratio = Math.min(1, maxDim / Math.max(canvas.width, canvas.height));
        if (ratio < 1) {
            const offscreen = document.createElement('canvas');
            offscreen.width = Math.round(canvas.width * ratio);
            offscreen.height = Math.round(canvas.height * ratio);
            const ctx = offscreen.getContext('2d');
            ctx.drawImage(canvas, 0, 0, offscreen.width, offscreen.height);
            return offscreen;
        }
        return canvas;
    }

    function confirmCropperImage() {
        const canvas = document.getElementById('cropCanvas');
        const frame = document.getElementById('cropFrame');
        if (!canvas || !frame) {
            console.warn('XEROX: No crop elements available');
            closeCropperModal();
            return;
        }

        try {
            // Show loading state
            if (cropperConfirmBtn) {
                cropperConfirmBtn.disabled = true;
                const labelEl = cropperConfirmBtn.querySelector('.cropper-btn-label');
                if (labelEl) labelEl.textContent = 'Processing...';
            }

            const frameRect = frame.getBoundingClientRect();
            const canvasRect = canvas.getBoundingClientRect();

            const scaleX = canvas.width / canvasRect.width;
            const scaleY = canvas.height / canvasRect.height;

            const cropX = (frameRect.left - canvasRect.left) * scaleX;
            const cropY = (frameRect.top - canvasRect.top) * scaleY;
            const cropW = frameRect.width * scaleX;
            const cropH = frameRect.height * scaleY;

            const out = document.createElement('canvas');
            out.width = cropW;
            out.height = cropH;
            const outCtx = out.getContext('2d');

            outCtx.drawImage(
                canvas,
                cropX, cropY, cropW, cropH,
                0, 0, cropW, cropH
            );

            // Compress if needed
            const finalCanvas = compressCanvas(out);

            // Convert to blob
            finalCanvas.toBlob(async (blob) => {
                // Re-enable button
                if (cropperConfirmBtn) {
                    cropperConfirmBtn.disabled = false;
                    const labelEl = cropperConfirmBtn.querySelector('.cropper-btn-label');
                    if (labelEl) labelEl.textContent = 'CONTINUE';
                }

                if (!blob) {
                    console.error('XEROX: Failed to create blob from cropped canvas');
                    alert('Failed to crop image. Using original.');
                    handleCroppedResult(currentCropOriginalBlob, currentCropOriginalThumb, false, null);
                    return;
                }

                console.info('XEROX: Cropped blob created', {
                    size: (blob.size / 1024).toFixed(2) + ' KB',
                    dimensions: `${finalCanvas.width}x${finalCanvas.height}`,
                    isCropped: true
                });

                // Build thumbnail for UI preview
                const thumbCanvas = document.createElement('canvas');
                const thumbWidth = 200;
                const thumbHeight = Math.round(thumbWidth * (finalCanvas.height / finalCanvas.width));
                thumbCanvas.width = thumbWidth;
                thumbCanvas.height = thumbHeight;
                const tCtx = thumbCanvas.getContext('2d');
                tCtx.drawImage(finalCanvas, 0, 0, thumbWidth, thumbHeight);
                const thumbDataUrl = thumbCanvas.toDataURL('image/jpeg', 0.7);

                // Build crop metadata
                const cropInfo = {
                    x: Math.round(cropX),
                    y: Math.round(cropY),
                    width: Math.round(cropW),
                    height: Math.round(cropH),
                    rotate: cropRotation || 0,
                    scaleX: 1,
                    scaleY: 1
                };

                // Handle the cropped result (updates page and triggers preview)
                handleCroppedResult(blob, thumbDataUrl, true, cropInfo);
            }, 'image/jpeg', CROP_JPEG_QUALITY);
        } catch (error) {
            console.error('XEROX: Crop confirmation error:', error);

            // Re-enable button
            if (cropperConfirmBtn) {
                cropperConfirmBtn.disabled = false;
                const labelEl = cropperConfirmBtn.querySelector('.cropper-btn-label');
                if (labelEl) labelEl.textContent = 'CONTINUE';
            }

            alert('Cropping failed: ' + error.message + '. Using original capture.');
            handleCroppedResult(currentCropOriginalBlob, currentCropOriginalThumb, false, null);
        }
    }

    function handleCroppedResult(resultBlob, thumbDataUrl, isCropped, cropInfo) {
        console.log('XEROX: Handling cropped result', {
            isNewPage: currentCroppingPageId === null,
            isCropped: isCropped,
            blobSize: (resultBlob.size / 1024).toFixed(2) + ' KB'
        });

        // New page
        if (currentCroppingPageId === null) {
            addScannedPage(
                resultBlob,
                thumbDataUrl,
                currentCropOriginalBlob,
                currentCropOriginalThumb,
                currentCropFilename,
                isCropped,
                cropInfo
            );
            if (retakeBtn) retakeBtn.style.display = 'none';

            // Reset preview state when new page is added
            previewReadyForPrint = false;
            updatePreviewUIState();

            // Trigger preview update after adding new page (debounced)
            setTimeout(() => {
                if (xeroxSettingsSection && xeroxSettingsSection.style.display !== 'none') {
                    scheduleXeroxPreviewUpdate();
                }
            }, 300);
        } else {
            // Update existing page
            const pageIndex = scannedPages.findIndex(p => p.id === currentCroppingPageId);
            if (pageIndex >= 0) {
                const page = scannedPages[pageIndex];
                page.blob = resultBlob;
                page.thumbnail = thumbDataUrl || page.thumbnail;
                page.isCropped = isCropped;
                page.cropInfo = cropInfo;

                // Preserve original blob/thumbnail for undo
                if (!page.originalBlob) {
                    page.originalBlob = currentCropOriginalBlob || page.blob;
                }
                if (!page.originalThumbnail && currentCropOriginalThumb) {
                    page.originalThumbnail = currentCropOriginalThumb;
                }

                updateThumbnails();

                // Trigger preview update (debounced)
                setTimeout(() => {
                    if (xeroxSettingsSection && xeroxSettingsSection.style.display !== 'none') {
                        scheduleXeroxPreviewUpdate();
                    }
                }, 300);
            } else {
                console.warn('XEROX: Page not found for crop update', currentCroppingPageId);
            }
        }

        closeCropperModal();
    }

    function cancelCropperImage() {
        // Cancel closes modal - handled by Recapture button or ESC key
        closeCropperModal();
        // Show retake option for new captures
        if (currentCroppingPageId === null && retakeBtn) {
            retakeBtn.style.display = 'inline-block';
        }
    }

    function undoCropFromModal() {
        if (currentCroppingPageId === null) {
            // For new captures, just reset crop frame
            resetCropFrame();
            return;
        }
        const page = scannedPages.find(p => p.id === currentCroppingPageId);
        if (!page || !page.originalBlob || !page.originalThumbnail) return;
        page.blob = page.originalBlob;
        page.thumbnail = page.originalThumbnail;
        page.isCropped = false;
        page.cropInfo = null;
        updateThumbnails();
        closeCropperModal();
        setTimeout(() => scheduleXeroxPreviewUpdate(), 300);
    }

    function recaptureFromModal() {
        if (currentCroppingPageId !== null) {
            deleteScannedPage(currentCroppingPageId);
        }
        closeCropperModal();
        if (retakeBtn) retakeBtn.style.display = 'none';
        // Bring user back to camera to capture again
        if (xeroxScannerSection) {
            xeroxScannerSection.style.display = 'block';
            xeroxScannerSection.classList.remove('inactive');
            resetScannerUIState(); // Ensure camera controls are active
        }
        if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
        // Resume camera if stream exists, otherwise enable it
        if (cameraStream && cameraVideo) {
            cameraVideo.play().catch(() => {
                enableCamera();
            });
        } else {
            enableCamera();
        }
    }

    function setupCropperControls() {
        // Continue button - confirms crop
        if (cropperConfirmBtn) {
            cropperConfirmBtn.addEventListener('click', confirmCropperImage);
        }

        // Retake button - reopens camera
        if (cropperRecaptureBtn) {
            cropperRecaptureBtn.addEventListener('click', recaptureFromModal);
        }

        if (cropperRotateBtn) {
            cropperRotateBtn.addEventListener('click', () => {
                cropRotation = (cropRotation + 90) % 360;
                resizeCanvas();
                renderImage();
                rotateCropFrameCSS();
                updateCropperPreview();
            });
        }

        // Crop free / Aspect toggle button
        if (cropperAspectBtn) {
            cropperAspectBtn.addEventListener('click', toggleAspectMode);
        }

        // Doc Name button - opens name input modal
        if (cropperDocNameBtn) {
            cropperDocNameBtn.addEventListener('click', () => {
                if (cropperDocNameModal) {
                    cropperDocNameModal.style.display = 'flex';
                    if (cropperDocNameInput) {
                        cropperDocNameInput.value = currentCropFilename || '';
                        cropperDocNameInput.focus();
                    }
                }
            });
        }

        // Doc Name modal handlers
        if (cropperDocNameSave) {
            cropperDocNameSave.addEventListener('click', () => {
                if (cropperDocNameInput && cropperDocNameInput.value.trim()) {
                    currentCropFilename = cropperDocNameInput.value.trim();
                    console.info('XEROX: Document name set:', currentCropFilename);
                }
                if (cropperDocNameModal) cropperDocNameModal.style.display = 'none';
            });
        }

        if (cropperDocNameCancel) {
            cropperDocNameCancel.addEventListener('click', () => {
                if (cropperDocNameModal) cropperDocNameModal.style.display = 'none';
            });
        }

        // Close doc name modal on backdrop click
        if (cropperDocNameModal) {
            cropperDocNameModal.addEventListener('click', (e) => {
                if (e.target === cropperDocNameModal) {
                    cropperDocNameModal.style.display = 'none';
                }
            });
        }

        // Close crop modal on backdrop click (only if clicking backdrop, not content)
        if (cropperModalBackdrop) {
            cropperModalBackdrop.addEventListener('click', (e) => {
                if (e.target === cropperModalBackdrop) {
                    recaptureFromModal();
                }
            });
        }

        // Keyboard accessibility: ESC to close modals, Enter to confirm crop
        document.addEventListener('keydown', (e) => {
            if (cropperDocNameModal && cropperDocNameModal.style.display === 'flex') {
                if (e.key === 'Escape') {
                    cropperDocNameModal.style.display = 'none';
                } else if (e.key === 'Enter') {
                    if (cropperDocNameSave) cropperDocNameSave.click();
                }
                return;
            }

            if (cropperModal && cropperModal.style.display === 'flex') {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    recaptureFromModal(); // ESC = Retake (closes modal and returns to camera)
                } else if (e.key === 'Enter' && e.ctrlKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    confirmCropperImage();
                }
            }
        });
    }

    // Capture image from camera
    function captureImage() {
        if (!cameraVideo || !cameraCanvas) return;

        try {
            const video = cameraVideo;
            const canvas = cameraCanvas;
            const ctx = canvas.getContext('2d');

            // ============================================================
            // MOBILE & DESKTOP VIEWPORT-AWARE CAPTURE FIX
            // ============================================================
            // Calculate the exact portion of the video that is visible
            // in the camera preview (accounting for CSS object-fit: cover)
            // 
            // CRITICAL: Use video element's ACTUAL RENDERED dimensions,
            // not container dimensions, to handle mobile correctly.

            const videoWidth = video.videoWidth;   // Native resolution width
            const videoHeight = video.videoHeight; // Native resolution height
            const videoAspect = videoWidth / videoHeight;

            // Get the video element's ACTUAL RENDERED dimensions
            // This accounts for CSS aspect-ratio constraints on mobile
            const videoRect = video.getBoundingClientRect();
            const renderedWidth = videoRect.width;
            const renderedHeight = videoRect.height;
            const renderedAspect = renderedWidth / renderedHeight;

            console.info('XEROX: Capture dimensions', {
                nativeVideo: `${videoWidth}x${videoHeight} (aspect: ${videoAspect.toFixed(2)})`,
                renderedVideo: `${renderedWidth.toFixed(0)}x${renderedHeight.toFixed(0)} (aspect: ${renderedAspect.toFixed(2)})`,
                device: /Mobile|Android|iPhone|iPad/i.test(navigator.userAgent) ? 'mobile' : 'desktop'
            });

            // Calculate visible crop rectangle in native video coordinates
            // object-fit: cover scales the video to fill the rendered area,
            // then crops the overflow. We need to find what's actually visible.
            let sourceX, sourceY, sourceWidth, sourceHeight;

            if (videoAspect > renderedAspect) {
                // Video is wider than rendered area - crop left/right sides
                // The video is scaled to match the rendered height
                sourceHeight = videoHeight;
                sourceWidth = videoHeight * renderedAspect;
                sourceX = (videoWidth - sourceWidth) / 2;  // Center crop horizontally
                sourceY = 0;
            } else {
                // Video is taller than rendered area - crop top/bottom
                // The video is scaled to match the rendered width
                sourceWidth = videoWidth;
                sourceHeight = videoWidth / renderedAspect;
                sourceX = 0;
                sourceY = (videoHeight - sourceHeight) / 2;  // Center crop vertically
            }

            // Set canvas to match the VISIBLE portion dimensions
            canvas.width = Math.round(sourceWidth);
            canvas.height = Math.round(sourceHeight);

            // Draw ONLY the visible portion of the video to canvas
            ctx.drawImage(
                video,
                Math.round(sourceX),      // Source X (crop start X in native resolution)
                Math.round(sourceY),      // Source Y (crop start Y in native resolution)
                Math.round(sourceWidth),  // Source width (crop width in native resolution)
                Math.round(sourceHeight), // Source height (crop height in native resolution)
                0,                        // Destination X
                0,                        // Destination Y
                canvas.width,             // Destination width
                canvas.height             // Destination height
            );

            console.info('XEROX: Viewport-aware capture result', {
                videoResolution: `${videoWidth}x${videoHeight}`,
                renderedSize: `${renderedWidth.toFixed(0)}x${renderedHeight.toFixed(0)}`,
                capturedRegion: `x:${Math.round(sourceX)} y:${Math.round(sourceY)} w:${Math.round(sourceWidth)} h:${Math.round(sourceHeight)}`,
                canvasSize: `${canvas.width}x${canvas.height}`,
                cropDirection: videoAspect > renderedAspect ? 'sides' : 'top/bottom'
            });

            // Convert to blob (compressed JPEG)
            canvas.toBlob(function (blob) {
                if (!blob) {
                    alert('Failed to capture image');
                    return;
                }

                currentCaptureBlob = blob;

                // Show retake option
                if (retakeBtn) retakeBtn.style.display = 'inline-block';

                // Create thumbnail preview and open cropper modal
                const reader = new FileReader();
                reader.onload = function (e) {
                    const thumbnailUrl = e.target.result;
                    openCropperModal(blob, {
                        pageId: null,
                        originalThumbnail: thumbnailUrl,
                        filename: `scan_${scannerPageIdCounter + 1}.jpg`
                    });
                };
                reader.readAsDataURL(blob);

            }, 'image/jpeg', 0.85);  // 85% quality for reasonable file size

        } catch (error) {
            console.error('XEROX: Capture error:', error);
            alert('Failed to capture image: ' + error.message);
        }
    }

    // Add scanned page to collection
    function addScannedPage(blob, thumbnailUrl, originalBlob = null, originalThumbnail = null, filename = null, isCropped = false, cropInfo = null) {
        if (scannedPages.length >= MAX_SCANNED_PAGES) {
            alert(`Maximum ${MAX_SCANNED_PAGES} pages allowed per scan job`);
            return;
        }

        const pageId = scannerPageIdCounter++;
        scannedPages.push({
            id: pageId,
            blob: blob,
            thumbnail: thumbnailUrl,
            originalBlob: originalBlob || blob,
            originalThumbnail: originalThumbnail || thumbnailUrl,
            filename: filename || `scan_${pageId + 1}.jpg`,
            isCropped: isCropped,
            cropInfo: cropInfo,
            capturedAt: new Date()
        });

        updateThumbnails();
        console.log(`XEROX: Added page ${pageId + 1}, total: ${scannedPages.length}`);
        // Note: Preview update is triggered by handleCroppedResult, not here to avoid duplicates
    }

    // Update thumbnails display
    function updateThumbnails() {
        if (!thumbnailsGrid || !scannedPageCount) return;

        scannedPageCount.textContent = scannedPages.length;

        // Update xerox price display
        updateXeroxPriceDisplay();

        // Always clear grid first to prevent stale thumbnails
        thumbnailsGrid.innerHTML = '';

        const nativePreview = thumbnailsGrid.closest('.native-thumb-preview');

        if (scannedPages.length === 0) {
            if (scannedPagesContainer) scannedPagesContainer.style.display = 'none';
            // Always show native preview (placeholder) even when empty
            if (nativePreview) nativePreview.style.display = 'flex';
            return;
        }

        if (scannedPagesContainer) scannedPagesContainer.style.display = 'block';
        if (nativePreview) nativePreview.style.display = 'flex';

        scannedPages.forEach((page, index) => {
            const thumbnailItem = document.createElement('div');
            thumbnailItem.className = 'thumbnail-item';

            const img = document.createElement('img');
            img.src = page.thumbnail;
            img.alt = `Page ${index + 1}`;

            const pageNumber = document.createElement('div');
            pageNumber.className = 'page-number';
            pageNumber.textContent = index + 1;

            const actions = document.createElement('div');
            actions.className = 'thumbnail-actions';

            // Crop button (opens cropper with current blob, preserves original for undo)
            const cropBtn = document.createElement('button');
            cropBtn.className = 'thumbnail-btn';
            cropBtn.textContent = '✂️';
            cropBtn.title = 'Crop';
            cropBtn.onclick = () => {
                // Use current blob for cropping (allows re-cropping)
                // Original blob is preserved separately for undo
                const blobToCrop = page.blob;
                const originalBlob = page.originalBlob || page.blob;
                const originalThumb = page.originalThumbnail || page.thumbnail;

                // Ensure original is preserved before cropping
                if (!page.originalBlob) {
                    page.originalBlob = page.blob;
                }
                if (!page.originalThumbnail) {
                    page.originalThumbnail = page.thumbnail;
                }

                openCropperModal(blobToCrop, {
                    pageId: page.id,
                    originalThumbnail: originalThumb,
                    filename: page.filename || `scan_${index + 1}.jpg`
                });
            };
            actions.appendChild(cropBtn);

            // Undo crop button
            if (page.isCropped) {
                const undoBtn = document.createElement('button');
                undoBtn.className = 'thumbnail-btn';
                undoBtn.textContent = '↩';
                undoBtn.title = 'Undo Crop';
                undoBtn.onclick = () => undoCrop(page.id);
                actions.appendChild(undoBtn);
            }

            // Re-capture (delete and go back to camera)
            const recaptureBtn = document.createElement('button');
            recaptureBtn.className = 'thumbnail-btn';
            recaptureBtn.textContent = '🎥';
            recaptureBtn.title = 'Re-capture';
            recaptureBtn.onclick = () => recapturePage(page.id);
            actions.appendChild(recaptureBtn);

            // Delete button
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'thumbnail-btn';
            deleteBtn.textContent = '🗑️';
            deleteBtn.title = 'Delete';
            deleteBtn.onclick = () => deleteScannedPage(page.id);

            // Move up button (except first)
            if (index > 0) {
                const moveUpBtn = document.createElement('button');
                moveUpBtn.className = 'thumbnail-btn';
                moveUpBtn.textContent = '↑';
                moveUpBtn.title = 'Move up';
                moveUpBtn.onclick = () => movePageUp(index);
                actions.appendChild(moveUpBtn);
            }

            // Move down button (except last)
            if (index < scannedPages.length - 1) {
                const moveDownBtn = document.createElement('button');
                moveDownBtn.className = 'thumbnail-btn';
                moveDownBtn.textContent = '↓';
                moveDownBtn.title = 'Move down';
                moveDownBtn.onclick = () => movePageDown(index);
                actions.appendChild(moveDownBtn);
            }

            actions.appendChild(deleteBtn);

            thumbnailItem.appendChild(img);
            thumbnailItem.appendChild(pageNumber);
            thumbnailItem.appendChild(actions);

            thumbnailsGrid.appendChild(thumbnailItem);
        });
    }

    // Delete scanned page
    function deleteScannedPage(pageId) {
        scannedPages = scannedPages.filter(p => p.id !== pageId);
        updateThumbnails();
        setTimeout(() => scheduleXeroxPreviewUpdate(), 300);
    }

    // Move page up
    function movePageUp(index) {
        if (index <= 0) return;
        [scannedPages[index - 1], scannedPages[index]] = [scannedPages[index], scannedPages[index - 1]];
        updateThumbnails();
        setTimeout(() => scheduleXeroxPreviewUpdate(), 300);
    }

    // Move page down
    function movePageDown(index) {
        if (index >= scannedPages.length - 1) return;
        [scannedPages[index], scannedPages[index + 1]] = [scannedPages[index + 1], scannedPages[index]];
        updateThumbnails();
        setTimeout(() => scheduleXeroxPreviewUpdate(), 300);
    }

    // Undo crop back to original capture
    function undoCrop(pageId) {
        const page = scannedPages.find(p => p.id === pageId);
        if (!page || !page.originalBlob || !page.originalThumbnail) return;
        page.blob = page.originalBlob;
        page.thumbnail = page.originalThumbnail;
        page.isCropped = false;
        page.cropInfo = null;
        updateThumbnails();
        setTimeout(() => scheduleXeroxPreviewUpdate(), 300);
    }

    // Remove page and prompt user to capture again
    function recapturePage(pageId) {
        deleteScannedPage(pageId);
        if (xeroxScannerSection) xeroxScannerSection.style.display = 'block';
        if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
        resetScannerUIState(); // Reset UI state when recapturing
        enableCamera();
    }

    // Convert scanned images to PDF (client-side)
    async function convertScannedPagesToPDF() {
        if (scannedPages.length === 0) {
            throw new Error('No pages scanned');
        }

        console.log(`XEROX: Converting ${scannedPages.length} pages to PDF...`);

        try {
            // Check if pdf-lib is available
            if (typeof PDFLib === 'undefined') {
                throw new Error('PDF library not loaded. Please refresh the page.');
            }

            // Create new PDF document
            const pdfDoc = await PDFLib.PDFDocument.create();

            // Add each scanned page as a PDF page
            for (let i = 0; i < scannedPages.length; i++) {
                const page = scannedPages[i];

                // Convert blob to image
                const imageBytes = await page.blob.arrayBuffer();
                let pdfImage;

                // Try JPEG first, then PNG
                try {
                    pdfImage = await pdfDoc.embedJpg(imageBytes);
                } catch (e) {
                    pdfImage = await pdfDoc.embedPng(imageBytes);
                }

                // Get image dimensions
                const imageDims = pdfImage.scale(1);

                // Create page with A4 size (or match image aspect ratio)
                const pageWidth = 595;  // A4 width in points
                const pageHeight = 842; // A4 height in points
                const pdfPage = pdfDoc.addPage([pageWidth, pageHeight]);

                // Scale image to fit page while maintaining aspect ratio
                const scale = Math.min(pageWidth / imageDims.width, pageHeight / imageDims.height);
                const scaledWidth = imageDims.width * scale;
                const scaledHeight = imageDims.height * scale;

                // Center image on page
                const x = (pageWidth - scaledWidth) / 2;
                const y = (pageHeight - scaledHeight) / 2;

                pdfPage.drawImage(pdfImage, {
                    x: x,
                    y: y,
                    width: scaledWidth,
                    height: scaledHeight
                });
            }

            // Generate PDF bytes
            const pdfBytes = await pdfDoc.save();
            const pdfBlob = new Blob([pdfBytes], { type: 'application/pdf' });

            console.log(`XEROX: PDF created successfully, size: ${(pdfBlob.size / 1024).toFixed(2)} KB`);

            return pdfBlob;

        } catch (error) {
            console.error('XEROX: PDF conversion error:', error);
            throw error;
        }
    }

    // Get XEROX captured images as File objects
    function buildXeroxMetadata() {
        return scannedPages.map((page, index) => ({
            name: page.filename || `scan_${index + 1}.jpg`,
            is_cropped: !!page.isCropped,
            crop_info: page.cropInfo || null,
            page_index: index
        }));
    }

    function getXeroxDocumentFiles() {
        if (!scannedPages || scannedPages.length === 0) {
            return { files: [], metadata: [] };
        }

        // Validate image sizes
        const files = [];
        const metadata = [];
        for (let i = 0; i < scannedPages.length; i++) {
            const page = scannedPages[i];
            const sizeMB = page.blob.size / 1024 / 1024;

            if (sizeMB > MAX_IMAGE_SIZE_MB) {
                throw new Error(`Image ${i + 1} exceeds maximum size of ${MAX_IMAGE_SIZE_MB}MB`);
            }

            // Convert blob to File object
            const fileName = page.filename || `scan_${i + 1}.jpg`;
            const fileType = page.blob.type || 'image/jpeg';
            const file = new File([page.blob], fileName, { type: fileType });
            files.push(file);
            metadata.push({
                name: fileName,
                is_cropped: !!page.isCropped,
                crop_info: page.cropInfo || null,
                page_index: i
            });
        }

        return { files, metadata };
    }

    // Finish scanning and show XEROX settings panel
    async function finishScanUpload() {
        if (scannedPages.length === 0) {
            alert('Please scan at least one page before finishing');
            return;
        }

        try {
            // Disable finish button
            if (finishScanBtn) {
                finishScanBtn.disabled = true;
                finishScanBtn.textContent = 'Processing...';
            }

            console.info(`XEROX: Finishing scan with ${scannedPages.length} pages`);

            // Hide scanner UI, show Review Screen instead of settings directly
            if (xeroxScannerSection) xeroxScannerSection.style.display = 'none';
            if (scannedReviewSection) scannedReviewSection.style.display = 'block';
            if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'none';
            if (uploadSection) uploadSection.style.display = 'none';
            if (landingSection) landingSection.style.display = 'none';

            stopCamera(); // Stop camera after finishing scanning session

            // Render the review list
            renderScannedReviewList();

            console.log('XEROX: Scan completed, showing review screen');


            // Update document info
            if (xeroxDocumentName) {
                xeroxDocumentName.textContent = `scanned_document_${Date.now()}.pdf`;
            }

            // Calculate current total size for document info
            let totalSize = 0;
            scannedPages.forEach(p => {
                if (p.blob) totalSize += p.blob.size / 1024 / 1024;
            });

            if (xeroxDocumentSize) {
                xeroxDocumentSize.textContent = `${totalSize.toFixed(2)} MB`;
            }
            if (xeroxDocumentPages) {
                xeroxDocumentPages.textContent = scannedPages.length.toString();
            }

            // Enable preview and upload buttons
            if (xeroxPreviewBtn) xeroxPreviewBtn.disabled = false;
            if (xeroxUploadBtn) xeroxUploadBtn.disabled = false;

            // Scroll to settings section
            if (xeroxSettingsSection) {
                scrollToElement(xeroxSettingsSection);
            }

            // Trigger initial auto-preview after a short delay to ensure UI is ready
            setTimeout(() => {
                scheduleXeroxPreviewUpdate();
            }, 300);

            console.log('XEROX: Scan completed, showing settings panel');

        } catch (error) {
            console.error('XEROX: Finish scan error:', error);

            // Show alert ONLY if scanned pages array is empty OR scan count is zero
            if (!scannedPages || scannedPages.length === 0) {
                alert('Failed to process scanned pages: ' + error.message);
            }

            // Re-enable finish button
            if (finishScanBtn) {
                finishScanBtn.disabled = false;
                finishScanBtn.textContent = '✓ Finish Scanning';
            }
        }
    }

    // Render the Scanned Pages Review Screen List
    function renderScannedReviewList() {
        if (!scannedReviewList || !scannedReviewCount) return;

        scannedReviewCount.textContent = `${scannedPages.length} Pages`;
        scannedReviewList.innerHTML = '';

        if (scannedPages.length === 0) {
            scannedReviewList.innerHTML = '<div style="text-align:center; padding: 40px; color: #64748b;">No pages scanned yet.</div>';
            return;
        }

        scannedPages.forEach((page, index) => {
            const sizeKB = Math.round(page.blob.size / 1024);
            const card = document.createElement('div');
            card.className = 'scanned-item-card';

            card.innerHTML = `
                <div class="scanned-item-thumb">
                    <img src="${page.thumbnail}" alt="Page ${index + 1}">
                </div>
                <div class="scanned-item-info">
                    <div class="scanned-item-serial">${index + 1}</div>
                    <div class="scanned-item-time">${formatTimeAgo(page.capturedAt)}</div>
                    <div class="scanned-item-size">${sizeKB} kB</div>
                </div>
                <div class="scanned-item-actions">
                    <button class="scanned-item-menu" title="Delete Page" data-id="${page.id}">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 6h18"></path>
                            <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path>
                            <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            `;

            // Make the entire card clickable for Retake/Crop flow
            card.addEventListener('click', function () {
                const blobToCrop = page.blob;
                const originalThumb = page.originalThumbnail || page.thumbnail;

                // Ensure original is preserved before cropping (consistent with thumbnail logic)
                if (!page.originalBlob) {
                    page.originalBlob = page.blob;
                }
                if (!page.originalThumbnail) {
                    page.originalThumbnail = page.thumbnail;
                }

                openCropperModal(blobToCrop, {
                    pageId: page.id,
                    originalThumbnail: originalThumb,
                    filename: page.filename || `scan_${index + 1}.jpg`
                });
            });

            // Add delete functionality
            const deleteBtn = card.querySelector('.scanned-item-menu');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', function (e) {
                    e.stopPropagation(); // Prevent triggering card click
                    if (confirm('Delete this page?')) {
                        deleteScannedPageFromReview(page.id);
                    }
                });
            }

            scannedReviewList.appendChild(card);
        });
    }

    function deleteScannedPageFromReview(pageId) {
        scannedPages = scannedPages.filter(p => p.id !== pageId);
        // Refresh both views
        updateThumbnails();
        renderScannedReviewList();

        // Return to scanner if last page deleted
        if (scannedPages.length === 0) {
            if (scannedReviewSection) scannedReviewSection.style.display = 'none';
            if (xeroxScannerSection) xeroxScannerSection.style.display = 'block';
            resetScannerUIState(); // Reset UI state when forced back to scanner
            enableCamera();
        }

        // Trigger preview update (debounced)
        setTimeout(() => scheduleXeroxPreviewUpdate(), 300);
    }

    // New Proceed Logic (from Review Screen to Settings)
    async function proceedToSettings() {
        try {
            if (scannedPages.length === 0) return;

            // Show loading state
            if (reviewProceedBtn) {
                reviewProceedBtn.disabled = true;
            }

            // Calculate size for document info
            let totalSize = 0;
            scannedPages.forEach(p => totalSize += p.blob.size / 1024 / 1024);

            // Hide review section, show settings
            if (scannedReviewSection) scannedReviewSection.style.display = 'none';
            if (xeroxSettingsSection) xeroxSettingsSection.style.display = 'block';

            stopCamera(); // Stop camera when proceeding to settings

            // Update document info
            if (xeroxDocumentName) {
                xeroxDocumentName.textContent = `scanned_document_${Date.now()}.pdf`;
            }
            if (xeroxDocumentSize) {
                xeroxDocumentSize.textContent = `${totalSize.toFixed(2)} MB`;
            }
            if (xeroxDocumentPages) {
                xeroxDocumentPages.textContent = scannedPages.length.toString();
            }

            // Enable preview and upload buttons
            if (xeroxPreviewBtn) xeroxPreviewBtn.disabled = false;
            if (xeroxUploadBtn) xeroxUploadBtn.disabled = false;

            // Scroll to settings section
            if (xeroxSettingsSection) {
                scrollToElement(xeroxSettingsSection);
            }

            // Trigger initial auto-preview
            setTimeout(() => {
                scheduleXeroxPreviewUpdate();
            }, 300);

            // Reset finishScanBtn state just in case
            if (finishScanBtn) {
                finishScanBtn.disabled = false;
                finishScanBtn.textContent = '✓';
            }

        } catch (error) {
            console.error('XEROX: Proceed error:', error);
        } finally {
            if (reviewProceedBtn) {
                reviewProceedBtn.disabled = false;
            }
        }
    }

    // Setup scanner event listeners
    function setupScannerListeners() {
        if (enableCameraBtn) {
            enableCameraBtn.addEventListener('click', enableCamera);
        }

        if (captureBtn) {
            captureBtn.addEventListener('click', captureImage);
        }

        if (retakeBtn) {
            retakeBtn.addEventListener('click', function () {
                currentCaptureBlob = null;
                if (retakeBtn) retakeBtn.style.display = 'none';
            });
        }

        if (addMorePagesBtn) {
            addMorePagesBtn.addEventListener('click', function () {
                // Re-enable camera if it was stopped
                if (!cameraStream) {
                    enableCamera();
                }
            });
        }

        if (finishScanBtn) {
            finishScanBtn.addEventListener('click', finishScanUpload);
        }

        // New Review Screen Listeners
        if (reviewAddMoreBtn) {
            reviewAddMoreBtn.addEventListener('click', function () {
                if (scannedReviewSection) scannedReviewSection.style.display = 'none';
                if (xeroxScannerSection) xeroxScannerSection.style.display = 'block';
                resetScannerUIState(); // Reset UI state when scanning more images
                if (!cameraStream) {
                    enableCamera();
                } else if (cameraVideo) {
                    cameraVideo.play().catch(enableCamera);
                }
            });
        }

        if (reviewProceedBtn) {
            reviewProceedBtn.addEventListener('click', proceedToSettings);
        }
    }

    // Initialize landing page and scanner
    initLandingPage();
    setupCropperControls();
    setupScannerListeners();

    // ============================================
    // END XEROX SCANNER FUNCTIONALITY
    // ============================================

    // PAGE RANGE FIX: Enhanced validation with better error messages
    function isValidPageRange(s) {
        if (!s || !s.trim()) return true; // Empty is valid (means "all pages")

        // Allow digits, spaces, commas, and dashes
        if (!/^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$/.test(s)) {
            return false;
        }

        // Additional logical check: for any range a-b ensure a<=b
        const parts = s.split(',');
        for (let part of parts) {
            part = part.trim();
            if (!part) continue;
            if (part.includes('-')) {
                const [aStr, bStr] = part.split('-').map(x => x.trim());
                const a = parseInt(aStr, 10);
                const b = parseInt(bStr, 10);
                if (isNaN(a) || isNaN(b) || a <= 0 || b <= 0 || a > b) {
                    return false;
                }
            } else {
                const a = parseInt(part, 10);
                if (isNaN(a) || a <= 0) {
                    return false;
                }
            }
        }
        return true;
    }

    // PAGE RANGE FIX: Show validation error message near the input field
    function showPageRangeError(message) {
        // Remove any existing error message
        const existingError = document.getElementById('pageRangeError');
        if (existingError) {
            existingError.remove();
        }

        if (message) {
            // Create error message element
            const errorDiv = document.createElement('div');
            errorDiv.id = 'pageRangeError';
            errorDiv.className = 'page-range-error';
            errorDiv.textContent = message;
            errorDiv.style.color = '#e53e3e';
            errorDiv.style.fontSize = '12px';
            errorDiv.style.marginTop = '4px';

            // Insert after page range input
            if (pageRangeInput && pageRangeInput.parentNode) {
                pageRangeInput.parentNode.appendChild(errorDiv);
            }
        }
    }
});
