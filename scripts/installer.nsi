Unicode true
Name "JobTracker"
OutFile "../release/JobTracker-Setup-1.1.6-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\JobTracker"
RequestExecutionLevel user
Icon "../build/icon.ico"
UninstallIcon "../build/icon.ico"
Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles
Section
SetOutPath "$INSTDIR"
File /r "../release/win-unpacked\*"
WriteUninstaller "$INSTDIR\Uninstall.exe"
CreateDirectory "$SMPROGRAMS\JobTracker"
CreateShortcut "$SMPROGRAMS\JobTracker\JobTracker.lnk" "$INSTDIR\JobTracker.exe"
CreateShortcut "$DESKTOP\JobTracker.lnk" "$INSTDIR\JobTracker.exe"
WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JobTracker" "DisplayName" "JobTracker"
WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JobTracker" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd
Section "Uninstall"
Delete "$DESKTOP\JobTracker.lnk"
RMDir /r "$SMPROGRAMS\JobTracker"
RMDir /r "$INSTDIR"
MessageBox MB_YESNO|MB_DEFBUTTON2 "Also delete your JobTracker data (applications, résumé, saved analyses and backups)? This cannot be undone." /SD IDNO IDNO keepdata
RMDir /r "$APPDATA\Waypoint"
keepdata:
DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JobTracker"
SectionEnd
