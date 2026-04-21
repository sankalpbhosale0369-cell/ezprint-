; EzPrint Agent - NSIS Installer Script
; Modern UI installer with professional features
; Requires NSIS 3.0+ with Modern UI 2

;--------------------------------
; Includes

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

;--------------------------------
; Configuration

; Application Info
!define APP_NAME "EzPrint Agent"
!define APP_VERSION "1.0.0"
!define APP_PUBLISHER "EzPrint"
!define APP_WEBSITE "https://ezprint.com"
!define APP_SUPPORT_EMAIL "support@ezprint.com"

; Executable Info
!define EXE_NAME "EzPrintAgent.exe"
!define UNINSTALLER_NAME "Uninstall.exe"

; Installation Directory
!define INSTALL_DIR "$PROGRAMFILES64\EzPrint\Agent"

; Registry Keys
!define REG_UNINSTALL "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define REG_APP "Software\EzPrint\Agent"

;--------------------------------
; General Configuration

; Installer name and output file
Name "${APP_NAME}"
OutFile "..\..\output\release\EzPrintAgentSetup_v${APP_VERSION}.exe"

; Default installation directory
InstallDir "${INSTALL_DIR}"

; Get installation folder from registry if available
InstallDirRegKey HKLM "${REG_APP}" "InstallPath"

; Request admin privileges
RequestExecutionLevel admin

; Compression
SetCompressor /SOLID lzma
SetCompressorDictSize 64

; Branding
BrandingText "${APP_NAME} v${APP_VERSION}"

;--------------------------------
; Interface Settings

!define MUI_ABORTWARNING
!define MUI_ICON "..\..\assets\icons\ezprint.ico"
!define MUI_UNICON "..\..\assets\icons\ezprint.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "..\..\assets\installer_banner.bmp"

; Header
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "${NSISDIR}\Contrib\Graphics\Header\nsis3-branding.bmp"

;--------------------------------
; Pages

; Installer Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\assets\license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE_NAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APP_NAME}"
!define MUI_FINISHPAGE_LINK "Visit ${APP_WEBSITE}"
!define MUI_FINISHPAGE_LINK_LOCATION "${APP_WEBSITE}"
!insertmacro MUI_PAGE_FINISH

; Uninstaller Pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

;--------------------------------
; Languages

!insertmacro MUI_LANGUAGE "English"

;--------------------------------
; Version Information

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "${APP_NAME} Installer"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright (c) 2024 ${APP_PUBLISHER}"

;--------------------------------
; Installer Functions

Function .onInit
  ; Check if already installed
  ReadRegStr $0 HKLM "${REG_UNINSTALL}" "UninstallString"
  ${If} $0 != ""
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "${APP_NAME} is already installed.$\n$\nDo you want to uninstall the previous version before continuing?" \
      IDYES uninst
    Abort
    uninst:
      ; Run uninstaller
      ClearErrors
      ExecWait '$0 /S _?=$INSTDIR'
      Delete "$0"
  ${EndIf}

  ; Check Windows version (Windows 10 1809+ required)
  ${If} ${AtLeastWin10}
    ; OK
  ${Else}
    MessageBox MB_OK|MB_ICONSTOP \
      "${APP_NAME} requires Windows 10 or later."
    Abort
  ${EndIf}
FunctionEnd

;--------------------------------
; Installation Section

Section "Main Application" SecMain
  SectionIn RO ; Read-only, cannot be deselected

  SetOutPath "$INSTDIR"

  ; Main executable
  File "..\output\dist\${EXE_NAME}"

  ; Write installation path to registry
  WriteRegStr HKLM "${REG_APP}" "InstallPath" "$INSTDIR"
  WriteRegStr HKLM "${REG_APP}" "Version" "${APP_VERSION}"

  ; Create uninstaller
  WriteUninstaller "$INSTDIR\${UNINSTALLER_NAME}"

  ; Write uninstall information to registry
  WriteRegStr HKLM "${REG_UNINSTALL}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${REG_UNINSTALL}" "UninstallString" '"$INSTDIR\${UNINSTALLER_NAME}"'
  WriteRegStr HKLM "${REG_UNINSTALL}" "QuietUninstallString" '"$INSTDIR\${UNINSTALLER_NAME}" /S'
  WriteRegStr HKLM "${REG_UNINSTALL}" "DisplayIcon" "$INSTDIR\${EXE_NAME}"
  WriteRegStr HKLM "${REG_UNINSTALL}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${REG_UNINSTALL}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "${REG_UNINSTALL}" "URLInfoAbout" "${APP_WEBSITE}"
  WriteRegStr HKLM "${REG_UNINSTALL}" "HelpLink" "${APP_WEBSITE}/support"
  WriteRegStr HKLM "${REG_UNINSTALL}" "URLUpdateInfo" "${APP_WEBSITE}/downloads"
  WriteRegDWORD HKLM "${REG_UNINSTALL}" "NoModify" 1
  WriteRegDWORD HKLM "${REG_UNINSTALL}" "NoRepair" 1

  ; Calculate installed size
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${REG_UNINSTALL}" "EstimatedSize" "$0"

SectionEnd

;--------------------------------
; Shortcuts Section

Section "Start Menu Shortcuts" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\${UNINSTALLER_NAME}"
SectionEnd

Section "Desktop Shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
SectionEnd

Section /o "Run at Windows Startup" SecStartup
  CreateShortcut "$SMSTARTUP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
SectionEnd

;--------------------------------
; Section Descriptions

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Main application files (required)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "Create shortcuts in Start Menu"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Create shortcut on Desktop"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartup} "Launch ${APP_NAME} automatically when Windows starts"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;--------------------------------
; Uninstaller Functions

Function un.onInit
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Are you sure you want to uninstall ${APP_NAME}?" \
    IDYES +2
  Abort
FunctionEnd

;--------------------------------
; Uninstaller Section

Section "Uninstall"

  ; Stop the application if running
  nsExec::ExecToStack 'taskkill /F /IM "${EXE_NAME}"'
  Pop $0
  Sleep 1000

  ; Remove files
  Delete "$INSTDIR\${EXE_NAME}"
  Delete "$INSTDIR\${UNINSTALLER_NAME}"

  ; Remove shortcuts
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  Delete "$SMSTARTUP\${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  ; Remove installation directory if empty
  RMDir "$INSTDIR"

  ; Ask about user data
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Do you want to remove all user data and settings?$\n$\nThis includes database, logs, and configuration files." \
    IDYES remove_data IDNO keep_data

  remove_data:
    ; Remove user data
    RMDir /r "$APPDATA\EzPrint"
    RMDir /r "$LOCALAPPDATA\EzPrint"
    Goto done_data

  keep_data:
    DetailPrint "User data preserved in $APPDATA\EzPrint"

  done_data:

  ; Remove registry keys
  DeleteRegKey HKLM "${REG_UNINSTALL}"
  DeleteRegKey HKLM "${REG_APP}"

  ; Success message
  MessageBox MB_OK|MB_ICONINFORMATION \
    "${APP_NAME} has been successfully uninstalled."

SectionEnd

;--------------------------------
; Silent Install Support

Function .onInstSuccess
  ${If} ${Silent}
    ; Silent install completed
    Exec "$INSTDIR\${EXE_NAME}"
  ${EndIf}
FunctionEnd
