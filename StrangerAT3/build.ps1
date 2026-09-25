# ===========================================================================
# Build Stranger_AT3_v2.ps1 -> "Stranger AT3.exe"
#
# WHY THIS EXISTS
#
# The launcher ships as a ps2exe-compiled binary, and the exe is what anyone
# actually runs. For a week the shipped exe was a Sep 5 build while the script
# kept being edited, so a whole feature was written, reviewed and reported as
# done without ever being reachable - the source was right and the running
# program was stale. Editing the .ps1 is only half the job; this script is the
# other half, so the gap cannot reopen silently.
#
# It refuses rather than warns, in the order that catches mistakes soonest:
#
#   1. the launcher must not be running   - you cannot overwrite a live exe,
#                                           and a failed copy looks like a
#                                           successful build from the outside
#   2. the script must PARSE              - ps2exe happily compiles a file
#                                           with syntax errors into an exe
#                                           that dies on launch
#   3. the build must VERIFY              - GUI subsystem, and the markers you
#                                           name with -Verify must be embedded
#
# The Sep 5 build is preserved once as "Stranger AT3.exe.precreator" and is
# never overwritten after that, so the last known-good binary always survives.
#
#   .\build.ps1                    parse-check, build, verify, install
#   .\build.ps1 -Check             parse-check only, write nothing
#   .\build.ps1 -Verify btnCreator,Show-AT3PropEditor
#                                  also assert these strings made it in
# ===========================================================================
[CmdletBinding()]
param(
    [switch]$Check,
    [string[]]$Verify = @()
)

$ErrorActionPreference = "Stop"
$Dir    = $PSScriptRoot
$Source = Join-Path $Dir "Stranger_AT3_v2.ps1"
$Exe    = Join-Path $Dir "Stranger AT3.exe"
$Icon   = Join-Path $Dir "Stranger_AT3.ico"
$Title  = "Stranger: Armed to the Teeth"
# One rolling backup of whatever was installed before this run, plus the
# untouched pre-Creator build kept forever.
$Roll   = Join-Path $Dir "Stranger AT3.exe.prev"

function Fail { param([string]$M) Write-Host "  REFUSED: $M" -ForegroundColor Red; exit 1 }
function Ok   { param([string]$M) Write-Host "  ok   $M" -ForegroundColor Green }
function Info { param([string]$M) Write-Host "       $M" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "Stranger AT3 - build" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $Source)) { Fail "source not found: $Source" }

# --- 1. nothing may be holding the exe open -------------------------------
$running = Get-Process -Name "Stranger AT3" -ErrorAction SilentlyContinue
if ($running) {
    # -Check writes nothing, so a running launcher is not a problem for it -
    # but do NOT print "not running", which would be a plain lie in the one
    # place someone looks to confirm the state before building.
    if (-not $Check) {
        Fail ("the launcher is running (PID " + ($running.Id -join ", ") + ") - close it and re-run")
    }
    Info ("launcher IS running (PID " + ($running.Id -join ", ") + ") - fine for -Check, blocks a real build")
} else {
    Ok "launcher is not running"
}

# --- 2. the script must parse ---------------------------------------------
# ps2exe does NOT syntax-check. A file with an unbalanced brace compiles
# cleanly into an exe that shows nothing at all when double-clicked, and
# because the build is -noConsole there is no error anywhere to read.
$errs = $null; $toks = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$toks, [ref]$errs)
if ($errs -and $errs.Count) {
    Write-Host "  REFUSED: $($errs.Count) syntax error(s) in Stranger_AT3_v2.ps1" -ForegroundColor Red
    $errs | Select-Object -First 10 | ForEach-Object {
        Write-Host ("         line {0}: {1}" -f $_.Extent.StartLineNumber, $_.Message) -ForegroundColor Red
    }
    exit 1
}
Ok ("source parses clean ({0:N0} bytes)" -f (Get-Item $Source).Length)

# --- 2b. the theme dictionary must LOAD -----------------------------------
# Set-AT3Theme wraps XamlReader.Load in an empty catch, so a malformed style
# does not throw - it silently ships the launcher with stock white Windows
# controls. Load it here, where a failure is loud.
try {
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml
    $src = Get-Content -LiteralPath $Source -Raw
    $m = [regex]::Match($src, "(?s)\`$script:ThemeXaml = @'\r?\n(.*?)\r?\n'@")
    if ($m.Success) {
        $sr = New-Object System.IO.StringReader $m.Groups[1].Value
        $xr = [System.Xml.XmlReader]::Create($sr)
        $dict = [Windows.Markup.XamlReader]::Load($xr)
        Ok ("theme dictionary loads ({0} styles)" -f $dict.Count)
    } else {
        Info "theme block not found - skipped"
    }
} catch {
    Fail ("theme XAML is malformed, it would ship unstyled: " + $_.Exception.Message)
}

if ($Check) { Write-Host "`n  -Check: nothing written.`n" -ForegroundColor Yellow; exit 0 }

# --- 3. compile ------------------------------------------------------------
Import-Module ps2exe -ErrorAction Stop
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("StrangerAT3_build_{0}.exe" -f $PID)
if (Test-Path -LiteralPath $Tmp) { Remove-Item -LiteralPath $Tmp -Force }

# -noConsole is what makes this a subsystem-2 GUI binary. Without it the
# launcher opens a black console window behind the WPF form.
# The release number comes from the script itself ($script:AT3Version), so the
# exe's file properties can never disagree with what the launcher shows.
$Ver = "0.0.0"
$m = [regex]::Match([System.IO.File]::ReadAllText($Source), '\$script:AT3Version\s*=\s*"([0-9.]+)"')
if ($m.Success) { $Ver = $m.Groups[1].Value }
$args = @{
    inputFile   = $Source
    outputFile  = $Tmp
    noConsole   = $true
    title       = $Title
    product     = $Title
    description = "Stranger: Armed to the Teeth v$Ver"
    version     = "$Ver.0"
}
if (Test-Path -LiteralPath $Icon) { $args["iconFile"] = $Icon }
Invoke-ps2exe @args | Out-Null
if (-not (Test-Path -LiteralPath $Tmp)) { Fail "ps2exe produced no output" }
Ok ("compiled ({0:N0} bytes)" -f (Get-Item $Tmp).Length)

# --- 4. verify the artefact BEFORE installing it ---------------------------
$b = [System.IO.File]::ReadAllBytes($Tmp)
$pe = [BitConverter]::ToInt32($b, 0x3C)
$sub = [BitConverter]::ToUInt16($b, $pe + 0x5C)
if ($sub -ne 2) { Fail "subsystem is $sub, expected 2 (Windows GUI) - -noConsole did not take" }
Ok "subsystem 2 (Windows GUI)"

if ($Verify.Count) {
    # ps2exe stores the script UTF-16; check both encodings so the caller does
    # not have to care how a given string was emitted.
    $txt = [System.Text.Encoding]::Unicode.GetString($b) + [System.Text.Encoding]::ASCII.GetString($b)
    $missing = @()
    foreach ($n in $Verify) { if ($txt -notmatch [regex]::Escape($n)) { $missing += $n } }
    if ($missing.Count) { Fail ("not embedded: " + ($missing -join ", ")) }
    Ok ("embedded: " + ($Verify -join ", "))
}

# --- 5. install ------------------------------------------------------------
if (Test-Path -LiteralPath $Exe) {
    Copy-Item -LiteralPath $Exe -Destination $Roll -Force
    Info "previous build -> Stranger AT3.exe.prev"
}
Copy-Item -LiteralPath $Tmp -Destination $Exe -Force
Remove-Item -LiteralPath $Tmp -Force -ErrorAction SilentlyContinue
$f = Get-Item -LiteralPath $Exe
Ok ("installed  {0:N0} bytes  {1}" -f $f.Length, $f.LastWriteTime)
Write-Host ""
