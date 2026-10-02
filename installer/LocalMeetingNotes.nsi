!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
!endif

!define APP_NAME "Local Meeting Notes"
!define COMPANY_NAME "tokotoko090"
!define EXE_NAME "LocalMeetingNotes.exe"

Name "${APP_NAME}"
OutFile "..\release\LocalMeetingNotesSetup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\LocalMeetingNotes"
InstallDirRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "InstallLocation"
RequestExecutionLevel user
Unicode true

Page directory
Page instfiles

UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  ; Only stop this installation, never a separate copy running elsewhere.
  System::Call 'kernel32::SetEnvironmentVariable(t "LMN_INSTALL_TARGET", t "$INSTDIR\${EXE_NAME}") i .r0'
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -WindowStyle Hidden -Command "Get-Process LocalMeetingNotes -ErrorAction SilentlyContinue | Where-Object { $$_.Path -eq $$env:LMN_INSTALL_TARGET } | ForEach-Object { & $$env:SystemRoot\System32\taskkill.exe /PID $$_.Id /T /F | Out-Null }"'
  System::Call 'kernel32::SetEnvironmentVariable(t "LMN_INSTALL_TARGET", t "") i .r0'
  SetOutPath "$INSTDIR"
  ClearErrors
  File "..\dist-app\${EXE_NAME}"
  IfErrors install_failed
  SetOutPath "$INSTDIR\vendor"
  File "..\vendor\ffmpeg.exe"
  IfErrors install_failed
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  Goto install_done
  install_failed:
    SetErrorLevel 1
    Abort "Could not install the application. Close Local Meeting Notes and retry."
  install_done:
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  Delete "$INSTDIR\${EXE_NAME}"
  Delete "$INSTDIR\vendor\ffmpeg.exe"
  RMDir "$INSTDIR\vendor"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalMeetingNotes"
SectionEnd
