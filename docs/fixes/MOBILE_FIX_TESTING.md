# Mobile Fix Testing Checklist

## Critical Mobile Test

### Device: Android/iOS Phone

**Steps**:
1. ✅ Open application on mobile device
2. ✅ Navigate to **XEROX** section
3. ✅ Enable camera (rear camera preferred)
4. ✅ Point at a document or photo
5. ✅ **OBSERVE**: Note the exact framing in camera preview
   - What's visible at the edges?
   - What background is showing?
6. ✅ Click **Capture** button (white circle)
7. ✅ **VERIFY**: Crop page shows EXACT same framing
   - No extra background
   - No zoom-out effect
   - Edges match preview exactly

**Expected Result**: ✅ **PASS**
- Camera preview framing = Crop page framing
- No extra curtains, walls, or background visible

**Failure Indicator**: ❌ **FAIL**
- Crop page shows MORE area than camera preview
- Extra background visible that wasn't in preview
- Image appears "zoomed out"

---

## Console Verification (Mobile)

### Open DevTools via USB Debugging

**Android Chrome**:
1. Connect phone via USB
2. Enable USB debugging
3. Open `chrome://inspect` on desktop
4. Inspect mobile browser

**Expected Console Output**:
```javascript
XEROX: Capture dimensions {
    nativeVideo: "1920x1080 (aspect: 1.78)",
    renderedVideo: "302x427 (aspect: 0.71)",  ← Should show A4-ish aspect
    device: "mobile"
}

XEROX: Viewport-aware capture result {
    videoResolution: "1920x1080",
    renderedSize: "302x427",  ← Actual rendered video element size
    capturedRegion: "x:578 y:0 w:764 h:1080",  ← Cropped region
    canvasSize: "764x1080",
    cropDirection: "sides"  ← Should be "sides" for typical 16:9 cameras
}
```

**Verification Points**:
- ✅ `renderedVideo` aspect should be ~0.7 (A4 ratio)
- ✅ `renderedVideo` width should be LESS than container width
- ✅ `cropDirection` should be "sides" (for 16:9 cameras on A4 preview)
- ✅ No JavaScript errors

---

## Desktop Regression Test

### Device: Desktop/Laptop

**Steps**:
1. ✅ Open application on desktop browser
2. ✅ Navigate to **XEROX** section
3. ✅ Enable camera (webcam)
4. ✅ Point at document
5. ✅ Capture
6. ✅ **VERIFY**: Still works correctly (no regression)

**Expected Console Output**:
```javascript
XEROX: Capture dimensions {
    nativeVideo: "1280x720 (aspect: 1.78)",
    renderedVideo: "800x600 (aspect: 1.33)",
    device: "desktop"
}

XEROX: Viewport-aware capture result {
    videoResolution: "1280x720",
    renderedSize: "800x600",
    capturedRegion: "x:160 y:0 w:960 h:720",
    canvasSize: "960x720",
    cropDirection: "sides"
}
```

**Success Criteria**:
- ✅ Desktop still works as before
- ✅ No visual changes
- ✅ No errors

---

## Edge Case Tests

### Test 1: Portrait Orientation (Mobile)
- **Action**: Rotate phone to portrait
- **Expected**: Viewport recalculates correctly
- **Verify**: Next capture matches new orientation

### Test 2: Landscape Orientation (Mobile)
- **Action**: Rotate phone to landscape
- **Expected**: Viewport recalculates correctly
- **Verify**: Capture matches landscape preview

### Test 3: Front Camera (Mobile)
- **Action**: Switch to front camera
- **Expected**: Same viewport matching behavior
- **Verify**: Preview = Crop page

### Test 4: Different Lighting
- **Action**: Test in bright and dark environments
- **Expected**: Fix works regardless of lighting
- **Verify**: Framing consistency maintained

### Test 5: Multiple Captures
- **Action**: Capture 3-5 pages in sequence
- **Expected**: Each capture matches its preview
- **Verify**: Consistent behavior across all captures

---

## Comparison Test: Before vs After

### Before Fix (Mobile)
```
Camera Preview: Shows portrait tightly framed
Crop Page: Shows portrait + extra background (curtains, walls)
Result: ❌ MISMATCH
```

### After Fix (Mobile)
```
Camera Preview: Shows portrait tightly framed
Crop Page: Shows portrait tightly framed (EXACT MATCH)
Result: ✅ PERFECT MATCH
```

---

## Quick Debug Commands

### Check Video Element Dimensions
```javascript
// In mobile browser console:
const video = document.getElementById('cameraVideo');
const rect = video.getBoundingClientRect();
console.log('Video element:', rect.width, 'x', rect.height);
console.log('Video native:', video.videoWidth, 'x', video.videoHeight);
console.log('Aspect ratio:', (rect.width / rect.height).toFixed(2));
```

**Expected Mobile Output**:
```
Video element: 302 x 427
Video native: 1920 x 1080
Aspect ratio: 0.71
```

### Check Container Dimensions
```javascript
const container = document.querySelector('.camera-preview-container');
console.log('Container:', container.clientWidth, 'x', container.clientHeight);
```

**Expected Mobile Output**:
```
Container: 375 x 427
```

**Key Insight**: Video element (302px) is SMALLER than container (375px) due to `aspect-ratio: 1/1.414` constraint!

---

## Success Metrics

### Mobile
- ✅ `renderedVideo` width < container width (due to aspect-ratio)
- ✅ `renderedVideo` aspect ~0.7 (A4 ratio)
- ✅ Visual match: preview = crop page
- ✅ No extra background on crop page

### Desktop
- ✅ `renderedVideo` ≈ container dimensions
- ✅ Still works correctly (no regression)
- ✅ Visual match: preview = crop page

### Both Platforms
- ✅ No JavaScript errors
- ✅ Cropper.js opens correctly
- ✅ Rotation works
- ✅ Crop-free/A4/Square toggles work
- ✅ Multiple page scanning works

---

## Rollback Trigger

If ANY of these occur on mobile:
- ❌ Capture fails completely
- ❌ Crop page shows black/blank image
- ❌ Console shows `getBoundingClientRect` errors
- ❌ Desktop stops working

Then:
1. Check console for specific error
2. Report issue with console logs
3. If critical, rollback to previous version

---

## Known Good Values (Reference)

### Mobile (iPhone 12)
```
nativeVideo: 1920x1080
renderedVideo: 302x427
capturedRegion: x:578 y:0 w:764 h:1080
cropDirection: sides
```

### Mobile (Samsung Galaxy)
```
nativeVideo: 1920x1080
renderedVideo: 308x435
capturedRegion: x:571 y:0 w:778 h:1080
cropDirection: sides
```

### Desktop (MacBook)
```
nativeVideo: 1280x720
renderedVideo: 800x600
capturedRegion: x:160 y:0 w:960 h:720
cropDirection: sides
```

---

## Final Verification

**Question**: Does the crop page show the EXACT same portion as the camera preview?

- ✅ **YES** → Fix successful
- ❌ **NO** → Check console logs, verify getBoundingClientRect values

**The fix is successful when**: Camera preview framing = Crop page framing on BOTH mobile and desktop.

---

**Testing Status**: ⏳ **PENDING USER VERIFICATION**  
**Expected Result**: ✅ **MOBILE + DESKTOP BOTH WORKING**
