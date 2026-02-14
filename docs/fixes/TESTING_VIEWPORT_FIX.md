# Testing Guide: Camera Viewport Fix

## Quick Verification Steps

### 1. Visual Test (Primary)

**Steps**:
1. Open the application on mobile device
2. Navigate to **XEROX** section
3. Enable camera access
4. Point camera at a document/photo
5. **Note the exact framing** you see in the camera preview
6. Click the **Capture** button (white circle)
7. **Verify** the Crop Page shows the **EXACT SAME framing**

**Expected Result**: ✅
- Camera preview framing = Crop page framing
- No extra background visible on crop page
- No zoom-out or expansion

**Failure Indicator**: ❌
- Crop page shows MORE area than camera preview
- Extra curtains, walls, or background visible
- Image appears "zoomed out" compared to preview

---

### 2. Console Log Verification

**Steps**:
1. Open browser DevTools (F12)
2. Go to **Console** tab
3. Capture an image
4. Look for log entry: `XEROX: Viewport-aware capture`

**Expected Output**:
```javascript
XEROX: Viewport-aware capture {
    videoResolution: "1280x720",
    containerSize: "375x530",
    capturedRegion: "384,0 511x720",
    canvasSize: "511x720"
}
```

**Verification**:
- `capturedRegion` should be **smaller** than `videoResolution`
- `canvasSize` should match the **cropped dimensions**
- No errors in console

---

### 3. Multi-Device Test Matrix

| Device Type | Orientation | Expected Crop Direction |
|-------------|-------------|------------------------|
| Mobile | Portrait | Crop left/right sides |
| Mobile | Landscape | Crop top/bottom |
| Desktop | Any | Depends on webcam aspect |
| Tablet | Portrait | Crop left/right sides |
| Tablet | Landscape | Crop top/bottom |

**Test Each**:
- ✅ Camera preview shows document centered
- ✅ Capture matches preview exactly
- ✅ No extra areas on crop page

---

### 4. Edge Case Tests

#### Test A: Ultra-Wide Camera
- **Device**: Modern phone with ultra-wide rear camera
- **Expected**: Significant left/right cropping
- **Verify**: No extra side areas on crop page

#### Test B: Front Camera
- **Device**: Any device
- **Camera**: Switch to front camera
- **Expected**: Same viewport matching behavior
- **Verify**: Preview = Crop page

#### Test C: Low-Light Conditions
- **Environment**: Dark room
- **Expected**: Fix works regardless of lighting
- **Verify**: Framing consistency maintained

#### Test D: Rotated Device
- **Action**: Rotate device while on camera preview
- **Expected**: Viewport recalculates correctly
- **Verify**: Next capture still matches preview

---

## Debugging Checklist

If the fix doesn't work as expected:

### Check 1: JavaScript Loaded
```javascript
// In browser console:
console.log(typeof captureImage);
// Expected: "function"
```

### Check 2: Video Element
```javascript
// In browser console:
const video = document.getElementById('cameraVideo');
console.log(video.videoWidth, video.videoHeight);
// Expected: Non-zero values (e.g., 1280, 720)
```

### Check 3: Container Dimensions
```javascript
// In browser console:
const container = document.querySelector('.camera-preview-container');
console.log(container.clientWidth, container.clientHeight);
// Expected: Non-zero values matching viewport
```

### Check 4: CSS Applied
```javascript
// In browser console:
const video = document.getElementById('cameraVideo');
const style = window.getComputedStyle(video);
console.log(style.objectFit);
// Expected: "cover"
```

---

## Regression Tests

Ensure these existing features still work:

- ✅ Camera permission request
- ✅ Camera stream starts correctly
- ✅ Capture button responsive
- ✅ Cropper modal opens
- ✅ Rotation works in cropper
- ✅ Crop-free/A4/Square aspect toggles work
- ✅ Continue button saves crop
- ✅ Retake button returns to camera
- ✅ Multiple page scanning
- ✅ Thumbnail preview updates
- ✅ Settings page shows correct page count

---

## Performance Verification

### Memory Usage
- **Before Fix**: Captures full 1280×720 = ~920K pixels
- **After Fix**: Captures cropped 511×720 = ~368K pixels
- **Improvement**: ~60% reduction in canvas size

### Capture Speed
- **Expected**: No noticeable difference
- **Verify**: Capture → Crop modal transition is smooth

---

## Success Criteria

✅ **Visual Parity**: Camera preview framing = Crop page framing  
✅ **No Extra Areas**: Crop page shows only what was visible in preview  
✅ **Console Logs**: Viewport-aware capture logs appear  
✅ **Cross-Device**: Works on mobile, tablet, desktop  
✅ **Cross-Browser**: Works on Chrome, Safari, Firefox, Edge  
✅ **No Regressions**: All existing features functional  
✅ **Performance**: No slowdown, reduced memory usage  

---

## Rollback Plan

If issues occur:

1. **Locate**: `web_interface/static/js/upload.js`
2. **Find**: `captureImage()` function (around line 2765)
3. **Replace** with original:
```javascript
function captureImage() {
    if (!cameraVideo || !cameraCanvas) return;
    try {
        const video = cameraVideo;
        const canvas = cameraCanvas;
        const ctx = canvas.getContext('2d');
        
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        
        canvas.toBlob(function (blob) {
            if (!blob) {
                alert('Failed to capture image');
                return;
            }
            currentCaptureBlob = blob;
            if (retakeBtn) retakeBtn.style.display = 'inline-block';
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
        }, 'image/jpeg', 0.85);
    } catch (error) {
        console.error('XEROX: Capture error:', error);
        alert('Failed to capture image: ' + error.message);
    }
}
```

4. **Restart** application
5. **Report** issue with details

---

## Contact

For issues or questions about this fix, refer to:
- **Technical Documentation**: `CAMERA_VIEWPORT_FIX.md`
- **Implementation**: `web_interface/static/js/upload.js` (line 2765)
- **Visual Diagram**: `viewport_fix_diagram.png`
