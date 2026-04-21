# EzPrint Agent - Testing Checklist

## Pre-Build Testing

### Environment Validation
- [ ] Python 3.8+ installed and accessible
- [ ] All dependencies from requirements.txt installed
- [ ] PyQt5 imports successfully (`python -c "import PyQt5"`)
- [ ] PyInstaller installed (`pyinstaller --version`)
- [ ] NSIS installed (optional, for installer creation)

### Configuration Validation
- [ ] `.env` file exists with required variables
- [ ] S3 credentials valid (if using S3)
- [ ] Database connection works
- [ ] SaaS API endpoint accessible (if configured)

## Build Process Testing

### Clean Build
```bash
python build/scripts/clean.py
```
- [ ] Removes build/output/dist/ directory
- [ ] Removes build/output/build/ directory
- [ ] Removes build/output/release/ directory
- [ ] Removes Python cache files
- [ ] No errors during cleanup

### Build Executable
```bash
python build/scripts/build_windows.py
```
- [ ] Dependency check passes
- [ ] Environment validation passes
- [ ] PyInstaller runs without errors
- [ ] EXE created in build/output/dist/
- [ ] File size reasonable (80-150 MB)
- [ ] Checksum calculated successfully
- [ ] Release package created (if NSIS available)
- [ ] ZIP archive created

### Build Output Verification
- [ ] `build/output/dist/EzPrintAgent.exe` exists
- [ ] EXE file has icon embedded
- [ ] Version information embedded in EXE
- [ ] File properties show correct company name, version
- [ ] `build/output/release/` contains release artifacts
- [ ] `checksums.txt` file present with SHA256 hashes

## Functional Testing (Development Machine)

### Basic Launch
- [ ] Double-click EXE launches application
- [ ] No console window appears (windowed mode)
- [ ] Application icon shows in taskbar
- [ ] Main window appears within 5 seconds
- [ ] No error messages on startup

### Core Functionality
- [ ] Database initializes correctly
- [ ] Can see shop configuration
- [ ] System tray icon appears
- [ ] Menu items functional

### Printer Detection
- [ ] Can detect local printers
- [ ] Printer list populates correctly
- [ ] Can select default printer
- [ ] Printer capabilities detected

### File Storage Testing

Customer uploads now flow through `ezprint-backend` → MinIO (S3-compatible).
The agent only consumes presigned download URLs; it never uploads.

#### MinIO / S3 downloads
- [ ] `GET /api/v1/jobs/{id}/file-url` returns a working presigned URL
- [ ] Agent downloads the asset to a temp file before printing
- [ ] 410 response (asset cleaned up by the worker) shows a friendly toast
- [ ] Local fallback path still works when the asset is still on disk

### Print Job Testing
- [ ] Can receive print job from SaaS
- [ ] File downloads correctly
- [ ] Print dialog appears (if enabled)
- [ ] Can send to printer
- [ ] Job status updates correctly
- [ ] Can view print job history

### Auto-Update Testing
- [ ] Manual update check works (Help > Check for Updates)
- [ ] "No updates available" message if on latest version
- [ ] Update notification appears if new version available
- [ ] Can view release notes
- [ ] Can download and install update (test with mock server)
- [ ] Checksum verification works
- [ ] Invalid checksum rejected
- [ ] Update installation launches correctly

### Real-Time Communication
- [ ] Native WebSocket (`/ws/agent`) connects to the FastAPI backend
- [ ] Can receive real-time `new_job` and `job_status` frames
- [ ] Outbound `print_started` / `print_completed` / `print_failed` acknowledged
- [ ] Reconnects with backoff after network interruption
- [ ] Re-mints agent token on `1008` close
- [ ] Falls back to REST polling when the socket can't connect

### Offline Functionality
- [ ] Application starts without internet
- [ ] Can access local printer list
- [ ] Queued jobs stored locally
- [ ] Jobs sync when connection restored

## Clean Installation Testing (Windows VM)

### Test Environment Setup
- [ ] Clean Windows 10 or 11 VM
- [ ] No Python installed
- [ ] No previous EzPrint installation
- [ ] No development tools

### Installation Testing
- [ ] Copy EXE to VM
- [ ] Double-click to run
- [ ] Windows SmartScreen doesn't block (if code signed)
- [ ] Application launches successfully
- [ ] All features work as expected
- [ ] Can connect to SaaS server
- [ ] Can detect and print to printers

### First-Run Experience
- [ ] Setup wizard appears (if implemented)
- [ ] Can configure shop credentials
- [ ] Can test printer connection
- [ ] Configuration saves correctly

## Upgrade Testing

### Prepare Test Environment
- [ ] Install previous version of agent
- [ ] Create test print jobs
- [ ] Configure settings

### Upgrade Process
- [ ] Launch new installer/EXE
- [ ] Detects existing installation
- [ ] Preserves configuration
- [ ] Preserves database
- [ ] Updates successfully
- [ ] New version shows correct version number
- [ ] Previous settings retained

### Post-Upgrade Validation
- [ ] All printers still detected
- [ ] Previous jobs still visible
- [ ] Configuration unchanged
- [ ] New features accessible

## Uninstall Testing

### Uninstall Process (if NSIS installer used)
- [ ] Uninstaller accessible from Add/Remove Programs
- [ ] Uninstaller launches correctly
- [ ] Removes application files
- [ ] Removes start menu shortcuts
- [ ] Removes desktop shortcut
- [ ] Removes startup entry (if configured)
- [ ] Asks about keeping configuration/data

### Cleanup Verification
- [ ] Program Files directory removed (or only data remains)
- [ ] Start menu shortcuts removed
- [ ] Desktop shortcut removed
- [ ] Startup registry entry removed
- [ ] System tray icon disappears
- [ ] User data preserved/removed based on choice

## Security Testing

### Code Signing (if implemented)
- [ ] EXE has valid digital signature
- [ ] Certificate details correct
- [ ] Timestamp present
- [ ] Windows recognizes publisher

### Antivirus Testing
- [ ] Windows Defender doesn't flag as malware
- [ ] VirusTotal scan clean (0 detections acceptable)
- [ ] Common antivirus software doesn't block

### Network Security
- [ ] HTTPS used for all API calls
- [ ] Certificates validated
- [ ] No insecure HTTP connections
- [ ] Credentials not logged in plain text

## Performance Testing

### Startup Performance
- [ ] Cold start (first run): < 10 seconds
- [ ] Warm start (subsequent runs): < 5 seconds
- [ ] Memory usage at idle: < 200 MB
- [ ] CPU usage at idle: < 5%

### File Processing Performance
- [ ] 1 MB file processes in < 5 seconds
- [ ] 10 MB file processes in < 30 seconds
- [ ] 50 MB file processes in < 2 minutes
- [ ] No memory leaks during batch processing

### Print Job Performance
- [ ] Can handle 10 concurrent jobs
- [ ] Queue processing reliable
- [ ] No crashes under load

## Compatibility Testing

### Windows Versions
- [ ] Windows 10 (version 1809+)
- [ ] Windows 11
- [ ] Windows Server 2019/2022 (if applicable)

### Printer Compatibility
- [ ] USB printers detected
- [ ] Network printers detected
- [ ] Default Windows printer works
- [ ] PDF printer works
- [ ] Thermal receipt printers work (if applicable)

### File Format Compatibility
- [ ] PDF files print correctly
- [ ] Image files (PNG, JPG) print correctly
- [ ] Document files print correctly (if supported)
- [ ] Various paper sizes supported

## Error Handling Testing

### Network Failures
- [ ] Handles SaaS server unreachable
- [ ] Handles temporary network loss
- [ ] Handles slow connections
- [ ] Shows appropriate error messages
- [ ] Implements retry logic

### Storage Failures
- [ ] Handles MinIO/S3 unavailable (presigned URL fetch fails gracefully)
- [ ] Handles disk full condition
- [ ] Falls back to local file_path when a remote URL can't be fetched

### Printer Failures
- [ ] Handles printer offline
- [ ] Handles printer error states
- [ ] Handles paper jam/out of paper
- [ ] Shows clear error messages

### Database Failures
- [ ] Handles database corruption
- [ ] Can recreate database if needed
- [ ] Preserves data integrity

## Logging and Diagnostics

### Log Files
- [ ] Logs created in correct location
- [ ] Log rotation works
- [ ] Contains useful diagnostic information
- [ ] Doesn't log sensitive data
- [ ] Log level configurable

### Error Reporting
- [ ] Errors logged with stack traces
- [ ] Can export logs for support
- [ ] Includes system information

## Regression Testing Checklist

Run before each release:

1. [ ] Full clean build succeeds
2. [ ] Fresh installation on Windows 10/11
3. [ ] Upgrade from previous version
4. [ ] Basic print job workflow
5. [ ] Presigned MinIO download for a finalized job
6. [ ] Auto-update mechanism
7. [ ] Offline mode
8. [ ] Uninstall cleanup

## Known Issues and Workarounds

Document any known issues discovered during testing:

| Issue | Severity | Workaround | Status |
|-------|----------|------------|--------|
| Example: Slow first startup | Low | Expected behavior for onefile mode | Won't Fix |
| | | | |

## Test Environment Details

### Recommended VM Configuration
- OS: Windows 10 Pro (21H2 or later)
- RAM: 4 GB minimum
- Disk: 20 GB
- Software: No Python, no dev tools
- Printers: At least one printer installed

### Test Data Requirements
- Sample PDF files (various sizes)
- Sample image files (PNG, JPG)
- Test print jobs
- Mock SaaS server (optional)

## Automated Testing (Future Enhancement)

Ideas for automation:
- [ ] Automated build testing in CI/CD
- [ ] Unit tests for core modules
- [ ] Integration tests for `ezprint-backend` + MinIO
- [ ] UI automation with PyQt5 test framework
- [ ] Automated installer testing

## Sign-Off

Before release, the following must be verified:

- [ ] All critical tests passed
- [ ] All high severity issues resolved
- [ ] Performance benchmarks met
- [ ] Security review completed
- [ ] Documentation updated
- [ ] Release notes written
- [ ] Code signed (production releases)
- [ ] Uploaded to distribution server
- [ ] Version API updated

**Tester Name**: _________________
**Date**: _________________
**Version Tested**: _________________
**Test Result**: Pass / Fail
**Notes**:

---

## Support and Reporting

If you encounter issues during testing:
1. Check TROUBLESHOOTING section in build/README.md
2. Review log files in %APPDATA%/EzPrint/logs/
3. Export logs and system information
4. Report issue with reproduction steps
5. Contact: dev@ezprint.com
