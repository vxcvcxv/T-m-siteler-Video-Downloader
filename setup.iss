[Setup]
AppName=ALIDWD Video Downloader
AppVersion=5.1
DefaultDirName={pf}\ALIDWD
DefaultGroupName=ALIDWD Downloader
OutputDir=.\Output
OutputBaseFilename=ALIDWD_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\ALIDWD\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "EklentiKurulum.html"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ALIDWD"; Filename: "{app}\ALIDWD.exe"
Name: "{commondesktop}\ALIDWD"; Filename: "{app}\ALIDWD.exe"

[Run]
Filename: "{app}\ALIDWD.exe"; Description: "ALIDWD'i Baslat"; Flags: nowait postinstall skipifsilent
Filename: "{app}\EklentiKurulum.html"; Description: "Chrome Eklentisi Kurulum Rehberini Goruntule"; Flags: shellexec postinstall skipifsilent
