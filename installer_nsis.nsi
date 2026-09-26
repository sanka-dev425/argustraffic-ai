; =====================================================================
; ArgusTraffic AI - NSIS Modern UI 2 Installer Script
; Generates standard Windows installer with Directory Selection & Finish Page
; =====================================================================

!include "MUI2.nsh"
!include "FileFunc.nsh"

; General Settings
Name "ArgusTraffic AI"
OutFile "Output\ArgusTraffic_Setup.exe"
InstallDir "$PROGRAMFILES64\ArgusTraffic AI"
InstallDirRegKey HKLM "Software\ArgusTraffic AI" "Install_Dir"
RequestExecutionLevel admin

; UI Configuration
!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

; Pages (Matches user's screenshots)
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; Finish Page with "Run Application" Checkbox
!define MUI_FINISHPAGE_RUN "$INSTDIR\ArgusTraffic.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Run ArgusTraffic AI"
!insertmacro MUI_PAGE_FINISH

; Uninstaller Pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Language
!insertmacro MUI_LANGUAGE "English"

Section "ArgusTraffic Core" SecCore
    SetOutPath "$INSTDIR"
    File /r "dist\ArgusTraffic\*.*"

    ; Store installation path
    WriteRegStr HKLM "Software\ArgusTraffic AI" "Install_Dir" "$INSTDIR"

    ; Create uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Add to Add/Remove Programs
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgusTraffic AI" "DisplayName" "ArgusTraffic AI"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgusTraffic AI" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgusTraffic AI" "DisplayIcon" '"$INSTDIR\ArgusTraffic.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgusTraffic AI" "Publisher" "ArgusTraffic Systems"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgusTraffic AI" "DisplayVersion" "2.0.0"

    ; Shortcuts
    CreateDirectory "$SMPROGRAMS\ArgusTraffic AI"
    CreateShortcut "$SMPROGRAMS\ArgusTraffic AI\ArgusTraffic AI.lnk" "$INSTDIR\ArgusTraffic.exe"
    CreateShortcut "$SMPROGRAMS\ArgusTraffic AI\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    CreateShortcut "$DESKTOP\ArgusTraffic AI.lnk" "$INSTDIR\ArgusTraffic.exe"
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\ArgusTraffic AI.lnk"
    RMDir /r "$SMPROGRAMS\ArgusTraffic AI"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgusTraffic AI"
    DeleteRegKey HKLM "Software\ArgusTraffic AI"
SectionEnd
