# Secrets travel only on stdin/stdout pipes. Windows persists the generic credential.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AsisWinCred {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct Credential {
        public uint Flags, Type;
        public string TargetName, Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist, AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias, UserName;
    }
    [DllImport("advapi32.dll", EntryPoint="CredWriteW", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool Write(ref Credential value, uint flags);
    [DllImport("advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool Read(string target, uint type, uint flags, out IntPtr value);
    [DllImport("advapi32.dll")]
    public static extern void CredFree(IntPtr value);
}
'@
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($request.service -notin @('local.personal-asis.coordinator', 'local.personal-asis.backup') -or
        [string]::IsNullOrEmpty($request.account)) { exit 2 }
    $target = $request.service + '/' + $request.account
    if ($request.action -eq 'set') {
        $bytes = [Text.Encoding]::UTF8.GetBytes([string]$request.secret)
        if ($bytes.Length -eq 0 -or $bytes.Length -gt 2560) { exit 2 }
        $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($bytes.Length)
        try {
            [Runtime.InteropServices.Marshal]::Copy($bytes, 0, $buffer, $bytes.Length)
            $value = [AsisWinCred+Credential]::new()
            $value.Type = 1
            $value.TargetName = $target
            $value.UserName = $request.account
            $value.CredentialBlobSize = $bytes.Length
            $value.CredentialBlob = $buffer
            $value.Persist = 2
            if (-not [AsisWinCred]::Write([ref]$value, 0)) { exit 2 }
            [Console]::Write('{"stored":true}')
        } finally {
            for ($i = 0; $i -lt $bytes.Length; $i++) {
                [Runtime.InteropServices.Marshal]::WriteByte($buffer, $i, 0)
            }
            [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)
            [Array]::Clear($bytes, 0, $bytes.Length)
        }
    } elseif ($request.action -eq 'get') {
        $pointer = [IntPtr]::Zero
        if (-not [AsisWinCred]::Read($target, 1, 0, [ref]$pointer)) {
            if ([Runtime.InteropServices.Marshal]::GetLastWin32Error() -eq 1168) { exit 3 }
            exit 2
        }
        try {
            $value = [Runtime.InteropServices.Marshal]::PtrToStructure($pointer, [type][AsisWinCred+Credential])
            $bytes = [byte[]]::new($value.CredentialBlobSize)
            [Runtime.InteropServices.Marshal]::Copy($value.CredentialBlob, $bytes, 0, $bytes.Length)
            [Console]::Write((@{secret = [Text.Encoding]::UTF8.GetString($bytes)} | ConvertTo-Json -Compress))
            [Array]::Clear($bytes, 0, $bytes.Length)
        } finally { [AsisWinCred]::CredFree($pointer) }
    } else { exit 2 }
} catch { exit 2 }
