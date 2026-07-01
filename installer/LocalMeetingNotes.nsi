!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
!endif

!define APP_NAME "Local Meeting Notes"
!define COMPANY_NAME "tokotoko090"
!define EXE_NAME "LocalMeetingNotes.exe"

Name "${APP_NAME}"
OutFile "..\release\LocalMeetingNotesSetup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\LocalMeetingNotes"
RequestExecutionLevel user
Unicode true

Page directory
Page instfiles

UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  ExecWait '"$SYSDIR\taskkill.exe" /IM "${EXE_NAME}" /F'
  SetOutPath "$INSTDIR"
  File "..\dist-app\${EXE_NAME}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "UninstallString" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  Delete "$INSTDIR\${EXE_NAME}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes"
SectionEnd
