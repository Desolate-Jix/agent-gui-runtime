; 当前用户安装包；文件清单仅由已验证载荷生成。
#ifndef ProductAppId
#define ProductAppId "AgentGuiRuntime.AgentReview.PerUser"
#endif
#ifndef ProductAppName
#define ProductAppName "Agent Review"
#endif
#ifndef ProductVersion
#define ProductVersion "0.0.0"
#endif
#ifndef ReleaseId
#define ReleaseId "unprepared"
#endif
#ifndef SourceRoot
#define SourceRoot "."
#endif
#ifndef BuildOutputDir
#define BuildOutputDir "."
#endif
#ifndef IncludeFile
#define IncludeFile "installer-files.iss"
#endif
#ifndef ReserveBytes
#define ReserveBytes 1073741824
#endif

[Setup]
AppId={#ProductAppId}
AppName={#ProductAppName}
AppVersion={#ProductVersion}
DefaultDirName={localappdata}\Programs\AgentReview
DefaultGroupName={#ProductAppName}
PrivilegesRequired=lowest
CloseApplications=no
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputDir={#BuildOutputDir}
OutputBaseFilename=AgentReview-{#ReleaseId}
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#ProductAppName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
#include IncludeFile

[Icons]
Name: "{userprograms}\{#ProductAppName}"; Filename: "{app}\versions\{#ReleaseId}\AgentReview.exe"; WorkingDir: "{app}\versions\{#ReleaseId}"

[Code]
const
  ReserveBytes = {#ReserveBytes};
  INVALID_FILE_ATTRIBUTES = $FFFFFFFF;

function GetWinFileAttributes(const Value: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function IsReparsePoint(const Value: String): Boolean;
var
  Attributes: Cardinal;
begin
  Attributes := GetWinFileAttributes(Value);
  Result := (Attributes <> INVALID_FILE_ATTRIBUTES) and ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0);
end;

function DirectoryIsNonEmpty(const Value: String): Boolean;
var
  Found: TFindRec;
  Item: String;
begin
  Result := False;
  if not DirExists(Value) then Exit;
  if FindFirst(AddBackslash(Value) + '*', Found) then begin
    try
      repeat
        Item := Found.Name;
        if (Item <> '.') and (Item <> '..') then begin
          Result := True;
          Exit;
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;

function ExistingInstallLocationMatches(const Value: String): Boolean;
var
  InstalledLocation: String;
begin
  Result := RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#ProductAppId}_is1', 'InstallLocation', InstalledLocation) and
    (CompareText(RemoveBackslashUnlessRoot(InstalledLocation), RemoveBackslashUnlessRoot(Value)) = 0);
end;


function ValidateTargetAncestors(const Value: String): String;
var
  Current: String;
begin
  Result := '';
  Current := RemoveBackslashUnlessRoot(Value);
  while Current <> '' do begin
    if FileExists(Current) then begin
      Result := '安装目录的现有上级路径不能是文件。';
      Exit;
    end;
    if DirExists(Current) and IsReparsePoint(Current) then begin
      Result := '安装目录的现有上级目录不能是重解析点。';
      Exit;
    end;
    if Current = ExtractFileDir(Current) then Break;
    Current := ExtractFileDir(Current);
  end;
end;

function ExistingDirectoryForSpace(const Value: String): String;
var
  Parent: String;
begin
  Result := RemoveBackslashUnlessRoot(Value);
  while (Result <> '') and (not DirExists(Result)) do begin
    Parent := ExtractFileDir(Result);
    if Parent = Result then begin
      Result := '';
      Exit;
    end;
    Result := Parent;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  FreeSpace, TotalSpace, RequiredSpace: Int64;
  ReleaseDirectory, SpaceDirectory, AncestorError: String;
begin
  Result := '';
  AncestorError := ValidateTargetAncestors(WizardDirValue);
  if AncestorError <> '' then begin
    Result := AncestorError;
    Exit;
  end;
  { 升级必须沿用同一根目录，防止共享卸载入口丢失旧版本记录。 }
  if RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#ProductAppId}_is1') and
     (not ExistingInstallLocationMatches(WizardDirValue)) then begin
    Result := '已存在当前用户安装。请使用原安装目录升级；更换目录前请先通过原卸载入口卸载程序，审核历史和外部模型会保留。';
    Exit;
  end;
  if DirectoryIsNonEmpty(WizardDirValue) and
     (not ExistingInstallLocationMatches(WizardDirValue)) then begin
    Result := '安装目录非空，且不是已注册的 Agent Review 安装目录。';
    Exit;
  end;
  if IsReparsePoint(AddBackslash(WizardDirValue) + 'versions') then begin
    Result := '安装目录的 versions 目录不能是重解析点。';
    Exit;
  end;
  ReleaseDirectory := AddBackslash(WizardDirValue) + 'versions\{#ReleaseId}';
  if DirExists(ReleaseDirectory) or FileExists(ReleaseDirectory) then begin
    Result := '该精确版本已存在，已拒绝覆盖。';
    Exit;
  end;
  SpaceDirectory := ExistingDirectoryForSpace(WizardDirValue);
  if (SpaceDirectory = '') or not GetSpaceOnDisk64(SpaceDirectory, FreeSpace, TotalSpace) then begin
    Result := '无法验证安装磁盘的可用空间。';
    Exit;
  end;
  RequiredSpace := Int64({#PayloadBytes}) + ReserveBytes;
  if FreeSpace < RequiredSpace then begin
    Result := '磁盘空间不足：需要新载荷大小外加 1 GiB 保留空间。';
    Exit;
  end;
end;
