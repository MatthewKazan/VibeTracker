Unicode true
!include FileFunc.nsh
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\JobTracker"
Name "JobTracker"
OutFile "../release/JobTracker-Setup-${VERSION}-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\JobTracker"
; Upgrades reuse the folder chosen for the previous install.
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
RequestExecutionLevel user
Icon "../build/icon.ico"
UninstallIcon "../build/icon.ico"
Page directory "" "" DirectoryLeave
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

; The uninstaller removes the whole install folder, so always install into a dedicated JobTracker folder
; rather than directly into a folder the user picked (e.g. Documents).
Function DirectoryLeave
${GetFileName} "$INSTDIR" $0
StrCmp $0 "JobTracker" +2
StrCpy $INSTDIR "$INSTDIR\JobTracker"
FunctionEnd

; Files of a running app are locked on Windows, so ask the user to close JobTracker first.
!macro WaitForAppToClose UN
Function ${UN}WaitForAppToClose
check:
nsExec::ExecToStack 'cmd /c tasklist /FI "IMAGENAME eq JobTracker.exe" /NH | find /I "JobTracker.exe"'
Pop $0
Pop $1
StrCmp $0 "0" 0 done
MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "JobTracker is running. Quit JobTracker, then click Retry." /SD IDCANCEL IDRETRY check
Abort
done:
FunctionEnd
!macroend
!insertmacro WaitForAppToClose ""
!insertmacro WaitForAppToClose "un."
Function .onInit
Call WaitForAppToClose
FunctionEnd
Function un.onInit
Call un.WaitForAppToClose
FunctionEnd

Section
SetOutPath "$INSTDIR"
File /r "../release/win-unpacked\*"
WriteUninstaller "$INSTDIR\Uninstall.exe"
CreateDirectory "$SMPROGRAMS\JobTracker"
CreateShortcut "$SMPROGRAMS\JobTracker\JobTracker.lnk" "$INSTDIR\JobTracker.exe"
CreateShortcut "$DESKTOP\JobTracker.lnk" "$INSTDIR\JobTracker.exe"
WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "JobTracker"
WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\JobTracker.exe"
WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd
Section "Uninstall"
Delete "$DESKTOP\JobTracker.lnk"
RMDir /r "$SMPROGRAMS\JobTracker"
RMDir /r "$INSTDIR"
MessageBox MB_YESNO|MB_DEFBUTTON2 "Also delete your JobTracker data (applications, résumé, saved analyses and backups)? This cannot be undone." /SD IDNO IDNO keepdata
RMDir /r "$APPDATA\Waypoint"
keepdata:
DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
