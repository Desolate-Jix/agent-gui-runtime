// 两个产品共用预检与文件所有权契约，产品常量由构建工具固定。
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class ComponentInstaller {
    const string Marker = ".component-install.json";
    const string TestMarker = ".component-installer-test.json";
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
    static readonly string Sid = WindowsIdentity.GetCurrent().User.Value;
    static string Self { get { return Assembly.GetExecutingAssembly().Location; } }
    static string DefaultRoot { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", Identity.product_id); } }
    static string RegistryKey { get { return @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + Identity.product_id; } }
    sealed class FileFact { public string path { get; set; } public long size { get; set; } public string sha256 { get; set; } }
    sealed class InstallRecord {
        public string format { get; set; } public string component { get; set; }
        public string product_id { get; set; } public string version { get; set; }
        public string root { get; set; } public string user_sid { get; set; }
        public string mode { get; set; } public List<FileFact> files { get; set; }
        public string state { get; set; }
    }
    static string Hash(Stream stream) { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
    static string HashFile(string path) { using (var stream = File.OpenRead(path)) return Hash(stream); }
    static string Canonical(string path) { return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar); }
    static bool Same(string a, string b) { return string.Equals(a, b, StringComparison.OrdinalIgnoreCase); }
    static void Fail(string reason) { throw new InvalidOperationException(reason); }
    static void NoReparse(string path) {
        string current = Path.GetFullPath(path);
        while (!string.IsNullOrEmpty(current)) {
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                Fail("Reparse point is forbidden: " + current);
            current = Path.GetDirectoryName(current);
        }
    }
    static string SafePath(string name, bool metadata) {
        if (string.IsNullOrEmpty(name) || name.Contains("\\") || name.Contains(":")) Fail("Unsafe payload path");
        foreach (string part in name.Split('/')) {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ")
                || part.Any(c => c < 32 || "<>\"|?*".Contains(c))
                || Regex.IsMatch(part, @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", RegexOptions.IgnoreCase)) Fail("Unsafe payload path: " + name);
        }
        if (!metadata && (Same(name, Marker) || Same(name, "Uninstall.exe"))) Fail("Reserved payload path");
        return name;
    }
    static string Target(string root, string name, bool metadata) {
        string result = Path.GetFullPath(Path.Combine(root, SafePath(name, metadata).Replace('/', Path.DirectorySeparatorChar)));
        if (!result.StartsWith(Canonical(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) Fail("Path escaped install root");
        NoReparse(result); return result;
    }
    static void WriteJson(string path, object value) { File.WriteAllText(path, Json.Serialize(value), new UTF8Encoding(false)); }
    static byte[] Resource(string name, string expectedHash) {
        using (Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
            if (input == null) Fail("Missing embedded resource: " + name);
            using (var buffer = new MemoryStream()) {
                input.CopyTo(buffer); byte[] bytes = buffer.ToArray();
                using (var verify = new MemoryStream(bytes)) if (Hash(verify) != expectedHash) Fail("Embedded resource integrity failure: " + name);
                return bytes;
            }
        }
    }
    static List<FileFact> PreflightPayload() {
        byte[] manifest = Resource("payload-manifest.json", Identity.manifest_sha256);
        var doc = Json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(manifest));
        var expectedKeys = new HashSet<string>(new[] {"format", "component", "product_id", "entrypoint", "display_name", "version", "files"});
        if (!expectedKeys.SetEquals(doc.Keys) || (string)doc["format"] != "component-payload-v1"
            || (string)doc["component"] != Identity.component || (string)doc["product_id"] != Identity.product_id
            || (string)doc["entrypoint"] != Identity.entrypoint || (string)doc["version"] != Identity.version) Fail("Invalid embedded manifest identity");
        var rows = new List<FileFact>(); var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (object item in (IEnumerable)doc["files"]) {
            var row = (Dictionary<string, object>)item;
            if (!new HashSet<string>(new[] {"path", "size", "sha256"}).SetEquals(row.Keys)) Fail("Invalid manifest file keys");
            if(!(row["size"] is int || row["size"] is long)) Fail("Manifest size must be an integer");
            string path = SafePath((string)row["path"], false); long size = Convert.ToInt64(row["size"]);
            string hash = (string)row["sha256"];
            if (!seen.Add(path) || size < 0 || !Regex.IsMatch(hash, "^[0-9a-f]{64}$")) Fail("Invalid duplicate/size/hash manifest fact");
            rows.Add(new FileFact {path = path, size = size, sha256 = hash});
        }
        if (rows.Count == 0 || !seen.Contains(Identity.entrypoint)) Fail("Missing component entrypoint");
        foreach (string name in seen) if (seen.Any(other => other.StartsWith(name + "/", StringComparison.OrdinalIgnoreCase))) Fail("File/directory path conflict");
        byte[] archive = Resource("payload.zip", Identity.payload_sha256);
        using (var input = new MemoryStream(archive)) using (var zip = new ZipArchive(input, ZipArchiveMode.Read)) {
            var actual = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (ZipArchiveEntry entry in zip.Entries) {
                string path = SafePath(entry.FullName, false);
                if (!actual.Add(path)) Fail("Duplicate ZIP path");
                var row = rows.SingleOrDefault(r => Same(r.path, path));
                if (row == null || entry.Length != row.size) Fail("ZIP/manifest file mismatch");
                using (Stream stream = entry.Open()) if (Hash(stream) != row.sha256) Fail("ZIP payload hash mismatch");
            }
            if (!actual.SetEquals(seen)) Fail("ZIP omits manifest files");
        }
        return rows;
    }
    static string CheckRoot(string supplied, bool install) {
        if (!Path.IsPathRooted(supplied) || supplied != Path.GetFullPath(supplied)) Fail("Check root must be an explicit absolute canonical path");
        string root = Canonical(supplied), temp = Canonical(Path.GetTempPath());
        if (!root.StartsWith(temp + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) Fail("Check root must be a new child of the current temporary directory");
        NoReparse(root);
        string marker = Path.Combine(root, TestMarker);
        NoReparse(marker);
        if (Directory.Exists(root)) {
            if (!File.Exists(marker)) Fail("Existing check root is not an installer-owned test directory");
            var record = Json.Deserialize<Dictionary<string, string>>(File.ReadAllText(marker, Encoding.UTF8));
            if (record.Count != 3 || record["format"] != "component-installer-test-v1" || !Same(record["root"], root) || record["sid"] != Sid) Fail("Invalid check ownership marker");
        } else {
            if (!install) Fail("Check uninstall root does not exist");
            Directory.CreateDirectory(root);
            WriteJson(marker, new Dictionary<string, string> {{"format", "component-installer-test-v1"}, {"root", root}, {"sid", Sid}});
        }
        return Path.Combine(root, Identity.product_id);
    }
    static InstallRecord ReadRecord(string root, bool check, bool required) {
        NoReparse(root); string marker = Path.Combine(root, Marker);
        NoReparse(marker);
        if (!File.Exists(marker)) {
            if (required || Directory.Exists(root)) Fail("Existing directory is not a verified installation of this component");
            return null;
        }
        var record = Json.Deserialize<InstallRecord>(File.ReadAllText(marker, Encoding.UTF8));
        if (record == null || record.format != "component-install-v1" || record.component != Identity.component
            || record.product_id != Identity.product_id || !Same(record.root, Canonical(root)) || record.user_sid != Sid
            || record.mode != (check ? "check" : "normal") || record.files == null) Fail("Installation marker belongs to another component/user/root");
        if(record.state!=null && record.state!="installed" && record.state!="retained") Fail("Invalid installation marker lifecycle state");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in record.files) {
            Target(root, row.path, true);
            if (!seen.Add(row.path) || row.size < 0 || !Regex.IsMatch(row.sha256, "^[0-9a-f]{64}$")) Fail("Invalid installation file record");
        }
        // 从旧卸载器资源读取冻结清单，不能让可编辑标记自行新增文件所有权。
        var uninstallFact=record.files.SingleOrDefault(row=>Same(row.path,"Uninstall.exe"));
        string uninstallPath=Target(root,"Uninstall.exe",true);
        if(uninstallFact==null || !Matches(uninstallPath,uninstallFact)) Fail("Installed uninstaller changed; refusing unverified file ownership");
        Assembly previous=Assembly.Load(File.ReadAllBytes(uninstallPath));
        string expected=(string)previous.GetType("Identity").GetField("manifest_sha256",BindingFlags.Static|BindingFlags.NonPublic).GetRawConstantValue();
        byte[] bytes;
        using(Stream stream=previous.GetManifestResourceStream("payload-manifest.json")) using(var buffer=new MemoryStream()) {
            if(stream==null) Fail("Old installer manifest missing"); stream.CopyTo(buffer); bytes=buffer.ToArray();
        }
        using(var stream=new MemoryStream(bytes)) if(Hash(stream)!=expected) Fail("Old installer manifest integrity failure");
        var frozen=Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(bytes));
        if((string)frozen["component"]!=Identity.component || (string)frozen["product_id"]!=Identity.product_id || (string)frozen["version"]!=record.version) Fail("Old installer identity differs from marker");
        var frozenRows=Json.Deserialize<List<FileFact>>(Json.Serialize(frozen["files"]));
        if(record.files.Count!=frozenRows.Count+1) Fail("Installation marker contains unverified owned files");
        foreach(var row in frozenRows) {
            var claimed=record.files.SingleOrDefault(r=>Same(r.path,row.path));
            if(claimed==null || claimed.size!=row.size || claimed.sha256!=row.sha256) Fail("Installation marker differs from frozen file ownership");
        }
        return record;
    }
    static bool Matches(string path, FileFact row) { return File.Exists(path) && new FileInfo(path).Length == row.size && HashFile(path) == row.sha256; }
    static void Exclusive(string path) {
        if (!File.Exists(path)) return;
        try { using (File.Open(path, FileMode.Open, FileAccess.Read, FileShare.None)) {} }
        catch (IOException) { Fail("Component file is in use; close this component and retry: " + path); }
    }
    static void RunningGuard(string root) {
        foreach (var process in Process.GetProcesses()) using (process) {
            try {
                string image = process.MainModule.FileName;
                if (process.Id != Process.GetCurrentProcess().Id && image.StartsWith(Canonical(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                    Fail("Component is running; close it yourself and retry: " + image);
            } catch (System.ComponentModel.Win32Exception) {} catch (InvalidOperationException error) {
                if (error.Message.StartsWith("Component is running")) throw;
            }
        }
    }
    static void Install(string root, bool check, List<FileFact> rows, IntegrationBackend backend=null) {
        root = Canonical(root); NoReparse(root);
        InstallRecord old = ReadRecord(root, check, false); RunningGuard(root);
        if(!check) IntegrationPreflight(root);
        if (old != null) { Exclusive(Path.Combine(root,Marker)); foreach (var row in old.files) Exclusive(Target(root, row.path, true)); }
        var owned = old == null ? new List<FileFact>() : old.files;
        foreach (var row in rows.Concat(new[] {new FileFact {path="Uninstall.exe"}})) {
            string target = Target(root, row.path, true); var previous = owned.SingleOrDefault(r => Same(r.path, row.path));
            if (Directory.Exists(target) || File.Exists(target) && (previous == null || !Matches(target, previous)))
                Fail("Refusing to overwrite unknown or user-modified file: " + target);
        }
        foreach (var row in rows) {
            string parent = Path.GetDirectoryName(Target(root, row.path, false));
            while (!Same(parent, root)) { if (File.Exists(parent)) Fail("Payload parent is an existing file"); parent = Path.GetDirectoryName(parent); }
        }
        string stage = Path.Combine(Path.GetTempPath(), "component-installer-stage-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        var backups = new Dictionary<string, string>(); var written = new List<string>(); bool created = !Directory.Exists(root),keepStage=false;
        try {
            using (var input = new MemoryStream(Resource("payload.zip", Identity.payload_sha256))) using (var zip = new ZipArchive(input, ZipArchiveMode.Read)) {
                foreach (var entry in zip.Entries) { string target = Target(stage, entry.FullName, false); Directory.CreateDirectory(Path.GetDirectoryName(target)); using (var stream = entry.Open()) using (var output = File.Create(target)) stream.CopyTo(output); }
            }
            File.Copy(Self, Path.Combine(stage, "Uninstall.exe"));
            var files = rows.Select(r => new FileFact {path=r.path,size=r.size,sha256=r.sha256}).ToList();
            string uninstaller = Path.Combine(stage, "Uninstall.exe");
            files.Add(new FileFact {path="Uninstall.exe",size=new FileInfo(uninstaller).Length,sha256=HashFile(uninstaller)});
            Directory.CreateDirectory(root);
            var changes = files.Select(r => r.path).Concat(owned.Where(r => !files.Any(n => Same(n.path,r.path)) && Matches(Target(root,r.path,true),r)).Select(r => r.path)).Concat(new[]{Marker}).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            int index=0;
            foreach (string name in changes) { string target=Target(root,name,true); if (File.Exists(target)) { string backup=Path.Combine(stage,"backup-"+(index++)); File.Copy(target,backup); backups[target]=backup; } }
            foreach (var row in files) { string target=Target(root,row.path,true); NoReparse(target); Directory.CreateDirectory(Path.GetDirectoryName(target)); written.Add(target); File.Copy(Target(stage,row.path,true),target,true); }
            foreach (var row in owned.Where(r => !files.Any(n => Same(n.path,r.path)))) { string target=Target(root,row.path,true); if (Matches(target,row)) { File.Delete(target); written.Add(target); } }
            written.Add(Path.Combine(root,Marker));
            WriteJson(Target(root,Marker,true),new InstallRecord {format="component-install-v1",component=Identity.component,product_id=Identity.product_id,version=Identity.version,root=root,user_sid=Sid,mode=check?"check":"normal",files=files,state="installed"});
            if (!check || backend!=null) Integration(root, true, backend);
        } catch(Exception original) {
            var errors=new List<string>();
            foreach (string target in written.Distinct().Reverse()) {
                try {NoReparse(target);if(backups.ContainsKey(target)) File.Copy(backups[target],target,true);else if(File.Exists(target)) File.Delete(target);}
                catch(Exception error) {errors.Add(error.Message);}
            }
            if(errors.Count>0) {keepStage=true;throw new InvalidOperationException("Installation failed and payload rollback is incomplete; backups preserved in "+stage+": "+string.Join("; ",errors),original);}
            if (created && Directory.Exists(root) && !Directory.EnumerateFileSystemEntries(root).Any()) Directory.Delete(root);
            throw;
        } finally {if(!keepStage) RemoveStage(stage);}
    }
    static void RemoveStage(string stage) {
        NoReparse(stage);
        foreach (string path in Directory.GetFiles(stage,"*",SearchOption.AllDirectories)) { NoReparse(path); File.Delete(path); }
        foreach (string path in Directory.GetDirectories(stage,"*",SearchOption.AllDirectories).OrderByDescending(p=>p.Length)) { NoReparse(path); Directory.Delete(path); }
        Directory.Delete(stage);
    }
    static bool HasRetainedContent(string root,InstallRecord record,List<FileFact> removable) {
        var deletePaths=new HashSet<string>(removable.Select(row=>Target(root,row.path,true)),StringComparer.OrdinalIgnoreCase);
        var knownDirectories=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var row in record.files) {
            string directory=Path.GetDirectoryName(Target(root,row.path,true));
            while(!Same(directory,root)) {knownDirectories.Add(directory);directory=Path.GetDirectoryName(directory);}
        }
        var pending=new Stack<string>();pending.Push(root);
        while(pending.Count>0) {
            string directory=pending.Pop();NoReparse(directory);
            foreach(string path in Directory.EnumerateFileSystemEntries(directory)) {
                if(Same(path,Path.Combine(root,Marker))||Same(path,Path.Combine(root,"Uninstall.exe"))) continue;
                var attributes=File.GetAttributes(path);
                // 未知或重解析目录仅保留；不进入虚拟环境、缓存及用户内容。
                if((attributes&FileAttributes.ReparsePoint)!=0) return true;
                if((attributes&FileAttributes.Directory)!=0) {
                    if(!knownDirectories.Contains(path)) return true;
                    pending.Push(path);
                } else if(!deletePaths.Contains(path)) return true;
            }
        }
        return false;
    }
    static void Uninstall(string root, bool check, IntegrationBackend backend=null) {
        root=Canonical(root); InstallRecord record=ReadRecord(root,check,true); RunningGuard(root);
        if(!check) IntegrationPreflight(root);
        foreach(var row in record.files) Exclusive(Target(root,row.path,true));
        var removable=record.files.Where(row => Matches(Target(root,row.path,true),row)).ToList();
        bool retained=HasRetainedContent(root,record,removable);
        if(retained) removable=removable.Where(row=>!Same(row.path,"Uninstall.exe")).ToList();
        Exclusive(Path.Combine(root,Marker)); foreach(var row in removable) Exclusive(Target(root,row.path,true));
        string stage=Path.Combine(Path.GetTempPath(),"component-uninstall-stage-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(stage);
        var backups=new Dictionary<string,string>();int index=0;bool keepStage=false;
        try {
            foreach(string path in removable.Select(row=>Target(root,row.path,true)).Concat(new[]{Target(root,Marker,true)})) {string backup=Path.Combine(stage,(index++).ToString());File.Copy(path,backup);backups[path]=backup;}
            // 所有路径先验证，卸载只移除记录且未修改的文件。
            foreach(var row in removable) {string path=Target(root,row.path,true);if(Matches(path,row)) File.Delete(path);}
            if(retained) {record.state="retained";WriteJson(Target(root,Marker,true),record);}
            else File.Delete(Target(root,Marker,true));
            if(!check||backend!=null) Integration(root,false,backend);
        } catch(Exception original) {
            var errors=new List<string>();
            foreach(var entry in backups) {try {NoReparse(entry.Key);File.Copy(entry.Value,entry.Key,true);}catch(Exception error){errors.Add(error.Message);}}
            if(errors.Count>0) {keepStage=true;throw new InvalidOperationException("Uninstall failed and payload rollback is incomplete; backups preserved in "+stage+": "+string.Join("; ",errors),original);}
            throw;
        } finally {if(!keepStage) RemoveStage(stage);}
        var dirs=record.files.Select(row=>Path.GetDirectoryName(Target(root,row.path,true))).Distinct().OrderByDescending(p=>p.Length);
        foreach(string leaf in dirs) { string directory=leaf; while(directory.StartsWith(root,StringComparison.OrdinalIgnoreCase)) { NoReparse(directory); if(Directory.Exists(directory) && !Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory); if(Same(directory,root)) break; directory=Path.GetDirectoryName(directory); } }
        if(Directory.Exists(root) && !Directory.EnumerateFileSystemEntries(root).Any()) Directory.Delete(root);
    }
    static string ShortcutPath { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),Identity.display_name+".lnk"); } }
    static string DataDirectory { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AgentGUIRuntime","data"); } }
    static string ShortcutTarget(string root) {
        return Identity.component=="execution" ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe") : Path.Combine(root,Identity.entrypoint);
    }
    static string ShortcutArguments(string root) {
        return Identity.component=="execution" ? "-NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(root,Identity.entrypoint.Replace('/',Path.DirectorySeparatorChar))+"\" -RecognitionSource agent_current -DataDirectory \""+DataDirectory+"\"" : "";
    }
    static void VerifyShortcut(object link,string root) {
        Type type=link.GetType();
        string target=(string)type.InvokeMember("TargetPath",BindingFlags.GetProperty,null,link,null);
        string arguments=(string)type.InvokeMember("Arguments",BindingFlags.GetProperty,null,link,null);
        string directory=(string)type.InvokeMember("WorkingDirectory",BindingFlags.GetProperty,null,link,null);
        if(!Same(target,ShortcutTarget(root)) || arguments!=ShortcutArguments(root) || !Same(directory,root)) Fail("Shortcut target/arguments/working directory belong to another launch contract");
    }
    static void IntegrationPreflight(string root) {
        NoReparse(ShortcutPath);
        if(Identity.component=="execution" && !File.Exists(ShortcutTarget(root))) Fail("Windows PowerShell executable is unavailable");
        using(var key=Registry.CurrentUser.OpenSubKey(RegistryKey))
            if(key!=null && !Same((string)key.GetValue("InstallLocation"),root)) Fail("Registry product identity belongs to another root");
        if(File.Exists(ShortcutPath)) {
            Type type=Type.GetTypeFromProgID("WScript.Shell"); object shell=Activator.CreateInstance(type);
            object link=type.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{ShortcutPath});
            VerifyShortcut(link,root);
        }
    }
    abstract class IntegrationBackend {
        internal abstract string Shortcut {get;}
        internal abstract object CaptureRegistry();
        internal abstract void RestoreRegistry(object snapshot);
        internal abstract void ChangeShortcut(string root,bool install);
        internal abstract void ChangeRegistry(string root,bool install);
    }
    sealed class RegistryValueSnapshot { internal object value; internal RegistryValueKind kind; }
    sealed class RegistrySnapshot { internal bool existed; internal Dictionary<string,RegistryValueSnapshot> values=new Dictionary<string,RegistryValueSnapshot>(); }
    sealed class NormalIntegrationBackend:IntegrationBackend {
        internal override string Shortcut {get{return ShortcutPath;}}
        internal override object CaptureRegistry() {
            var snapshot=new RegistrySnapshot();
            using(var key=Registry.CurrentUser.OpenSubKey(RegistryKey)) if(key!=null) {
                snapshot.existed=true;
                foreach(string name in key.GetValueNames()) snapshot.values[name]=new RegistryValueSnapshot {value=key.GetValue(name,null,RegistryValueOptions.DoNotExpandEnvironmentNames),kind=key.GetValueKind(name)};
            }
            return snapshot;
        }
        internal override void RestoreRegistry(object value) {
            var snapshot=(RegistrySnapshot)value;
            if(!snapshot.existed) {Registry.CurrentUser.DeleteSubKey(RegistryKey,false);return;}
            using(var key=Registry.CurrentUser.CreateSubKey(RegistryKey)) {
                foreach(string name in key.GetValueNames()) if(!snapshot.values.ContainsKey(name)) key.DeleteValue(name);
                foreach(var entry in snapshot.values) key.SetValue(entry.Key,entry.Value.value,entry.Value.kind);
            }
        }
        internal override void ChangeShortcut(string root,bool install) {
            if(!install) {if(File.Exists(Shortcut)) File.Delete(Shortcut);return;}
            Type type=Type.GetTypeFromProgID("WScript.Shell"); object shell=Activator.CreateInstance(type);
            object link=type.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{Shortcut}); Type linkType=link.GetType();
            if(File.Exists(Shortcut)) VerifyShortcut(link,root);
            linkType.InvokeMember("TargetPath",BindingFlags.SetProperty,null,link,new object[]{ShortcutTarget(root)});
            linkType.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,link,new object[]{root});
            linkType.InvokeMember("Arguments",BindingFlags.SetProperty,null,link,new object[]{ShortcutArguments(root)});
            linkType.InvokeMember("Save",BindingFlags.InvokeMethod,null,link,null);
            System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);
            System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
        }
        internal override void ChangeRegistry(string root,bool install) {
            if(!install) {Registry.CurrentUser.DeleteSubKey(RegistryKey,false);return;}
            using(var key=Registry.CurrentUser.CreateSubKey(RegistryKey)) {
                key.SetValue("DisplayName",Identity.display_name);key.SetValue("DisplayVersion",Identity.version);
                key.SetValue("InstallLocation",root);key.SetValue("UninstallString","\""+Path.Combine(root,"Uninstall.exe")+"\" --uninstall");
                key.SetValue("NoModify",1);key.SetValue("NoRepair",1);
            }
        }
    }
    sealed class IsolatedIntegrationBackend:IntegrationBackend {
        internal string directory; internal string failure;
        internal override string Shortcut {get{return Path.Combine(directory,"shortcut.bin");}}
        string RegistryFile {get{return Path.Combine(directory,"registry.json");}}
        internal override object CaptureRegistry() {return File.Exists(RegistryFile)?File.ReadAllBytes(RegistryFile):null;}
        internal override void RestoreRegistry(object snapshot) {if(snapshot==null) {if(File.Exists(RegistryFile)) File.Delete(RegistryFile);} else File.WriteAllBytes(RegistryFile,(byte[])snapshot);}
        internal override void ChangeShortcut(string root,bool install) {
            if(install) WriteJson(Shortcut,new {target=ShortcutTarget(root),arguments=ShortcutArguments(root),directory=root});
            else if(File.Exists(Shortcut)) File.Delete(Shortcut);
            if(failure=="shortcut") Fail("Injected isolated shortcut write failure");
        }
        internal override void ChangeRegistry(string root,bool install) {
            if(install) WriteJson(RegistryFile,new {DisplayName=Identity.display_name,DisplayVersion=Identity.version,InstallLocation=root});
            else if(File.Exists(RegistryFile)) File.Delete(RegistryFile);
            if(failure=="registry") Fail("Injected isolated registry write failure");
        }
    }
    static void Integration(string root,bool install,IntegrationBackend backend=null) {
        backend=backend??new NormalIntegrationBackend(); NoReparse(backend.Shortcut);
        byte[] shortcut=File.Exists(backend.Shortcut)?File.ReadAllBytes(backend.Shortcut):null;
        object registry=backend.CaptureRegistry();
        try {backend.ChangeShortcut(root,install);backend.ChangeRegistry(root,install);}
        catch(Exception original) {
            var errors=new List<string>();
            try {NoReparse(backend.Shortcut);if(shortcut==null) {if(File.Exists(backend.Shortcut)) File.Delete(backend.Shortcut);} else File.WriteAllBytes(backend.Shortcut,shortcut);} catch(Exception error) {errors.Add("shortcut restore: "+error.Message);}
            try {backend.RestoreRegistry(registry);} catch(Exception error) {errors.Add("registry restore: "+error.Message);}
            if(errors.Count>0) throw new InvalidOperationException("Integration failed and rollback is incomplete: "+string.Join("; ",errors),original);
            throw new InvalidOperationException("Integration write failed; previous integration state restored: "+original.Message,original);
        }
    }
    static void CheckIntegrationFailure(string root,List<FileFact> rows) {
        if(!Directory.Exists(root)) Install(root,true,rows); string marker=Path.Combine(root,Marker); byte[] originalMarker=File.ReadAllBytes(marker);
        var oldFiles=ReadRecord(root,true,true).files; var hashes=oldFiles.ToDictionary(row=>row.path,row=>HashFile(Target(root,row.path,true)));
        string directory=Path.Combine(Path.GetDirectoryName(root),"isolated-integration");Directory.CreateDirectory(directory);
        var backend=new IsolatedIntegrationBackend {directory=directory};
        byte[] oldShortcut=Encoding.UTF8.GetBytes("original shortcut bytes");
        byte[] oldRegistry=Encoding.UTF8.GetBytes("{\"InstallLocation\":\"old\",\"UnknownString\":\"retain\",\"UnknownBinary\":[0,255],\"UnknownDword\":42}");
        foreach(bool existed in new[]{false,true}) foreach(string fault in new[]{"shortcut","registry"}) {
            string registry=Path.Combine(directory,"registry.json");
            if(existed) {File.WriteAllBytes(backend.Shortcut,oldShortcut);File.WriteAllBytes(registry,oldRegistry);}
            else {if(File.Exists(backend.Shortcut)) File.Delete(backend.Shortcut);if(File.Exists(registry)) File.Delete(registry);}
            backend.failure=fault;bool failed=false;
            try {Install(root,true,rows,backend);} catch(InvalidOperationException error) {if(!error.Message.StartsWith("Integration write failed; previous integration state restored")) throw;failed=true;}
            if(!failed) Fail("Isolated injected integration failure did not execute");
            if(existed) {if(!File.ReadAllBytes(backend.Shortcut).SequenceEqual(oldShortcut)||!File.ReadAllBytes(registry).SequenceEqual(oldRegistry)) Fail("Isolated old integration state was not restored");}
            else if(File.Exists(backend.Shortcut)||File.Exists(registry)) Fail("Isolated new integration state was not removed");
            if(!File.ReadAllBytes(marker).SequenceEqual(originalMarker) || hashes.Any(entry=>HashFile(Target(root,entry.Key,true))!=entry.Value)) Fail("Payload rollback differs from original");
        }
        foreach(string fault in new[]{"shortcut","registry"}) {
            string registry=Path.Combine(directory,"registry.json");File.WriteAllBytes(backend.Shortcut,oldShortcut);File.WriteAllBytes(registry,oldRegistry);backend.failure=fault;bool failed=false;
            try {Uninstall(root,true,backend);} catch(InvalidOperationException error) {if(!error.Message.StartsWith("Integration write failed; previous integration state restored")) throw;failed=true;}
            if(!failed || !File.ReadAllBytes(backend.Shortcut).SequenceEqual(oldShortcut)||!File.ReadAllBytes(registry).SequenceEqual(oldRegistry)||!File.ReadAllBytes(marker).SequenceEqual(originalMarker)||hashes.Any(entry=>HashFile(Target(root,entry.Key,true))!=entry.Value)) Fail("Uninstall integration/payload rollback was incomplete");
        }
        string newRoot=Path.Combine(Path.GetDirectoryName(root),"first-install",Identity.product_id);
        foreach(string fault in new[]{"shortcut","registry"}) {
            if(File.Exists(backend.Shortcut)) File.Delete(backend.Shortcut);string registry=Path.Combine(directory,"registry.json");if(File.Exists(registry)) File.Delete(registry);
            backend.failure=fault;bool failed=false;
            try {Install(newRoot,true,rows,backend);} catch(InvalidOperationException error) {if(!error.Message.StartsWith("Integration write failed; previous integration state restored")) throw;failed=true;}
            if(!failed || File.Exists(backend.Shortcut)||File.Exists(registry)||Directory.Exists(newRoot)&&Directory.GetFiles(newRoot,"*",SearchOption.AllDirectories).Length!=0) Fail("First install rollback left integration or payload files");
            if(Directory.Exists(newRoot)) RemoveStage(newRoot);
        }
        Console.WriteLine(Json.Serialize(new {ok=true,backend="isolated-files",integration_written=false,shortcut_rollback=true,registry_rollback=true,payload_rollback=true,new_integration_removed=true,first_install_payload_removed=true,uninstall_payload_rollback=true}));
    }
    sealed class CleanupInfo {public int helper_pid {get;set;} public long helper_start_ticks {get;set;} public string helper_path {get;set;} public string worker_path {get;set;} public string error_path {get;set;} }
    static string PowerShellPath {get{return Path.Combine(Environment.GetEnvironmentVariable("SystemRoot"),"System32","WindowsPowerShell","v1.0","powershell.exe");}}
    static string PsLiteral(string value) {return "'"+value.Replace("'","''")+"'";}
    static void ValidateWorkerPath(string path) {
        path=Canonical(path);string temporary=Canonical(Path.GetTempPath());NoReparse(path);
        if(!Same(Path.GetDirectoryName(path),temporary) || !Regex.IsMatch(Path.GetFileName(path),"^component-uninstaller-[0-9a-f]{32}\\.exe$")) Fail("Cleanup worker is not this installer's exact temporary file");
    }
    static CleanupInfo StartCleanup() {
        ValidateWorkerPath(Self);NoReparse(PowerShellPath);
        int pid=Process.GetCurrentProcess().Id;long ticks=Process.GetCurrentProcess().StartTime.ToUniversalTime().Ticks;
        string hash=HashFile(Self),error=Self+".cleanup-error.txt";NoReparse(error);
        if(File.Exists(error)) Fail("Cleanup error path already exists");
        string script="$ErrorActionPreference='Stop'; $path="+PsLiteral(Self)+"; $errorPath="+PsLiteral(error)+"; $temp="+PsLiteral(Canonical(Path.GetTempPath()))+"; try { "
            +"$worker=Get-Process -Id "+pid+" -ErrorAction SilentlyContinue; if($null -ne $worker) { if($worker.StartTime.ToUniversalTime().Ticks -ne "+ticks+" -or $worker.MainModule.FileName -cne $path) { throw 'Cleanup worker identity changed'; }; $worker.WaitForExit(); }; "
            +"if([IO.Path]::GetFullPath($path) -cne $path -or [IO.Path]::GetDirectoryName($path) -cne $temp -or [IO.Path]::GetFileName($path) -notmatch '^component-uninstaller-[0-9a-f]{32}\\.exe$') { throw 'Cleanup path is not exact temporary worker'; }; "
            +"$current=$path; while($current) { if([IO.File]::Exists($current) -or [IO.Directory]::Exists($current)) { if(([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Cleanup reparse point rejected'; } }; $current=[IO.Path]::GetDirectoryName($current); }; "
            +"$stream=[IO.File]::OpenRead($path); try { $sha=[Security.Cryptography.SHA256]::Create(); try { $actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant(); } finally { $sha.Dispose(); } } finally { $stream.Dispose(); }; "
            +"if($actual -cne "+PsLiteral(hash)+") { throw 'Cleanup worker hash changed'; }; [IO.File]::Delete($path); if([IO.File]::Exists($path)) { throw 'Cleanup worker still exists'; }; "
            +"} catch { [IO.File]::WriteAllText($errorPath,($_ | Out-String),[Text.UTF8Encoding]::new($false)); exit 1 }; exit 0";
        string encoded=Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
        var start=new ProcessStartInfo(PowerShellPath,"-NoProfile -NonInteractive -EncodedCommand "+encoded) {UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden};
        using(var helper=Process.Start(start)) return new CleanupInfo {helper_pid=helper.Id,helper_start_ticks=helper.StartTime.ToUniversalTime().Ticks,helper_path=PowerShellPath,worker_path=Self,error_path=error};
    }
    static void WaitCleanup(CleanupInfo info) {
        ValidateWorkerPath(info.worker_path);NoReparse(info.error_path);
        try {using(var helper=Process.GetProcessById(info.helper_pid)) {
            if(helper.StartTime.ToUniversalTime().Ticks==info.helper_start_ticks && Same(helper.MainModule.FileName,info.helper_path)) {
                if(!helper.WaitForExit(15000)) Fail("Cleanup helper did not exit; preserved worker: "+info.worker_path);
                if(helper.ExitCode!=0) Fail("Cleanup helper failed; inspect "+info.error_path);
            }
        }} catch(ArgumentException) {}
        if(File.Exists(info.error_path)) Fail("Cleanup failed; inspect preserved evidence: "+info.error_path);
        if(File.Exists(info.worker_path)) Fail("Cleanup incomplete; temporary worker remains: "+info.worker_path);
    }
    static string CheckUninstallWorker(string supplied,string root) {
        ReadRecord(root,true,true);string temp=Path.Combine(Path.GetTempPath(),"component-uninstaller-"+Guid.NewGuid().ToString("N")+".exe");ValidateWorkerPath(temp);File.Copy(Self,temp);
        try {
            var start=new ProcessStartInfo(temp,"--check-uninstall-worker \""+supplied+"\"") {UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=new UTF8Encoding(false),StandardErrorEncoding=new UTF8Encoding(false)};
            using(var worker=Process.Start(start)) {
                var outputTask=worker.StandardOutput.ReadToEndAsync();var errorsTask=worker.StandardError.ReadToEndAsync();
                if(!worker.WaitForExit(15000)) Fail("Check uninstall worker timed out; preserved path: "+temp);
                string output=outputTask.GetAwaiter().GetResult(),errors=errorsTask.GetAwaiter().GetResult();
                if(string.IsNullOrWhiteSpace(output)) Fail("Check uninstall worker produced no cleanup evidence: "+errors+"; preserved path: "+temp);
                var info=Json.Deserialize<CleanupInfo>(output);WaitCleanup(info);
                if(worker.ExitCode!=0) Fail("Check uninstall worker failed after verified worker cleanup: "+errors);
                return temp;
            }
        } catch {if(File.Exists(temp)) NoReparse(temp);throw;}
    }
    static void UninstallNormal() {
        var record=ReadRecord(DefaultRoot,false,true);
        if(MessageBox.Show("Uninstall "+Identity.display_name+"?\n"+DefaultRoot+"\nUser data and modified/unknown files will be preserved.",Identity.display_name,MessageBoxButtons.OKCancel)!=DialogResult.OK) return;
        string temp=Path.Combine(Path.GetTempPath(),"component-uninstaller-"+Guid.NewGuid().ToString("N")+".exe"); File.Copy(Self,temp);
        Process.Start(new ProcessStartInfo(temp,"--remove-confirmed") {UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
    }
    [STAThread] static int Main(string[] args) {
        bool check=args.Length==2 && (args[0]=="--check-install" || args[0]=="--check-uninstall" || args[0]=="--check-uninstall-worker" || args[0]=="--check-integration-failure");
        try {
            if(check) {
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput(),new UTF8Encoding(false)){AutoFlush=true});
                Console.SetError(new StreamWriter(Console.OpenStandardError(),new UTF8Encoding(false)){AutoFlush=true});
                var rows=PreflightPayload(); string root=CheckRoot(args[1],args[0]=="--check-install"||args[0]=="--check-integration-failure");
                if(args[0]=="--check-integration-failure") {CheckIntegrationFailure(root,rows);return 0;}
                if(args[0]=="--check-uninstall-worker") {
                    ValidateWorkerPath(Self);var record=ReadRecord(root,true,true);if(!Matches(Self,record.files.Single(r=>Same(r.path,"Uninstall.exe")))) Fail("Check worker hash differs from installed uninstaller");
                    CleanupInfo info=StartCleanup();Console.WriteLine(Json.Serialize(info));Uninstall(root,true);return 0;
                }
                string workerPath=null;
                if(args[0]=="--check-install") Install(root,true,rows); else workerPath=CheckUninstallWorker(args[1],root);
                Console.WriteLine(Json.Serialize(new {ok=true,command=args[0],component=Identity.component,root=root,shortcut_target=ShortcutTarget(root),shortcut_arguments=ShortcutArguments(root),shortcut_working_directory=root,data_directory=DataDirectory,integration_written=false,worker_cleanup_complete=workerPath!=null,worker_path=workerPath})); return 0;
            }
            if(args.Length==1 && args[0]=="--remove-confirmed") {
                string temporary=Canonical(Path.GetTempPath());
                if(!Canonical(Self).StartsWith(temporary+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) Fail("Uninstall worker must be a temporary verified copy");
                var record=ReadRecord(DefaultRoot,false,true); var fact=record.files.Single(r=>Same(r.path,"Uninstall.exe"));
                if(!Matches(Self,fact)) Fail("Uninstall worker does not match installed component");
                StartCleanup();System.Threading.Thread.Sleep(500); Uninstall(DefaultRoot,false); return 0;
            }
            Application.EnableVisualStyles();
            if(args.Length==1 && args[0]=="--uninstall") { UninstallNormal(); return 0; }
            if(args.Length!=0) Fail("Unsupported installer arguments");
            var payload=PreflightPayload();
            using(var form=new Form {Text=Identity.display_name+" Setup",ClientSize=new Size(640,210),StartPosition=FormStartPosition.CenterScreen,FormBorderStyle=FormBorderStyle.FixedDialog,MaximizeBox=false}) {
                var label=new Label {Left=20,Top=20,Width=600,Height=120,Text=Identity.display_name+" "+Identity.version+"\n\nInstall for current user:\n"+DefaultRoot+"\n\nNo model weights or user library are installed by this installer. Unsigned preview."};
                var button=new Button {Text="Install",Left=510,Top=160,Width=110};
                button.Click+=(sender,eventArgs)=>{ try { Install(DefaultRoot,false,payload); MessageBox.Show("Installed successfully. User libraries remain outside the install directory.",Identity.display_name); form.Close(); } catch(Exception error) {MessageBox.Show(error.Message,"Installation refused/failed",MessageBoxButtons.OK,MessageBoxIcon.Error);} };
                form.Controls.Add(label);form.Controls.Add(button);Application.Run(form);
            }
            return 0;
        } catch(Exception error) { if(check || args.Any(a=>a.StartsWith("--check-"))) Console.Error.WriteLine(error.Message); else MessageBox.Show(error.Message,"Installer failed",MessageBoxButtons.OK,MessageBoxIcon.Error); return 1; }
    }
}
