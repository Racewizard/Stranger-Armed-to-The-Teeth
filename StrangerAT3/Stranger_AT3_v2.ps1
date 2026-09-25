# ===========================================================================
# Stranger: Armed to the Teeth - launcher v0.2.1
#
# A ground-up rebuild of the UI for public release. The BACKEND is carried
# over unchanged from Stranger_AT3.ps1 (kept intact alongside this file), so
# behaviour is identical - only the presentation is new.
#
# Layout:
#   main window  - logo, action buttons left, editor menus right, feedback box
#   Gameplay Editor -> Global Game Rules / Ammotype Config / Character Studio
#   Map Editor      -> Ambience Config / Prop Editor / Spawns Editor
#
# RESTORE VANILLA never ships or reads game files of its own. It only puts
# back the .bak/.knockbak/.at3vanilla copies that THIS launcher made on the
# user's machine, so no Stranger's Wrath data is redistributed with AT3.
# ===========================================================================
#requires -Version 5.1
# Stranger: Armed to the Teeth - WPF front end for Stranger's Wrath / SWSE.
# (Built as 'Stranger AT3.exe'; source file name kept for continuity.)
# V1: one "Global" tab of gamerules, applied before/at launch.

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# $PSScriptRoot is empty inside a ps2exe-compiled executable (it isn't hosted
# as a real .ps1 file anymore), so fall back to the running process's own exe
# path - that always resolves correctly, compiled or not.
if ($PSScriptRoot) {
    $AT3Dir = $PSScriptRoot
} else {
    $AT3Dir = Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
}
$GameRoot        = Split-Path -Parent $AT3Dir
$ModDir          = Join-Path $GameRoot "SWSEMods\SWSE Console"
$AiPrefsPath     = Join-Path $ModDir "aiprefs.txt"
$PlayerPrefsPath = Join-Path $ModDir "playerprefs.txt"
$RemoteIn        = Join-Path $ModDir "remote_in.txt"
$RemoteOut       = Join-Path $ModDir "remote_out.txt"
$GameExe         = Join-Path $GameRoot "Launcher.exe"
$RegionDataDir   = Join-Path $AT3Dir "RegionData"
$AmmoCsvPath     = Join-Path $AT3Dir "AmmoKnockback.csv"
$AmmoMapPath     = Join-Path $AT3Dir "AmmoPatchMap.csv"
$PresetsDir      = Join-Path $AT3Dir "Presets"
$AT3LogPath      = Join-Path $AT3Dir "at3_debug.log"
# The one place the release number lives: startup, the title bar, presets
# and build.ps1 (which stamps it into the exe) all read it from here.
$script:AT3Version = "0.3.0"

# Last resort when a click appears to do nothing. WPF swallows exceptions raised
# inside event handlers, and a ps2exe -noConsole build has nowhere to print, so
# a failure can be completely invisible - which is exactly how "+ Save Preset"
# looked. Anything that can fail quietly writes a line here instead.
function Write-AT3Log {
    param([string]$Text)
    try {
        Add-Content -LiteralPath $AT3LogPath -Encoding UTF8 `
            -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + "  " + $Text)
    } catch { }
}

# Startup timing, logged so a slow launch can be diagnosed from the log.
$script:AT3Clock = [System.Diagnostics.Stopwatch]::StartNew()
function Write-AT3Timing {
    param([string]$Step)
    Write-AT3Log ("startup {0,7:N0} ms  {1}" -f $script:AT3Clock.Elapsed.TotalMilliseconds, $Step)
}
# These two live further down in the v1 script, past the block this file
# carries over, so they have to be declared here. Without them the prop and
# spawn appliers silently no-op: Join-Path throws on a null path and the
# error is swallowed by the caller's try/catch.
$PropDir         = Join-Path $AT3Dir "PropPlacements"
$ModToolsDir     = Join-Path $GameRoot "ModTools"

# ---------------------------------------------------------------------------
# Ammo knockback - written straight into the game's own data bundles
# ---------------------------------------------------------------------------
# Unlike every other setting in this launcher, this is NOT an SWSE config
# file: it edits the shipped bundles under data\bundles\ in place. Each ammo
# type has a serialized prefs record there holding m_maxKnockSpeed (how hard
# the blast throws NPCs and objects) and m_maxKnockSpeedPlayer (how hard it
# throws Stranger/Steef). Vanilla leaves the player field at -1 on every
# single ammo type, which means "unset - fall back to the engine default",
# so setting it to a real number is what makes an explosion actually launch
# the player.
#
# The two .csv files next to this script are generated offline:
#   AmmoKnockback.csv - one row per ammo type, with its vanilla values
#   AmmoPatchMap.csv  - every (ammo, file, byte offset) that needs writing,
#                       precomputed so the launcher never has to scan ~100MB
#                       of bundles at startup
# Writes are always in place and the same width, so those offsets stay valid
# permanently. A .knockbak copy of every touched file is made once, the first
# time it is modified, and never overwritten after that - so the pristine
# original is always recoverable even after many edits.
# ---------------------------------------------------------------------------
# A patch site is only safe to touch if the record is still where the map says.
# Verified structurally: the ammo's own hash at the record start, and the bolt
# class tag at +0x14. This is what protects a restored, verified or
# differently-patched game from having bytes written into the middle of
# whatever now occupies that offset.
$script:AmmoTag = 0x000B4265

# Field offsets inside the record, relative to its start. Recovered from the
# exe's reflection tables by ModTools\patchmap.py and constant for this build.
$script:RelKnock  = 164
$script:RelPlayer = 168

# ---------------------------------------------------------------------------
# Install requirements
# ---------------------------------------------------------------------------
# AT3 is a drop-in for a Steam copy of Stranger's Wrath HD that already has
# SWSE. The markers below are all files AT3 itself never creates, so they
# cannot be spuriously satisfied by a previous run:
#   Launcher.exe + bin\stranger.exe  the game
#   bin\steam_api.dll                the Steam build specifically
#   bin\dinput8.dll + SWSEMods\      SWSE's hook DLL and its own config
# SWSE is checked via features.txt / load_order.txt rather than the SWSEMods
# folder alone, because Confirm-AT3ModDir creates SWSEMods\SWSE Console\.
function Test-AT3Install {
    $missing = New-Object System.Collections.Generic.List[string]

    $hasGame = (Test-Path -LiteralPath (Join-Path $GameRoot "Launcher.exe")) -and
               (Test-Path -LiteralPath (Join-Path $GameRoot "bin\stranger.exe"))
    if (-not $hasGame) {
        $missing.Add("Oddworld: Stranger's Wrath HD - Launcher.exe and bin\stranger.exe were not found.")
    }

    $hasSteam = Test-Path -LiteralPath (Join-Path $GameRoot "bin\steam_api.dll")
    if ($hasGame -and -not $hasSteam) {
        $missing.Add("The Steam edition - bin\steam_api.dll is missing. AT3's data offsets are built against the Steam build.")
    }

    $hasSwse = (Test-Path -LiteralPath (Join-Path $GameRoot "bin\dinput8.dll")) -and
               ((Test-Path -LiteralPath (Join-Path $GameRoot "SWSEMods\features.txt")) -or
                (Test-Path -LiteralPath (Join-Path $GameRoot "SWSEMods\load_order.txt")))
    if (-not $hasSwse) {
        $missing.Add("Stranger's Wrath Script Extender (SWSE) - bin\dinput8.dll and SWSEMods\ were not found.")
    }

    return [pscustomobject]@{
        Ok       = ($missing.Count -eq 0)
        HasGame  = $hasGame
        HasSteam = $hasSteam
        HasSwse  = $hasSwse
        Missing  = $missing
    }
}

# ---------------------------------------------------------------------------
# Rebuilding the patch map on a different copy of the game
# ---------------------------------------------------------------------------
# The offsets in AmmoPatchMap.csv are absolute, so they only describe the copy
# of the game they were generated from. Two identical Steam installs match
# byte for byte, but a different depot - or bundles another mod has rewritten -
# will not. Rather than simply refusing, rediscover the records by content:
# scan for the class tag, step back 0x14 to the record start, and keep the
# hit if the hash there is one of the 26 known ammo types.
#
# The scan is native (Latin-1 round-trip so String.IndexOf does the work) and
# covers the 18 bundles that carry ammo records in about half a second. It
# reproduces ModTools\patchmap.py's output exactly, all 468 sites.
function Repair-AT3PatchMap {
    if (-not (Test-Path $AmmoCsvPath)) { return $null }

    $byHash = @{}
    foreach ($a in (Import-Csv -Path $AmmoCsvPath)) { $byHash[[uint32]("0x" + $a.Hash)] = $a.Name }

    # Prefer the files the old map already named; if that is unusable, fall
    # back to walking every bundle in the install.
    $files = @()
    if (Test-Path $AmmoMapPath) {
        $files = @(Import-Csv -Path $AmmoMapPath | ForEach-Object { $_.File } | Sort-Object -Unique |
                   Where-Object { Test-Path -LiteralPath (Join-Path $GameRoot ($_ -replace '/', '\')) })
    }
    if ($files.Count -eq 0) {
        $bundleRoot = Join-Path $GameRoot "data\bundles"
        if (-not (Test-Path $bundleRoot)) { return $null }
        $files = @(Get-ChildItem -Path $bundleRoot -Recurse -File -Include *.smb, *.smh -ErrorAction SilentlyContinue |
                   ForEach-Object { $_.FullName.Substring($GameRoot.Length + 1) -replace '\', '/' })
    }

    $latin1   = [System.Text.Encoding]::GetEncoding(28591)
    $tagStr   = $latin1.GetString([System.BitConverter]::GetBytes([uint32]$script:AmmoTag))
    $rows     = New-Object System.Collections.ArrayList

    foreach ($rel in $files) {
        $full = Join-Path $GameRoot ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $full)) { continue }
        try {
            $d = [System.IO.File]::ReadAllBytes($full)
            $s = $latin1.GetString($d)
        } catch { continue }
        $i = 0
        while ($true) {
            $k = $s.IndexOf($tagStr, $i, [StringComparison]::Ordinal)
            if ($k -lt 0) { break }
            $i = $k + 1
            $rec = $k - 0x14
            if ($rec -lt 0) { continue }
            $h = [System.BitConverter]::ToUInt32($d, $rec)
            if (-not $byHash.ContainsKey($h)) { continue }
            $ao = $rec + $script:RelKnock
            $bo = $rec + $script:RelPlayer
            if ($bo + 4 -gt $d.Length) { continue }
            $ks = [System.BitConverter]::ToSingle($d, $ao)
            $kp = [System.BitConverter]::ToSingle($d, $bo)
            if ([double]::IsNaN($ks) -or $ks -lt -1.0001 -or $ks -gt 100000.0) { continue }
            if ([double]::IsNaN($kp) -or $kp -lt -1.0001 -or $kp -gt 100000.0) { continue }
            [void]$rows.Add([pscustomobject]@{
                Name = $byHash[$h]; File = $rel; Hash = ("{0:X8}" -f $h)
                RecOff = $rec; OffKnock = $ao; OffKnockPlayer = $bo })
        }
    }

    if ($rows.Count -eq 0) { return $null }
    try {
        $rows | Export-Csv -Path $AmmoMapPath -NoTypeInformation -Encoding UTF8
    } catch { return $null }
    return $rows.Count
}


# ---------------------------------------------------------------------------
# Refuse to run outside a Steam + SWSE install of Stranger's Wrath HD. Every
# setting here is either an SWSE config file or a byte written into the Steam
# build's own bundles, so without both there is nothing this launcher can do.
$script:Install = Test-AT3Install
if (-not $script:Install.Ok) {
    $msg = "Stranger: Armed to the Teeth needs to sit inside a Steam copy of " +
           "Oddworld: Stranger's Wrath HD that already has SWSE installed.`r`n`r`n" +
           ($script:Install.Missing -join "`r`n`r`n") +
           "`r`n`r`nLooked in:`r`n$GameRoot`r`n`r`n" +
           "Put the StrangerAT3 folder directly inside the game folder (next to " +
           "Launcher.exe) and run it from there."
    [System.Windows.MessageBox]::Show($msg, "Stranger: Armed to the Teeth",
        [System.Windows.MessageBoxButton]::OK, [System.Windows.MessageBoxImage]::Error) | Out-Null
    exit 1
}

function Test-AT3PatchSite {
    param([System.IO.FileStream]$Stream, [int64]$RecOff, [uint32]$Hash)
    $buf = New-Object byte[] 4
    try {
        [void]$Stream.Seek($RecOff, [System.IO.SeekOrigin]::Begin)
        if ($Stream.Read($buf, 0, 4) -ne 4) { return $false }
        if ([System.BitConverter]::ToUInt32($buf, 0) -ne $Hash) { return $false }
        [void]$Stream.Seek($RecOff + 0x14, [System.IO.SeekOrigin]::Begin)
        if ($Stream.Read($buf, 0, 4) -ne 4) { return $false }
        return ([System.BitConverter]::ToUInt32($buf, 0) -eq $script:AmmoTag)
    } catch { return $false }
}

# Read what the game files ACTUALLY hold right now, rather than trusting the
# CurrentKnock column, which is only a snapshot from when the CSV was built and
# goes stale the moment the game is restored or verified.
# Widening a float32 to double exposes its binary error (0.1f prints as
# 0.100000001490116), so go via the shortest round-trip string - that gives
# back the number a human would have typed.
function Read-AT3Float {
    param([System.IO.FileStream]$Stream, [int64]$Offset)
    $b = New-Object byte[] 4
    [void]$Stream.Seek($Offset, [System.IO.SeekOrigin]::Begin)
    if ($Stream.Read($b, 0, 4) -ne 4) { return $null }
    $f = [System.BitConverter]::ToSingle($b, 0)
    return [double]::Parse($f.ToString("R", [cultureinfo]::InvariantCulture), [cultureinfo]::InvariantCulture)
}

function Get-AT3AmmoCurrent {
    param([switch]$NoRepair)
    $out = @{}
    if (-not (Test-Path $AmmoMapPath)) { return $out }
    $byFile = @{}
    foreach ($m in (Import-Csv -Path $AmmoMapPath)) {
        if ($out.ContainsKey($m.Name)) { continue }
        if (-not $byFile.ContainsKey($m.File)) { $byFile[$m.File] = New-Object System.Collections.ArrayList }
        [void]$byFile[$m.File].Add($m)
    }
    foreach ($rel in $byFile.Keys) {
        $full = Join-Path $GameRoot ($rel -replace '/', '\')
        if (-not (Test-Path $full)) { continue }
        try {
            $fs = [System.IO.File]::Open($full, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        } catch { continue }
        try {
            foreach ($m in $byFile[$rel]) {
                if ($out.ContainsKey($m.Name)) { continue }
                if (-not (Test-AT3PatchSite -Stream $fs -RecOff ([int64]$m.RecOff) -Hash ([uint32]("0x" + $m.Hash)))) { continue }
                $k = Read-AT3Float -Stream $fs -Offset ([int64]$m.OffKnock)
                $p = Read-AT3Float -Stream $fs -Offset ([int64]$m.OffKnockPlayer)
                if ($null -ne $k -and $null -ne $p) {
                    $out[$m.Name] = @{ Knock = $k; KnockPlayer = $p }
                }
            }
        } finally { $fs.Close() }
    }

    # Nothing verified means the map does not describe this copy of the game -
    # a different depot, or bundles some other mod rewrote. Rediscover the
    # records by content and try once more, so dropping AT3 into a fresh
    # install just works instead of silently doing nothing.
    if ($out.Count -eq 0 -and -not $NoRepair) {
        $n = Repair-AT3PatchMap
        if ($n) {
            $script:AmmoMapRepaired = $n
            return (Get-AT3AmmoCurrent -NoRepair)
        }
    }
    return $out
}

function Set-AT3AmmoKnockback {
    param([Parameter(Mandatory)]$Rows)   # Name / Knock / KnockPlayer

    # Rescan before applying. AmmoPatchMap.csv stores ABSOLUTE file offsets, and
    # any bundle rebuild moves every record after the insertion point - so a
    # stored map silently stops matching and every site is skipped. The map is
    # built by live scanning anyway, so rebuilding it here costs little and
    # removes the whole stale-offset failure. (The ammo map covers .smh blockmap
    # files, which at3index.py does not scan, so this path refreshes rather than
    # using the index.)
    [void](Repair-AT3PatchMap)

    if (-not (Test-Path $AmmoMapPath)) { return "No AmmoPatchMap.csv - ammo knockback not applied." }

    $want = @{}
    foreach ($r in $Rows) { $want[[string]$r.Name] = $r }

    # group the patch sites by file so each file is opened exactly once
    $byFile = @{}
    foreach ($m in (Import-Csv -Path $AmmoMapPath)) {
        if (-not $want.ContainsKey($m.Name)) { continue }
        if (-not $byFile.ContainsKey($m.File)) { $byFile[$m.File] = New-Object System.Collections.ArrayList }
        [void]$byFile[$m.File].Add($m)
    }

    $files = 0; $writes = 0; $skipped = 0
    foreach ($rel in $byFile.Keys) {
        $full = Join-Path $GameRoot ($rel -replace '/', '\')
        if (-not (Test-Path $full)) { continue }

        $bak = "$full.knockbak"
        if (-not (Test-Path $bak)) { Copy-Item -LiteralPath $full -Destination $bak -ErrorAction SilentlyContinue }

        try {
            $fs = [System.IO.File]::Open($full, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::Read)
        } catch { continue }
        try {
            foreach ($m in $byFile[$rel]) {
                # Refuse the site if the record is not where the map claims.
                if (-not (Test-AT3PatchSite -Stream $fs -RecOff ([int64]$m.RecOff) -Hash ([uint32]("0x" + $m.Hash)))) {
                    $skipped++
                    continue
                }
                $w = $want[$m.Name]
                foreach ($pair in @(
                    @{ Off = [int64]$m.OffKnock;       Val = [float]$w.Knock }
                    @{ Off = [int64]$m.OffKnockPlayer; Val = [float]$w.KnockPlayer }
                )) {
                    $bytes = [System.BitConverter]::GetBytes([float]$pair.Val)
                    [void]$fs.Seek($pair.Off, [System.IO.SeekOrigin]::Begin)
                    $fs.Write($bytes, 0, 4)
                    $writes++
                }
            }
        } finally { $fs.Close() }
        $files++
    }
    if ($skipped -gt 0) {
        return "Ammo knockback: $writes value(s) across $files file(s); " +
               "SKIPPED $skipped site(s) that did not match the expected record - " +
               "regenerate AmmoPatchMap.csv (ModTools\patchmap.py) if the game was reinstalled or verified."
    }
    return "Ammo knockback written: $writes value(s) across $files bundle file(s)."
}

# ---------------------------------------------------------------------------
# Structural preset support (AT3 Official)
# ---------------------------------------------------------------------------
# A normal preset only restores form fields. The AT3 set also changes values
# INSIDE the game bundles - a weapon record's stats and which character a spawn
# points at. Those are plain byte writes, so the preset carries the offset and
# type with every value and the launcher applies them without needing to know
# anything about record layout.
#
# What it does NOT do is create records. A new character or mesh cannot be
# conjured by a byte write, so the preset lists those as prerequisites and the
# launcher reports if they are absent rather than pretending it can add them.

# A preset may carry whole replacement FILES as well as byte edits. The AT3
# Official set adds new records - a character, a weapon, a bounty entry, a job
# script and an imported mesh - and a record cannot be created by patching
# bytes, so those arrive as complete bundles.
#
# Only the files the preset lists are touched. Each one is backed up once as
# .at3vanilla before the first overwrite, so the original install can always be
# put back.

function Restore-AT3PresetFiles {
    # Preset files are a MATCHED SET: a bundle plus the blockmap that indexes
    # it. Leaving one behind while the other reverts desyncs the region and the
    # level will not load.
    #
    # Nothing restored these before. Unloading a preset left its modified
    # npc_19.smb (+4096 bytes) and npc_23.smb (+73728 bytes) on disk while the
    # blockmap went back to vanilla - so the index described 565248/348160-byte
    # bundles that were no longer those sizes. Region_01 crashed on entry, and
    # ONLY region_01, because only its bundles had been swapped. It stayed
    # broken across every later launch because the ammo stage patches bundles in
    # place and never rebuilds them.
    #
    # Runs before the ammo stage so patches land on whatever ends up in place.
    $restored = 0
    $root = Join-Path $GameRoot "data"
    foreach ($bak in @(Get-ChildItem -LiteralPath $root -Recurse -Filter "*.at3vanilla" -ErrorAction SilentlyContinue)) {
        $target = $bak.FullName.Substring(0, $bak.FullName.Length - ".at3vanilla".Length)
        if (-not (Test-Path $target)) { continue }
        # Never undo an asset consolidation. consolidate_assets.py copies every
        # zone-bundle record into the region's normal bundle so props can be
        # placed in any zone; restoring the .at3vanilla copy would silently
        # throw that away on the next launch. Its own .consolbak is the marker.
        # Any AT3 bundle edit leaves one of these markers. Guarding only on
        # .consolbak was not enough: once consolidation was reverted that
        # marker vanished, and every launch silently restored tgl.smb from
        # .at3vanilla - throwing away the on-demand asset copies before the
        # game even started, which looked exactly like nothing being written.
        $edited = $false
        foreach ($m in @(".consolbak", ".ensurebak", ".assetbak", ".lighttest")) {
            if (Test-Path ($target + $m)) { $edited = $true }
        }
        # The creators leave per-hash backups (<file>.buildbak_<HASH>, .editbak_,
        # .deletebak_). A bundle carrying one holds characters or weapons that
        # were written deliberately - restoring .at3vanilla over it would
        # silently throw them away.
        foreach ($m in @(".buildbak_*", ".editbak_*", ".deletebak_*")) {
            if (@(Get-ChildItem -Path ($target + $m) -ErrorAction SilentlyContinue).Count) { $edited = $true }
        }
        if ($edited) { continue }
        try {
            $a = (Get-FileHash -LiteralPath $target -Algorithm SHA1).Hash
            $b = (Get-FileHash -LiteralPath $bak.FullName -Algorithm SHA1).Hash
            if ($a -ne $b) {
                Copy-Item -LiteralPath $bak.FullName -Destination $target -Force -ErrorAction Stop
                $restored++
            }
        } catch { }
    }
    return $restored
}

function Set-AT3PresetFiles {
    param($Preset)
    if (-not $Preset) { return "" }
    if (-not $Preset.Files) { return "" }

    $sep = [char]92
    $copied = 0; $skipped = 0; $same = 0
    foreach ($f in $Preset.Files) {
        $target = Join-Path $GameRoot ([string]$f.Target).Replace('/', $sep)
        $source = Join-Path $PresetsDir ([string]$f.Source).Replace('/', $sep)
        if (-not (Test-Path $source)) { $skipped++; continue }
        if (-not (Test-Path $target)) { $skipped++; continue }

        # already in place? compare length first, it is cheap
        $tinfo = Get-Item -LiteralPath $target
        if ($tinfo.Length -eq [int64]$f.Bytes) {
            $h = (Get-FileHash -LiteralPath $target -Algorithm SHA1).Hash
            if ($h -eq ([string]$f.Sha1).ToUpper()) { $same++; continue }
        }

        $bak = "$target.at3vanilla"
        if (-not (Test-Path $bak)) {
            Copy-Item -LiteralPath $target -Destination $bak -ErrorAction SilentlyContinue
        }
        try {
            Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
            $copied++
        } catch { $skipped++ }
    }
    $msg = "AT3 files: $copied injected"
    if ($same -gt 0)    { $msg += ", $same already current" }
    if ($skipped -gt 0) { $msg += ", $skipped SKIPPED (missing or locked)" }
    return "$msg."
}

# ---------------------------------------------------------------------------
# Live record lookup - replaces stored file offsets
# ---------------------------------------------------------------------------
# A preset used to store RecOff, the file offset of a record's hash field. Any
# bundle rebuild moves every record after the insertion point, so the stored
# number rots: AT3 Official still names RecOff 449935 for a record whose
# descriptor now begins at 231493, and that entry has silently done nothing
# since. Test-AT3RecordAt catches it and skips, so it fails safe - but it fails.
#
# ModToolst3index.py scans every bundle (2.5 s cold, 0.17 s cached) and writes
# index_cache.json. Offsets are resolved from it at apply time, so they cannot
# be stale. Presets no longer need to carry RecOff at all.
$script:AT3IndexMap = $null

function Update-AT3Index {
    $s = Join-Path $ModToolsDir "at3index.py"
    if (-not (Test-Path $s)) { return $false }
    $r = Invoke-AT3Python -Arguments @($s, "--build") -Activity "Indexing game bundles"
    $script:AT3IndexMap = $null
    return [bool]$r.Ok
}

function Update-AT3Catalogue {
    # GlobalCatalogue.csv / catalogue_<region>.csv drove the Character Studio
    # panel AND apply_spawns.py's safe_donor faction check from a hand-built
    # 2026-08-31 snapshot that nothing refreshed - it did not know about any
    # character built since. Faction is derived from m_species (abs+12,
    # confirmed), which does not depend on the fragile ANC anchor, so this is
    # reliable even for records whose HP column is not.
    $s = Join-Path $ModToolsDir "at3catalogue.py"
    if (-not (Test-Path $s)) { return $false }
    $r = Invoke-AT3Python -Arguments @($s, "--build") -Activity "Rebuilding character catalogue"
    $script:CatalogueFresh = [bool]$r.Ok
    return [bool]$r.Ok
}

# The catalogue is read only by the character pickers, the Character Studio
# and the spawn tools - not at startup. at3catalogue.py skips the rebuild when
# no game file changed (~0.2 s), and this skips even that once per session
# until something writes game files (Apply resets the flag).
$script:CatalogueFresh = $false
function Use-AT3Catalogue {
    if (-not $script:CatalogueFresh) { [void](Update-AT3Catalogue) }
}

$script:AT3IndexHashes = $null   # hash (upper hex) -> count of live copies

function Import-AT3IndexCache {
    if ($null -ne $script:AT3IndexMap) { return }
    $m = @{}
    $hcount = @{}
    $p = Join-Path $AT3Dir "index_cache.json"
    if (Test-Path $p) {
        try {
            $j = Get-Content -LiteralPath $p -Raw | ConvertFrom-Json
            foreach ($f in $j.files.PSObject.Properties) {
                foreach ($rec in $f.Value.records) {
                    $h = [string]$rec[0]
                    $m[($h + "|" + $f.Name)] = [int64]$rec[3]
                    if ($hcount.ContainsKey($h)) { $hcount[$h] = $hcount[$h] + 1 } else { $hcount[$h] = 1 }
                }
            }
        } catch { }
    }
    $script:AT3IndexMap = $m
    $script:AT3IndexHashes = $hcount
}

function Resolve-AT3RecOff {
    param([string]$Hash, [string]$RelFile)
    Import-AT3IndexCache
    $k = $Hash.ToUpper() + "|" + $RelFile
    if ($script:AT3IndexMap.ContainsKey($k)) { return $script:AT3IndexMap[$k] }
    return $null
}

function Test-AT3HashResident {
    # Is this hash present ANYWHERE right now, according to the live index -
    # not according to what a preset's Requires row claims about itself.
    param([string]$Hash)
    Import-AT3IndexCache
    $h = $Hash.ToUpper()
    return ($script:AT3IndexHashes.ContainsKey($h) -and $script:AT3IndexHashes[$h] -gt 0)
}

function Test-AT3RecordAt {
    param([System.IO.FileStream]$Stream, [int64]$RecOff, [uint32]$Hash)
    $buf = New-Object byte[] 4
    try {
        [void]$Stream.Seek($RecOff, [System.IO.SeekOrigin]::Begin)
        if ($Stream.Read($buf, 0, 4) -ne 4) { return $false }
        return ([System.BitConverter]::ToUInt32($buf, 0) -eq $Hash)
    } catch { return $false }
}

function Test-AT3Requires {
    # Whether a preset's declared requirements ACTUALLY exist on disk right
    # now, checked against the live index rather than against the preset's own
    # say-so. The old check only asked "did the preset author fill in a
    # Bundles list" - a property of the JSON, unrelated to the game files - so
    # it could never report a real miss. A record that a launcher rebuild
    # dropped (as happened to jailbreak_blisterz's boss job and weapon
    # geometry) would have sailed through it silently.
    param($Preset)
    $missing = @()
    if ($Preset.Requires) {
        Import-AT3IndexCache
        foreach ($r in $Preset.Requires) {
            $hash = [string]$r.Hash
            if ($hash) {
                if (-not (Test-AT3HashResident -Hash $hash)) {
                    $missing += ("{0} ({1}) - not found by the current file scan" -f [string]$r.What, $hash)
                }
            } elseif (-not $r.Bundles -or @($r.Bundles).Count -eq 0) {
                $missing += [string]$r.What
            }
        }
    }
    return $missing
}

# CUSTOM CHARACTERS ARE BUILT, NOT SHIPPED.
#
# A preset's Recipes are JSON files describing how to make a new character out
# of records the player already has: clone this vanilla record, patch these few
# bytes, copy that mesh across from another bundle. jailbreak_blisterz is 147
# bytes of patch data and six instructions.
#
# The alternative was shipping the modified bundles - 10.26 MB of Oddworld's own
# data to deliver 4.7 KB of ours - which is both wrong to redistribute and
# pointless when every record is a clone of something already on disk.
#
# Runs BEFORE the spawn stage: the level references the new character hash, so
# it has to exist by the time spawns are written.
function Set-AT3PresetRecipes {
    param($Preset)
    if (-not $Preset) { return "" }
    if ($null -eq $Preset.PSObject.Properties["Recipes"]) { return "" }
    $script2 = Join-Path $ModToolsDir "character_recipe.py"
    if (-not (Test-Path $script2)) { return "Recipes: character_recipe.py missing." }
    $msgs = @()
    foreach ($r in @($Preset.Recipes)) {
        $rp = Join-Path $PresetsDir ([string]$Preset.Name)
        $full = Join-Path $rp ([string]$r)
        if (-not (Test-Path $full)) { $msgs += "Recipe not found: $r"; continue }
        $res = Invoke-AT3Python -Arguments @($script2, "install", $full, "--quiet")
        if (-not $res.Ok) { $msgs += "Recipe[$r]: FAILED - $($res.Output)"; continue }
        $line = @([string[]]($res.Output -split "`r?`n") | Where-Object { $_ -match "records," -or $_ -match "already installed" })
        if ($line.Count -gt 0) { $msgs += "Recipe[$r]: " + ($line[0].Trim()) }
        else { $msgs += "Recipe[$r]: installed." }
    }
    if ($msgs.Count -eq 0) { return "" }
    return ($msgs -join "  ")
}

function Set-AT3PresetMods {
    param($Preset)
    if (-not $Preset) { return "" }

    $writes = 0; $skipped = 0; $spawns = 0
    $sep = [char]92

    if ($Preset.Weapons) {
        foreach ($w in $Preset.Weapons) {
            $full = Join-Path $GameRoot ([string]$w.File).Replace('/', $sep)
            if (-not (Test-Path $full)) { $skipped++; continue }
            $bak = "$full.presetbak"
            if (-not (Test-Path $bak)) {
                Copy-Item -LiteralPath $full -Destination $bak -ErrorAction SilentlyContinue
            }
            try {
                $fs = [System.IO.File]::Open($full, [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::Read)
            } catch { $skipped++; continue }
            try {
                # Resolve the offset from the live index. Fall back to the
                # preset's stored RecOff only if the index has no answer, so
                # old presets still work.
                $recOff = Resolve-AT3RecOff -Hash ([string]$w.Hash) -RelFile ([string]$w.File)
                if ($null -eq $recOff) { $recOff = [int64]$w.RecOff }
                if (-not (Test-AT3RecordAt -Stream $fs -RecOff ([int64]$recOff) -Hash ([uint32]("0x" + $w.Hash)))) {
                    # the record moved - refuse rather than write into whatever
                    # is there now, same policy as the ammo patch map
                    $skipped++
                } else {
                    foreach ($f in $w.Fields) {
                        if ([string]$f.Kind -eq "i") {
                            $bytes = [System.BitConverter]::GetBytes([int]$f.Value)
                        } else {
                            $bytes = [System.BitConverter]::GetBytes([float]$f.Value)
                        }
                        [void]$fs.Seek(([int64]$recOff + [int64]$f.Off), [System.IO.SeekOrigin]::Begin)
                        $fs.Write($bytes, 0, 4)
                        $writes++
                    }
                }
            } finally { $fs.Close() }
        }
    }

    if ($Preset.Spawns) {
        foreach ($s in $Preset.Spawns) {
            $full = Join-Path $GameRoot ([string]$s.File).Replace('/', $sep)
            if (-not (Test-Path $full)) { $skipped++; continue }
            $bak = "$full.presetbak"
            if (-not (Test-Path $bak)) {
                Copy-Item -LiteralPath $full -Destination $bak -ErrorAction SilentlyContinue
            }
            try {
                $fs = [System.IO.File]::Open($full, [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::Read)
            } catch { $skipped++; continue }
            try {
                $bytes = [System.BitConverter]::GetBytes([uint32]("0x" + $s.Hash))
                [void]$fs.Seek([int64]$s.Offset, [System.IO.SeekOrigin]::Begin)
                $fs.Write($bytes, 0, 4)
                $spawns++
            } finally { $fs.Close() }
        }
    }

    $jobs = 0
    if ($Preset.Jobs) {
        # A spawn's job record is what gives it a boss health bar. It is stored
        # twice - at -36 from the type hash (+92) and again at RECORD LENGTH - 6,
        # which is +67 from the type hash only on a 201-byte spawn - so both
        # copies must be written or the two disagree. The preset's Writes still
        # say 67; the real offset is read from the record below.
        foreach ($j in $Preset.Jobs) {
            $full = Join-Path $GameRoot ([string]$j.File).Replace('/', $sep)
            if (-not (Test-Path $full)) { $skipped++; continue }
            $bak = "$full.presetbak"
            if (-not (Test-Path $bak)) {
                Copy-Item -LiteralPath $full -Destination $bak -ErrorAction SilentlyContinue
            }
            try {
                $fs = [System.IO.File]::Open($full, [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::Read)
            } catch { $skipped++; continue }
            try {
                $bytes = [System.BitConverter]::GetBytes([uint32]("0x" + $j.Hash))
                # The record starts 128 bytes before the type hash; its length is
                # its next pointer minus its start. Only a record that really is
                # one (the level's record token at its start) moves the +67
                # write - anything else keeps the preset's stored offset.
                $mirror = $null
                try {
                    $start = [int64]$j.Offset - 128
                    $hdr = New-Object byte[] 8
                    [void]$fs.Seek($start, [System.IO.SeekOrigin]::Begin)
                    if ($fs.Read($hdr, 0, 8) -eq 8 -and [System.BitConverter]::ToUInt32($hdr, 0) -eq 0x7A60600D) {
                        $len = [int64][System.BitConverter]::ToUInt32($hdr, 4) - $start
                        if ($len -ge 132 -and $len -le 4096) { $mirror = $len - 6 - 128 }
                    }
                } catch { $mirror = $null }
                foreach ($w in $j.Writes) {
                    $at = [int64]$w
                    if ($at -eq 67 -and $null -ne $mirror) { $at = $mirror }
                    [void]$fs.Seek(([int64]$j.Offset + $at), [System.IO.SeekOrigin]::Begin)
                    $fs.Write($bytes, 0, 4)
                }
                $jobs++
            } finally { $fs.Close() }
        }
    }

    $msg = "AT3 preset: $writes weapon value(s), $spawns spawn(s), $jobs job(s) written."
    if ($skipped -gt 0) {
        $msg += " SKIPPED $skipped site(s) that did not match - the bundles may have been rebuilt or restored."
    }
    $missing = Test-AT3Requires -Preset $Preset
    if ($missing.Count -gt 0) {
        $msg += " MISSING: " + ($missing -join "; ") + " - these are added by ModTools, not by the launcher."
    }
    return $msg
}

# ---------------------------------------------------------------------------
# SWSE remote console mailbox
# ---------------------------------------------------------------------------
$script:Seq = 0

function Send-SWSECommand {
    param(
        [Parameter(Mandatory)][string]$Command,
        [int]$TimeoutSeconds = 15
    )
    $script:Seq++
    $seq = $script:Seq
    try {
        Set-Content -Path $RemoteIn -Value "$seq`n$Command`n" -Encoding ASCII -NoNewline
    } catch {
        return $null
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        if (Test-Path $RemoteOut) {
            try {
                $content = Get-Content -Path $RemoteOut -Raw -ErrorAction SilentlyContinue
            } catch { $content = $null }
            # The game writes CRLF line endings, not bare LF - match either.
            if ($content -and $content -match "^$seq\r?\n" -and $content -match '<<END>>') {
                return $content
            }
        }
    }
    return $null
}

# ---------------------------------------------------------------------------
# aiprefs.txt - universal weapon behavior, applied to every enemy
# ---------------------------------------------------------------------------
# Rewrites only the `active =` line and a managed [Racketeer] section, so any
# other profiles already in the file (keen/relentless/obvious, or the user's
# own) are left untouched.
#
# $Reload and $Accuracy are the LAUNCHER's user-facing "better for the enemy"
# multipliers: higher = faster reload / more accurate, matching fire rate's
# direction so all three behave the same way. aiprefs.txt's own `reload` and
# `accuracy` keys mean the opposite there (a TIME and a SPREAD WIDTH, lower =
# better) - that inversion is translated here, once, so nobody typing "5"
# into this window has to know the file works backwards.
#
# $MissTime is NOT a multiplier like the other three, and is not inverted
# either - it's an ABSOLUTE value in the same units SWSE writes directly to
# the field (shipped ~10 on almost every character, confirmed live: pushed to
# 100000 it makes enemies almost unable to land a hit). It also isn't a
# "better/worse for the enemy" knob the way the others are - a bigger
# deliberate-miss window makes them LESS dangerous - so there's no direction
# to make consistent with fire rate/reload/accuracy anyway. Default 10 = vanilla
# for nearly every weapon (one known outlier ships at ~500 instead).
# Restoring a backup of the base game wipes SWSEMods along with everything
# else. Writing a pref into a missing directory throws, so recreate it rather
# than failing the launch - SWSE reads these files, it does not create them.
function Confirm-AT3ModDir {
    if (Test-Path -LiteralPath $ModDir) { return $true }
    try {
        New-Item -ItemType Directory -Path $ModDir -Force -ErrorAction Stop | Out-Null
        return $true
    } catch { return $false }
}

function Set-AT3AiProfile {
    param([double]$FireRate = 1.0, [double]$Reload = 1.0, [double]$Accuracy = 1.0, [double]$MissTime = 10.0)

    if (-not (Confirm-AT3ModDir)) { return }

    $reloadTimeMultiplier   = if ($Reload -gt 0)   { 1.0 / $Reload }   else { 1.0 }
    $accuracyWidthMultiplier = if ($Accuracy -gt 0) { 1.0 / $Accuracy } else { 1.0 }

    $useOff = ($FireRate -eq 1.0 -and $Reload -eq 1.0 -and $Accuracy -eq 1.0 -and $MissTime -eq 10.0)
    $activeLine = if ($useOff) { "active = off" } else { "active = Racketeer" }

    if (Test-Path $AiPrefsPath) {
        $lines = @(Get-Content -Path $AiPrefsPath)
    } else {
        $lines = @("# Stranger: Armed to the Teeth - managed aiprefs.txt", "active = off")
    }

    $out = New-Object System.Collections.Generic.List[string]
    $seenActive = $false
    $inSection = $false
    $skippingManagedSection = $false

    foreach ($line in $lines) {
        $trimmed = $line.Trim()

        if ($trimmed -match '^\[(.+)\]$') {
            $skippingManagedSection = ($Matches[1] -eq 'Racketeer')
            $inSection = $true
            if (-not $skippingManagedSection) { $out.Add($line) }
            continue
        }

        if ($skippingManagedSection) { continue }

        if (-not $inSection -and -not $seenActive -and $trimmed -match '^active\s*=') {
            $out.Add($activeLine)
            $seenActive = $true
            continue
        }

        $out.Add($line)
    }

    if (-not $seenActive) { $out.Insert(0, $activeLine) }

    $out.Add("")
    $out.Add("[Racketeer]")
    $out.Add(("firerate = {0:0.0##}" -f $FireRate))
    $out.Add(("reload   = {0:0.0##}" -f $reloadTimeMultiplier))
    $out.Add(("accuracy = {0:0.0##}" -f $accuracyWidthMultiplier))
    $out.Add(("misstime = {0:0.0##}" -f $MissTime))

    Set-Content -Path $AiPrefsPath -Value $out -Encoding ASCII
}

# ---------------------------------------------------------------------------
# playerprefs.txt - Stranger's HP/Stamina. SWSE itself (playertune.cpp)
# watches for a live player object and applies this once, a few seconds
# after it appears, so it lands after the game's own difficulty-based init
# instead of racing it - no polling from here needed at all.
# ---------------------------------------------------------------------------
function Set-AT3PlayerPrefs {
    param([Nullable[double]]$Health, [Nullable[double]]$Stamina)

    if (-not (Confirm-AT3ModDir)) { return }

    $out = @(
        "# Stranger: Armed to the Teeth - managed playerprefs.txt"
        "# Applied automatically by SWSE a few seconds after you start a game."
        ""
        "health  = $(if ($null -ne $Health) { '{0:0.0##}' -f $Health } else { '' })"
        "stamina = $(if ($null -ne $Stamina) { '{0:0.0##}' -f $Stamina } else { '' })"
    )
    Set-Content -Path $PlayerPrefsPath -Value $out -Encoding ASCII
}

# ---------------------------------------------------------------------------
# Input parsing helpers
# ---------------------------------------------------------------------------
function Get-OptionalDouble([string]$Text) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $val = 0.0
    if ([double]::TryParse($Text, [ref]$val)) { return $val }
    return $null
}

function Get-MultiplierDouble([string]$Text, [double]$Default = 1.0) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $Default }
    $val = 0.0
    if ([double]::TryParse($Text, [ref]$val)) { return $val }
    return $Default
}

# ===========================================================================
# AT3 v2 - data model
# ===========================================================================

$AmmoNamesPath = Join-Path $AT3Dir "AmmoNames.csv"

# name -> @{Display; Enemies; AoE; Order}
$script:AmmoMeta = @{}
$script:AmmoOrder = @()
if (Test-Path $AmmoNamesPath) {
    foreach ($r in @(Import-Csv -LiteralPath $AmmoNamesPath)) {
        $n = ([string]$r.Name).ToLower()
        $script:AmmoMeta[$n] = @{
            Display = [string]$r.Display
            Enemies = ([string]$r.Enemies -eq "1")
            AoE     = ([string]$r.AoE -eq "1")
            Order   = [int]$r.Order
        }
        $script:AmmoOrder += $n
    }
}

# Current and vanilla knock values, keyed by internal ammo name. Current comes
# from the LIVE bundles - the CSV's snapshot goes stale the moment the game is
# verified or restored behind our back.
$script:AmmoCur = @{}
$script:AmmoVan = @{}

function Initialize-AT3Ammo {
    $script:AmmoCur = @{}
    $script:AmmoVan = @{}
    if (-not (Test-Path $AmmoCsvPath)) { return 0 }
    $live = Get-AT3AmmoCurrent
    foreach ($a in @(Import-Csv -LiteralPath $AmmoCsvPath)) {
        $n = ([string]$a.Name).ToLower()
        $script:AmmoVan[$n] = @{ Knock = [double]$a.VanillaKnock; KnockPlayer = [double]$a.VanillaKnockPlayer }
        if ($live.ContainsKey($n)) {
            $script:AmmoCur[$n] = @{ Knock = [double]$live[$n].Knock; KnockPlayer = [double]$live[$n].KnockPlayer }
        } else {
            $script:AmmoCur[$n] = @{ Knock = [double]$a.CurrentKnock; KnockPlayer = [double]$a.CurrentKnockPlayer }
        }
    }
    return $script:AmmoCur.Count
}

function Get-AT3AmmoDisplay {
    param($Name)
    $n = ([string]$Name).ToLower()
    if ($script:AmmoMeta.ContainsKey($n)) { return $script:AmmoMeta[$n].Display }
    return $Name
}

# Rows in the shape Set-AT3AmmoKnockback expects, straight from the model.
function Get-AT3AmmoRows {
    $out = @()
    foreach ($n in $script:AmmoCur.Keys) {
        $out += [pscustomobject]@{ Name = $n
                                   Knock = [double]$script:AmmoCur[$n].Knock
                                   KnockPlayer = [double]$script:AmmoCur[$n].KnockPlayer }
    }
    return $out
}

# ---------------------------------------------------------------------------
# RESTORE VANILLA
#
# Puts back only the backup copies this launcher made on THIS machine. AT3
# ships no game data of its own, so nothing here can redistribute Stranger's
# Wrath files. For each modified file we take the OLDEST surviving backup,
# which is the one closest to the original install.
# ---------------------------------------------------------------------------
$script:AT3BackupSuffixes = @(
    ".bak", ".knockbak", ".at3vanilla", ".at3bak", ".attbak", ".rbbak",
    ".injbak", ".envbak", ".propbak", ".propsbak", ".spawnbak", ".spawnsbak",
    ".charbak", ".jobbak", ".tagbak", ".presetbak", ".bmbak", ".bmaddbak",
    ".fixbak", ".geobak", ".meshbak", ".hatbak", ".sitebak",
    # Added 2026-09-05. These four are written by the ModTools scripts but were
    # absent here, so Restore Vanilla silently skipped any file whose ONLY
    # backup used one of them - which is every tgl that had geometry imported
    # into it on a clean install.
    ".ensurebak", ".assetbak", ".consolbak", ".syncbak"
)

function Restore-AT3Vanilla {
    $dataRoot = Join-Path $GameRoot "data"
    if (-not (Test-Path $dataRoot)) { return "Restore: no data folder found." }

    # target file -> oldest backup that exists for it
    $best = @{}
    foreach ($sfx in $script:AT3BackupSuffixes) {
        foreach ($b in @(Get-ChildItem -LiteralPath $dataRoot -Recurse -Filter "*$sfx" -File -ErrorAction SilentlyContinue)) {
            if ($b.Name -notlike "*$sfx") { continue }
            $target = $b.FullName.Substring(0, $b.FullName.Length - $sfx.Length)
            if (-not (Test-Path -LiteralPath $target)) { continue }
            if ((-not $best.ContainsKey($target)) -or ($b.LastWriteTime -lt $best[$target].LastWriteTime)) {
                $best[$target] = $b
            }
        }
    }

    $restored = 0; $already = 0; $failed = 0
    foreach ($target in $best.Keys) {
        $src = $best[$target]
        try {
            $a = (Get-FileHash -LiteralPath $target -Algorithm SHA1).Hash
            $c = (Get-FileHash -LiteralPath $src.FullName -Algorithm SHA1).Hash
            if ($a -eq $c) { $already++; continue }
            Copy-Item -LiteralPath $src.FullName -Destination $target -Force -ErrorAction Stop
            $restored++
        } catch { $failed++ }
    }

    # EVERY EDITOR INPUT GOES BACK TO NEUTRAL, NOT JUST THE GAMEPLAY ONES.
    #
    # Restoring used to clear only the spawn CSVs and the gameplay rules, which
    # left the randomizer still enabled, prop placements still queued and
    # ambience edits still pending - so the very next APPLY CHANGES undid the
    # restore for everything except gameplay. If the button says it undoes every
    # change AT3 has made, it has to mean all of them.
    $cleared = 0
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter "spawns_*.csv" -ErrorAction SilentlyContinue)) {
        # header must match what the Spawns Editor writes, Donor/Tag included
        Set-Content -LiteralPath $f.FullName -Value "Action,Slot,Hash,X,Y,Z,Yaw,Donor,Tag" -Encoding utf8
        $cleared++
    }
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter "props_*.csv" -ErrorAction SilentlyContinue)) {
        Set-Content -LiteralPath $f.FullName -Value "Prop,X,Y,Z,Yaw,Pitch,Roll,Scale,Tint,Zone" -Encoding utf8
        $cleared++
    }
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter "env_edits_*.csv" -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
        $cleared++
    }
    foreach ($f in @(Get-ChildItem -LiteralPath $RegionDataDir -Filter "env_edits_*.csv" -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
        $cleared++
    }

    # The randomizer is a setting, not a file edit, so nothing else was ever
    # going to switch it off.
    $rnd = @("Enabled,0", "RosterHostiles,1", "RosterFriendlies,0", "RosterBosses,0",
             "RosterDeathray,0", "RosterTiny,0", "IntoHostile,1", "IntoFriendly,0",
             "IntoBosses,0", "IntoProgression,0", "Seed,")
    Set-Content -LiteralPath $RandomizerConfigPath -Encoding utf8 `
        -Value (@("Key,Value") + $rnd)

    # In-memory panels, so the windows show vanilla rather than the old edits.
    $script:AmbienceTables = @{}
    $script:LoadedPreset = $null
    $script:LoadedPresetPath = $null

    Set-AT3PlayerPrefs -Health $null -Stamina $null
    Set-AT3AiProfile -FireRate 1.0 -Reload 1.0 -Accuracy 1.0 -MissTime 10.0
    [void](Initialize-AT3Ammo)
    [void](Initialize-AT3GlobalRules)

    $msg = "Restored $restored file(s) from local backups"
    if ($already -gt 0) { $msg += ", $already already vanilla" }
    if ($failed -gt 0)  { $msg += ", $failed FAILED (file in use?)" }
    $msg += ". Cleared $cleared editor file(s); randomizer off; preset unloaded."
    return $msg
}

# ---------------------------------------------------------------------------
# Startup diagnostics for the feedback box
# ---------------------------------------------------------------------------
function Get-AT3Startup {
    # Build stamp first, so it is obvious at a glance which executable is
    # actually running - three .exe files live in this folder and the one with
    # the familiar name is the OLD launcher.
    $lines = @()
    $exeName = "Stranger_AT3_v2.ps1"
    try { $exeName = Split-Path -Leaf ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName) } catch { }
    $built = "?"
    try { $built = (Get-Item -LiteralPath ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)).LastWriteTime.ToString("yyyy-MM-dd HH:mm") } catch { }
    $lines += "AT3 v$($script:AT3Version)  -  build $built  -  running: $exeName"
    $lines += ""
    $bundles = Join-Path $GameRoot "data\bundles"
    if (Test-Path $bundles) {
        $regions = @(Get-ChildItem -LiteralPath $bundles -Directory -ErrorAction SilentlyContinue).Count
        $lines += "[OK]   Game files found - $regions region(s) readable at $GameRoot"
    } else {
        $lines += "[FAIL] Cannot find Stranger's Wrath data - expected $bundles"
    }

    # Scan the actual bundles now, every launch - AT3 used to know "vanilla"
    # for 4 of 1148 bundles and stored file offsets that rotted the moment a
    # bundle was rebuilt. This is what replaces that: read the files, not a
    # record of how they differ from a install nobody's machine still has.
    $script:AT3IndexMap = $null
    $t0 = Get-Date
    Write-AT3Timing "diagnostics begin"
    $ok = Update-AT3Index
    Write-AT3Timing "file index"
    $ms = [int]((Get-Date) - $t0).TotalMilliseconds
    if ($ok) {
        Import-AT3IndexCache
        $lines += "[OK]   File index built - $($script:AT3IndexHashes.Count) distinct record(s) known ($ms ms)"
    } else {
        $lines += "[WARN] File index did not build - presets will fall back to stored offsets"
    }
    # The character catalogue is NOT built here any more - it is refreshed on
    # first use (Use-AT3Catalogue). Most sessions never open a character tool.

    if (Test-Path -LiteralPath (Join-Path $AT3Dir "python\python.exe")) {
        $lines += "[OK]   Python runtime bundled (StrangerAT3\python)"
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        $lines += "[WARN] Bundled Python runtime missing - using the system Python"
    } else {
        $lines += "[FAIL] No Python runtime - StrangerAT3\python is missing; reinstall AT3"
    }

    $swse = Join-Path $GameRoot "bin\dinput8.dll"
    if (Test-Path $swse) {
        $lines += "[OK]   SWSE detected (bin\dinput8.dll)"
    } else {
        $lines += "[WARN] SWSE not detected - player and AI tuning will not apply"
    }

    Initialize-AT3GlobalRules
    Write-AT3Timing "global rules"
    $n = Initialize-AT3Ammo
    Write-AT3Timing "ammo"
    if ($n -gt 0) { $lines += "[OK]   Ammo config loaded - $n ammo types" }
    else          { $lines += "[WARN] AmmoKnockback.csv missing - ammo tab will be empty" }

    $presets = @(Get-PresetFiles).Count
    $lines += "[OK]   $presets preset(s) available"

    return ($lines -join "`r`n")
}

# ===========================================================================
# AT3 v2 - appliers (CSV driven; no grid required)
#
# The old launcher read placements straight off its DataGrids, so nothing
# applied unless the relevant tab had been opened. These take the CSVs as the
# source of truth instead, which is what the editors write to anyway.
# ===========================================================================

# ===========================================================================
# Progress window - what replaces the console flashes
#
# Users reported the console windows as "frightening and synonymous with
# malware", and they were right to: a GUI app that pops black terminals is
# indistinguishable from a dropper. The consoles are gone (see
# Invoke-AT3Python below); this is what stands in their place for the
# operations slow enough to need feedback.
#
# It is shown from the UI thread while a blocking read loop runs, so nothing
# repaints unless the dispatcher is pumped by hand after each update. That is
# what Step-AT3Dispatcher does - the WPF equivalent of DoEvents.
# ===========================================================================
function Step-AT3Dispatcher {
    try {
        [void][System.Windows.Threading.Dispatcher]::CurrentDispatcher.Invoke(
            [System.Windows.Threading.DispatcherPriority]::Background, [System.Action] {})
    } catch { }
}

function Show-AT3Progress {
    param([string]$Activity = "Working")
    try {
        $w = New-Object System.Windows.Window
        $w.Title = "Stranger: Armed to the Teeth"
        $w.Width = 540
        $w.Height = 165
        $w.WindowStartupLocation = [System.Windows.WindowStartupLocation]::CenterScreen
        $w.ResizeMode = [System.Windows.ResizeMode]::NoResize
        $w.WindowStyle = [System.Windows.WindowStyle]::ToolWindow
        $w.ShowInTaskbar = $false
        $w.Topmost = $true
        $w.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#1B1410")
        try { Set-AT3Theme -Target $w } catch { }

        $sp = New-Object System.Windows.Controls.StackPanel
        $sp.Margin = New-Object System.Windows.Thickness 18,16,18,16

        $ttl = New-Object System.Windows.Controls.TextBlock
        $ttl.Text = $Activity
        $ttl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
        $ttl.FontSize = 14
        $ttl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
        $ttl.Margin = New-Object System.Windows.Thickness 0,0,0,10
        [void]$sp.Children.Add($ttl)

        $bar = New-Object System.Windows.Controls.ProgressBar
        $bar.IsIndeterminate = $true
        $bar.Height = 8
        $bar.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#120D0A")
        $bar.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A6D3B")
        $bar.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#4A3524")
        $bar.Margin = New-Object System.Windows.Thickness 0,0,0,10
        [void]$sp.Children.Add($bar)

        $ln = New-Object System.Windows.Controls.TextBlock
        $ln.Text = "starting..."
        $ln.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
        $ln.FontSize = 11
        $ln.TextTrimming = [System.Windows.TextTrimming]::CharacterEllipsis
        $ln.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
        [void]$sp.Children.Add($ln)

        $w.Content = $sp
        $w.Show()
        Step-AT3Dispatcher
        return @{ Window = $w; Line = $ln; Title = $ttl }
    } catch {
        Write-AT3Log ("progress window failed: " + $_.Exception.Message)
        return $null
    }
}

function Update-AT3Progress {
    param($Progress, [string]$Text)
    if (-not $Progress) { return }
    try {
        $t = $Text.Trim()
        if ($t) { $Progress.Line.Text = $t }
        Step-AT3Dispatcher
    } catch { }
}

function Close-AT3Progress {
    param($Progress)
    if (-not $Progress) { return }
    try { $Progress.Window.Close() } catch { }
    Step-AT3Dispatcher
}

# ===========================================================================
# Run one ModTools script.
#
# NO CONSOLE WINDOW, EVER. This used Start-Process -NoNewWindow, and that flag
# does NOT do what its name suggests: it suppresses a new *shell* window, not
# the console allocation. The launcher is compiled -noConsole, so it is a GUI
# process with no console of its own - when it starts python.exe (a console
# subsystem binary) Windows therefore allocates a brand new console and shows
# it. Every index rebuild, catalogue refresh and Apply Changes flashed one up,
# starting with the very first thing that happens at startup.
#
# CreateNoWindow on a raw ProcessStartInfo is the flag that actually
# suppresses it, and it only works together with UseShellExecute = $false.
#
# stdout is read line by line so a caller can show progress. stderr is read
# ASYNCHRONOUSLY - if it were read after stdout, a child that filled the ~4KB
# stderr pipe buffer would block forever while we sat blocked on stdout, and
# a deadlocked GUI is worse than the console window this replaces.
# ===========================================================================
function Invoke-AT3Python {
    param([string[]]$Arguments, [string]$Activity)
    $exe = $null
    $pre = @()
    # AT3 ships its own Python (StrangerAT3\python, built by build_runtime.py)
    # so players never install one. A system Python is only the fallback for a
    # development checkout that has not built the runtime.
    $bundled = Join-Path $AT3Dir "python\python.exe"
    $c = $null
    if (Test-Path -LiteralPath $bundled) { $exe = $bundled }
    else { $c = Get-Command python.exe -ErrorAction SilentlyContinue }
    if ($exe) { }
    elseif ($c) {
        $exe = $c.Source
    } else {
        $c = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($c) { $exe = $c.Source; $pre = @("-3") }
    }
    if (-not $exe) { return @{ Ok = $false; Output = "AT3's Python runtime (StrangerAT3\python) is missing - reinstall AT3." } }

    # Quote every argument that contains a space. The game folder is
    # "Stranger's Wrath", so an unquoted script path splits at the space and
    # python is handed "...\common\Stranger's" as the file to run.
    $argLine = (($pre + $Arguments) | ForEach-Object {
        $s = [string]$_
        if ($s -match '\s') { '"' + $s + '"' } else { $s }
    }) -join ' '

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $exe
    $psi.Arguments              = $argLine
    $psi.WorkingDirectory       = $GameRoot
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true

    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    $sbOut = New-Object System.Text.StringBuilder
    $prog = $null
    try {
        if ($Activity) { $prog = Show-AT3Progress -Activity $Activity }
        [void]$p.Start()

        # ReadToEndAsync, NOT Register-ObjectEvent. A PowerShell -Action
        # handler is dispatched on the engine's own event queue, and that queue
        # is never pumped while this function sits blocked in ReadLine() and
        # WaitForExit() - so the handler simply never ran and every byte of
        # stderr was silently dropped. This hands the read to the .NET thread
        # pool instead, which needs no PowerShell machinery at all, and drains
        # the pipe continuously so it can never fill and deadlock.
        $errTask = $p.StandardError.ReadToEndAsync()

        while ($null -ne ($line = $p.StandardOutput.ReadLine())) {
            [void]$sbOut.AppendLine($line)
            if ($prog) { Update-AT3Progress -Progress $prog -Text $line }
        }
        $p.WaitForExit()
        $err = ""
        try { $err = [string]$errTask.Result } catch { }
        return @{ Ok = ($p.ExitCode -eq 0); Output = ($sbOut.ToString() + $err) }
    } catch {
        return @{ Ok = $false; Output = $_.Exception.Message }
    } finally {
        Close-AT3Progress -Progress $prog
        try { $p.Dispose() } catch { }
    }
}

# Backed by a DataTable for the same reason as the ammo tab: WPF's DataGrid

function Get-AT3PropCsv  { param($Region) return (Join-Path $PropDir "props_$Region.csv") }
function Get-AT3SpawnCsv { param($Region) return (Join-Path $PropDir "spawns_$Region.csv") }

# If the loaded preset ships a region's .lvl, everything else has to be layered
# ON TOP of it or whichever runs second erases the other.
function Get-AT3PresetLevel {
    param($Region)
    if (-not ($script:LoadedPreset -and $script:LoadedPreset.Files)) { return $null }
    $sep = [string][char]92
    $want = "data/bundles/region_$Region/lm_level_$Region.lvl"
    foreach ($f in $script:LoadedPreset.Files) {
        if (([string]$f.Target) -ne $want) { continue }
        $cand = Join-Path $PresetsDir ([string]$f.Source).Replace('/', $sep)
        if (Test-Path $cand) { return $cand }
    }
    return $null
}

function Set-AT3PropsAll {
    $propScript = Join-Path $ModToolsDir "place_props.py"
    # Which regions this run actually rewrote. The spawn stage layers onto the
    # prop stage's output, but ONLY for regions the prop stage touched - see the
    # comment on $stage in Set-AT3SpawnsAll for what goes wrong otherwise.
    $script:AT3PropsWrote = @{}
    if (-not (Test-Path $propScript)) { return "" }
    $msgs = @()
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter "props_*.csv" -ErrorAction SilentlyContinue)) {
        $region = $f.BaseName -replace "^props_", ""
        $n = @(Import-Csv -LiteralPath $f.FullName -ErrorAction SilentlyContinue).Count
        if ($n -eq 0) { continue }
        $argv = @($propScript, $region, "--csv", $f.FullName)
        $base = Get-AT3PresetLevel -Region $region
        if ($base) { $argv += @("--base", $base) }
        $res = Invoke-AT3Python -Arguments $argv
        if (-not $res.Ok) { $msgs += "Props[$region]: FAILED - $($res.Output)"; continue }
        # Not every props_*.csv names a playable region - the data tree has a
        # `utility` bundle folder with no level of its own.
        if ($res.Output -match "has no level file") { continue }
        $script:AT3PropsWrote[$region] = $true
        # A placement in a zone that does not load the object's geometry is
        # written but invisible. That used to pass silently, which looks exactly
        # like the editor not working at all.
        $lines = @([string[]]($res.Output -split "`r?`n"))
        $warn = @($lines | Where-Object { $_ -match "WARNING" })
        if ($warn.Count -gt 0) {
            $msgs += "Props[$region]: $n placement(s), $($warn.Count) may not be visible:"
            foreach ($wline in $warn) { $msgs += "   " + ($wline -replace "^\s*WARNING:\s*", "") }
        } else {
            $msgs += "Props[$region]: $n placement(s)."
        }
        # A clone inherits its donor's baked lighting, so one placed far from
        # the nearest existing instance of the same object can render unlit.
        # place_props flags it per row; surface the count rather than let it
        # scroll past in output nobody reads.
        $far = @($lines | Where-Object { $_ -match "donor far" })
        if ($far.Count -gt 0) {
            $msgs += "   $($far.Count) placement(s) far from the nearest matching object - lighting may not carry."
        }

        # MAKE THE ASSETS RESIDENT, OR THE PLACEMENTS ARE INERT.
        #
        # place_props only writes level records. An object still needs its
        # geometry, textures and baked lighting available where it stands, and
        # most of a region's props live in streamed zone bundles that the target
        # zone never loads - 274 of region_01's 292 placeable objects. Writing
        # the record without this step is what produced collision boxes with no
        # model, and unlit props.
        #
        # The copy goes into the region's `normal:` bundle. Copying into a zone
        # bundle instead makes the object render but leaves it UNLIT, even when
        # the entire source bundle is carried along - measured, not assumed.
        #
        # It reads the zones off the LEVEL rather than the CSV, because the CSV
        # is not a reliable carrier of the Zone column across an editor save.
        $ensure = Join-Path $ModToolsDir "ensure_asset.py"
        if (Test-Path $ensure) {
            $er = Invoke-AT3Python -Arguments @($ensure, $region, "--from-level")
            if (-not $er.Ok) {
                $msgs += "Assets[$region]: FAILED - $($er.Output)"
            } else {
                $line = @([string[]]($er.Output -split "`r?`n") | Where-Object { $_ -match "needed asset copies" })
                if ($line.Count -gt 0) { $msgs += "Assets[$region]: " + ($line[0].Trim() -replace "^region_\S+:\s*", "") }
            }
        }
    }
    if ($msgs.Count -eq 0) { return "Props: none placed." }
    return ($msgs -join "  ")
}

# The randomizer runs AFTER the spawn stage, and only ever overwrites the
# character hash of records that already exist - it never inserts or removes
# one. apply_spawns rebuilds the level from its own base each run, so every
# Apply Changes re-rolls from a clean slate instead of compounding.
function Set-AT3RandomizerAll {
    $script2 = Join-Path $ModToolsDir "randomize_spawns.py"
    if (-not (Test-Path $script2)) { return "" }
    if (-not (Test-Path $RandomizerConfigPath)) { return "" }
    $cfg = Get-AT3RandomizerConfig
    if (-not (@("1", "true", "yes", "y", "on") -contains ([string]$cfg.Enabled).ToLower())) { return "" }
    $res = Invoke-AT3Python -Arguments @($script2, "--all", "--config", $RandomizerConfigPath)
    if (-not $res.Ok) { return "Randomizer: FAILED - $($res.Output)" }
    $lines = @([string[]]($res.Output -split "`r?`n"))
    $tot = @($lines | Where-Object { $_ -match "retyped in total" })
    # The seed matters even when it was generated - it is how a roll gets shared.
    $sd = @($lines | Where-Object { $_ -match "^seed " })
    $parts = @()
    if ($tot.Count -gt 0) { $parts += $tot[0].Trim() }
    if ($sd.Count -gt 0) { $parts += $sd[0].Trim() }
    if ($parts.Count -gt 0) { return "Randomizer: " + ($parts -join "  |  ") }
    return "Randomizer: ran."
}

# EVERY LEVEL BACK TO ITS SPAWN BASE, BEFORE ANYTHING WRITES TO ONE.
#
# This has to run BEFORE the preset stage, not after. Set-AT3PresetMods writes
# the preset's spawn and job hashes straight into the level by offset - that is
# how the jailbreak_blisterz fight is staged - and a revert afterwards erased
# them, so the preset installed the character and then wiped his placement.
#
# It also has to run at all: the randomizer patches hashes IN PLACE with nothing
# to undo them, so without a revert a region stayed randomized forever once it
# had been randomized, even with the randomizer switched off.
#
# Order that satisfies both: reset -> preset writes -> spawn edits -> randomize.
function Reset-AT3SpawnLevels {
    $spawnScript = Join-Path $ModToolsDir "apply_spawns.py"
    if (-not (Test-Path $spawnScript)) { return "" }
    $n = 0
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter "spawns_*.csv" -ErrorAction SilentlyContinue)) {
        $region = $f.BaseName -replace "^spawns_", ""
        $res = Invoke-AT3Python -Arguments @($spawnScript, $region, "--revert")
        if ($res.Ok -and ($res.Output -match "reverted")) { $n++ }
    }
    if ($n -eq 0) { return "" }
    return "Spawns: $n level(s) reset to base."
}

function Set-AT3SpawnsAll {
    $spawnScript = Join-Path $ModToolsDir "apply_spawns.py"
    if (-not (Test-Path $spawnScript)) { return "" }
    $msgs = @()
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter "spawns_*.csv" -ErrorAction SilentlyContinue)) {
        $region = $f.BaseName -replace "^spawns_", ""
        $n = @(Import-Csv -LiteralPath $f.FullName -ErrorAction SilentlyContinue).Count
        # The level was already returned to its spawn base by
        # Reset-AT3SpawnLevels, before the preset stage. Nothing to do here.
        if ($n -eq 0) { continue }
        $argv = @($spawnScript, $region, "--csv", $f.FullName)
        # LAYER ON THE PROP STAGE - BUT ONLY IF IT ACTUALLY RAN.
        #
        # Props and spawns write the same .lvl, so when place_props has just
        # rebuilt it the spawn pass must start from THAT file or the placements
        # are lost. Staging the live .lvl unconditionally is what used to happen,
        # and it is wrong whenever the prop stage skipped the region - which it
        # does for any region with no props_*.csv, or an empty one. The staged
        # file then still held the PREVIOUS run's spawns, apply_spawns rebuilt
        # from it, and every Apply Changes added the same NPC again. Six regions
        # were found carrying doubled spawns from exactly this, 2026-08-30.
        #
        # With no --base, apply_spawns rebuilds from its own .spawnsbak, which is
        # idempotent. So pass --base only for regions the prop stage wrote.
        $stage = $null
        if ($script:AT3PropsWrote -and $script:AT3PropsWrote.ContainsKey($region)) {
            $lvl = Join-Path $GameRoot "data\bundles\region_$region\lm_level_$region.lvl"
            $stage = "$lvl.stage"
            try { Copy-Item -LiteralPath $lvl -Destination $stage -Force -ErrorAction Stop; $argv += @("--base", $stage) } catch { $stage = $null }
        }
        $res = Invoke-AT3Python -Arguments $argv
        if ($stage) { Remove-Item -LiteralPath $stage -ErrorAction SilentlyContinue }
        if (-not $res.Ok) { $msgs += "Spawns[$region]: FAILED - $($res.Output)"; continue }
        $refused = @([string[]]($res.Output -split "`r?`n") | Where-Object { $_ -match "REFUSED" })
        if ($refused.Count -gt 0) {
            $why = ($refused -join " ") -replace "^\s*REFUSED line \d+:\s*", ""
            $msgs += "Spawns[$region]: $why"
        } else {
            $msgs += "Spawns[$region]: $n change(s)."
        }
    }
    if ($msgs.Count -eq 0) { return "Spawns: none added." }
    return ($msgs -join "  ")
}

# ---------------------------------------------------------------------------
# Index coherence - always last
# ---------------------------------------------------------------------------
# A region's blockmap carries a BYTE-FOR-BYTE COPY of every record descriptor in
# every bundle it indexes (see ModTools\BLOCKMAP_FORMAT.md). So every value
# exists twice, and a stage that patches a bundle in place - the ammo knockback
# writer does exactly that, deliberately, so it never has to rebuild anything -
# leaves the index holding the old value. Which copy the engine reads then
# decides whether the edit does anything at all.
#
# That is not hypothetical. Region_01 and region_06 were found with their tgl
# bundle holding 1000.0 where the index still held the vanilla -1.0, and a
# separate desync had region_01's index claiming 1211 records in a bundle that
# held 1209 - which every existing check reported as PASS, because
# validate_bundle.py only ever compared one pair.
#
# Regenerating the index from the bundles makes the two agree. It is idempotent,
# it preserves existing padding so a healthy region is never rewritten, and it
# refuses outright if any bundle cannot be read rather than writing an index
# built from files it only partly saw.
function Sync-AT3Blockmaps {
    $script = Join-Path $ModToolsDir "check_groups.py"
    if (-not (Test-Path $script)) { return "" }
    $res = Invoke-AT3Python -Arguments @($script, "--all", "--repair")
    $lines = @([string[]]($res.Output -split "`r?`n"))
    $refused = @($lines | Where-Object { $_ -match "REFUSED" })
    if ($refused.Count -gt 0) {
        return "Index: NOT synced - " + (($refused -join " ") -replace "^\s*region_\S+:\s*REFUSED\s*-\s*", "")
    }
    $written = @($lines | Where-Object { $_ -match "written; .syncbak" })
    if ($written.Count -gt 0) {
        return "Index: resynced $($written.Count) region blockmap(s) to match the bundles."
    }
    return "Index: all region blockmaps already match their bundles."
}

# ---------------------------------------------------------------------------
# Presets - file list is shared with v1; loading fills the v2 model.
# ---------------------------------------------------------------------------
$script:LoadedPreset = $null
# Which file it came from. Kept so deleting a preset can tell whether it is the
# one currently loaded, and unload it - otherwise APPLY CHANGES would go looking
# for files that no longer exist.
$script:LoadedPresetPath = $null

# Delete a preset: its .json, and the companion folder of shipped files if it
# has one. Both live in StrangerAT3\Presets.
#
# Safe with respect to the game: preset files are put back from the .at3vanilla
# copies in the game tree by Restore-AT3PresetFiles, not from the preset folder,
# so removing a preset cannot strand modified bundles on disk. The next APPLY
# CHANGES still reverts cleanly.
function Remove-AT3Preset {
    param([Parameter(Mandatory)][string]$Path)
    $name = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $done = @()
    $dir = Join-Path (Split-Path -Parent $Path) $name
    if (Test-Path -LiteralPath $dir -PathType Container) {
        $n = @(Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue).Count
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction Stop
        $done += "$n file(s) from '$name'"
    }
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        $done += "$name.json"
    }
    if ($script:LoadedPresetPath -and ($script:LoadedPresetPath -eq $Path)) {
        $script:LoadedPreset = $null
        $script:LoadedPresetPath = $null
        $done += "it was the loaded preset, so it has been unloaded"
    }
    if ($done.Count -eq 0) { return "Preset '$name' was already gone." }
    return "Deleted preset '$name' - " + ($done -join ", ") + "."
}

function Get-PresetFiles {
    if (-not (Test-Path $PresetsDir)) { return @() }
    return @(Get-ChildItem -LiteralPath $PresetsDir -Filter *.json -File -ErrorAction SilentlyContinue | Sort-Object Name)
}

# Vanilla defaults. The multipliers are 1x; misstime is stored RAW (10 = 1x).
# Health and Stamina have no known vanilla number - blank means "leave the
# game's own value alone", which is what SWSE does with an empty field.
$script:GlobalDefaults = @{ Health = ""; Stamina = ""; FireRate = "1"; Reload = "1"; Accuracy = "1"; MissTime = "10" }
$script:GlobalRules = @{}
foreach ($k in $script:GlobalDefaults.Keys) { $script:GlobalRules[$k] = $script:GlobalDefaults[$k] }

# Fill the panel from what is actually configured on disk, the same way the
# ammo tab reads live bundle values rather than trusting a snapshot. Falls back
# to the vanilla defaults for anything missing.
function Initialize-AT3GlobalRules {
    foreach ($k in $script:GlobalDefaults.Keys) { $script:GlobalRules[$k] = $script:GlobalDefaults[$k] }

    if (Test-Path $PlayerPrefsPath) {
        foreach ($line in @(Get-Content -LiteralPath $PlayerPrefsPath)) {
            if ($line -match '^\s*health\s*=\s*(.*)$')  { $script:GlobalRules.Health  = $Matches[1].Trim() }
            if ($line -match '^\s*stamina\s*=\s*(.*)$') { $script:GlobalRules.Stamina = $Matches[1].Trim() }
        }
    }

    if (Test-Path $AiPrefsPath) {
        $inSection = $false
        $vals = @{}
        foreach ($line in @(Get-Content -LiteralPath $AiPrefsPath)) {
            $t = $line.Trim()
            if ($t -match '^\[(.+)\]$') { $inSection = ($Matches[1] -eq 'Racketeer'); continue }
            if (-not $inSection) { continue }
            if ($t -match '^([a-z]+)\s*=\s*([0-9.]+)') { $vals[$Matches[1]] = [double]$Matches[2] }
        }
        # Set-AT3AiProfile writes reload and accuracy INVERTED (it stores
        # 1/value), so they have to be inverted again on the way back in or the
        # panel would show the reciprocal of what the user typed.
        if ($vals.ContainsKey("firerate")) { $script:GlobalRules.FireRate = ("{0:0.###}" -f $vals["firerate"]) }
        if ($vals.ContainsKey("reload")   -and $vals["reload"]   -gt 0) { $script:GlobalRules.Reload   = ("{0:0.###}" -f (1.0 / $vals["reload"])) }
        if ($vals.ContainsKey("accuracy") -and $vals["accuracy"] -gt 0) { $script:GlobalRules.Accuracy = ("{0:0.###}" -f (1.0 / $vals["accuracy"])) }
        if ($vals.ContainsKey("misstime")) { $script:GlobalRules.MissTime = ("{0:0.###}" -f $vals["misstime"]) }
    }
}

function Load-AT3Preset {
    param([Parameter(Mandatory)][string]$Path)
    $p = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $script:LoadedPreset = $p
    $script:LoadedPresetPath = $Path
    # Rescan on load too, not just on Apply, so anything that inspects
    # $script:LoadedPreset before Apply is clicked - a future "what does this
    # preset need" panel, for instance - sees current residency rather than
    # whatever startup saw.
    $script:AT3IndexMap = $null
    [void](Update-AT3Index)
    [void](Update-AT3Catalogue)
    if ($p.Global) {
        foreach ($k in @("Health","Stamina","FireRate","Reload","Accuracy","MissTime")) {
            if ($null -ne $p.Global.PSObject.Properties[$k]) { $script:GlobalRules[$k] = [string]$p.Global.$k }
        }
    }
    # Format 3 carries every tool's state; an older preset leaves the editors alone.
    if ($p.Editors) { Set-AT3PresetEditors -Editors $p.Editors }
    $n = 0
    if ($p.Ammo) {
        foreach ($a in $p.Ammo) {
            $nm = ([string]$a.Name).ToLower()
            # Ammo absent from an older preset keeps its current value rather
            # than being zeroed.
            if ($script:AmmoCur.ContainsKey($nm)) {
                $script:AmmoCur[$nm].Knock = [double]$a.Knock
                $script:AmmoCur[$nm].KnockPlayer = [double]$a.KnockPlayer
                $n++
            }
        }
    }
    return $n
}

$script:ThemeXaml = @'
<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <!-- The stock Button template paints its OWN blue mouse-over and pressed
       chrome and ignores the SystemColors brushes entirely, so overriding
       those does nothing for buttons. Replacing the template is the only way
       to control those two states. -->
  <Style TargetType="Button">
    <Setter Property="Foreground" Value="#F2E4C4"/>
    <Setter Property="Background" Value="#4A3524"/>
    <Setter Property="BorderBrush" Value="#8A6D3B"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="FontFamily" Value="Georgia"/>
    <Setter Property="Padding" Value="6,2"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="SnapsToDevicePixels" Value="True"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="bd"
                  Background="{TemplateBinding Background}"
                  BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="{TemplateBinding BorderThickness}"
                  SnapsToDevicePixels="True">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              Margin="{TemplateBinding Padding}"
                              RecognizesAccessKey="True"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="bd" Property="Background" Value="#2C5A36"/>
              <Setter TargetName="bd" Property="BorderBrush" Value="#5E8C4A"/>
            </Trigger>
            <Trigger Property="IsPressed" Value="True">
              <Setter TargetName="bd" Property="Background" Value="#16301C"/>
              <Setter TargetName="bd" Property="BorderBrush" Value="#3E6B34"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Foreground" Value="#6A5F4C"/>
              <Setter TargetName="bd" Property="Background" Value="#2A211A"/>
              <Setter TargetName="bd" Property="BorderBrush" Value="#4A3524"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <!-- Menu items in the flyouts have the same problem. -->
  <Style TargetType="MenuItem">
    <Setter Property="Foreground" Value="#F2E4C4"/>
    <Setter Property="FontFamily" Value="Georgia"/>
    <Setter Property="Padding" Value="8,4"/>
    <Style.Triggers>
      <Trigger Property="IsHighlighted" Value="True">
        <Setter Property="Background" Value="#2C5A36"/>
        <Setter Property="Foreground" Value="#F2E4C4"/>
      </Trigger>
      <Trigger Property="IsEnabled" Value="False">
        <Setter Property="Foreground" Value="#6A5F4C"/>
      </Trigger>
    </Style.Triggers>
  </Style>
  <!-- Column headers ship as light grey with black text, which reads as a
       white bar across the top of every table. -->
  <Style TargetType="DataGridColumnHeader">
    <Setter Property="Background" Value="#2A1F16"/>
    <Setter Property="Foreground" Value="#D9A441"/>
    <Setter Property="FontFamily" Value="Georgia"/>
    <Setter Property="FontWeight" Value="Bold"/>
    <Setter Property="FontSize" Value="12"/>
    <Setter Property="Padding" Value="6,4"/>
    <Setter Property="BorderBrush" Value="#4A3524"/>
    <Setter Property="BorderThickness" Value="0,0,1,1"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="DataGridColumnHeader">
          <Border Background="{TemplateBinding Background}"
                  BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="{TemplateBinding BorderThickness}">
            <ContentPresenter Margin="{TemplateBinding Padding}"
                              VerticalAlignment="Center"
                              HorizontalAlignment="Left"/>
          </Border>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <!-- Cells ship transparent over a white grid background, and the stock
       IsSelected trigger paints them with the system highlight - a bright blue
       bar with white text. Both read as "the table turned white". -->
  <Style TargetType="DataGridCell">
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Foreground" Value="#E8D9B5"/>
    <Setter Property="BorderBrush" Value="Transparent"/>
    <Setter Property="BorderThickness" Value="0"/>
    <Style.Triggers>
      <Trigger Property="IsSelected" Value="True">
        <Setter Property="Background" Value="#24402C"/>
        <Setter Property="Foreground" Value="#F2E4C4"/>
        <Setter Property="BorderBrush" Value="#3E6B4A"/>
        <Setter Property="BorderThickness" Value="1"/>
      </Trigger>
      <Trigger Property="IsKeyboardFocusWithin" Value="True">
        <Setter Property="Background" Value="#1B1410"/>
      </Trigger>
    </Style.Triggers>
  </Style>

  <!-- The empty filler header to the right of the last column. -->
  <Style TargetType="DataGridRowHeader">
    <Setter Property="Background" Value="#2A1F16"/>
    <Setter Property="BorderBrush" Value="#4A3524"/>
  </Style>

  <!-- Scrollbars: the stock ones are a light grey track with a white thumb. -->
  <Style x:Key="AT3ScrollThumb" TargetType="Thumb">
    <Setter Property="OverridesDefaultStyle" Value="True"/>
    <Setter Property="IsTabStop" Value="False"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Thumb">
          <Border x:Name="tb" Background="#5A4430" BorderBrush="#6A5334"
                  BorderThickness="1" CornerRadius="2" Margin="2"/>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="tb" Property="Background" Value="#2C5A36"/>
              <Setter TargetName="tb" Property="BorderBrush" Value="#5E8C4A"/>
            </Trigger>
            <Trigger Property="IsDragging" Value="True">
              <Setter TargetName="tb" Property="Background" Value="#16301C"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="AT3ScrollPage" TargetType="RepeatButton">
    <Setter Property="OverridesDefaultStyle" Value="True"/>
    <Setter Property="IsTabStop" Value="False"/>
    <Setter Property="Focusable" Value="False"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="RepeatButton">
          <Border Background="Transparent"/>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ScrollBar">
    <Setter Property="Background" Value="#150F0B"/>
    <Setter Property="Width" Value="12"/>
    <Setter Property="MinWidth" Value="12"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ScrollBar">
          <Grid x:Name="root" Background="{TemplateBinding Background}">
            <Track x:Name="PART_Track" IsDirectionReversed="True">
              <Track.Thumb>
                <Thumb Style="{StaticResource AT3ScrollThumb}"/>
              </Track.Thumb>
              <Track.IncreaseRepeatButton>
                <RepeatButton Style="{StaticResource AT3ScrollPage}" Command="ScrollBar.PageDownCommand"/>
              </Track.IncreaseRepeatButton>
              <Track.DecreaseRepeatButton>
                <RepeatButton Style="{StaticResource AT3ScrollPage}" Command="ScrollBar.PageUpCommand"/>
              </Track.DecreaseRepeatButton>
            </Track>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property="Orientation" Value="Horizontal">
              <Setter TargetName="PART_Track" Property="IsDirectionReversed" Value="False"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
    <Style.Triggers>
      <Trigger Property="Orientation" Value="Horizontal">
        <Setter Property="Width" Value="Auto"/>
        <Setter Property="MinWidth" Value="0"/>
        <Setter Property="Height" Value="12"/>
        <Setter Property="MinHeight" Value="12"/>
      </Trigger>
    </Style.Triggers>
  </Style>

  <!-- TextBox and ComboBox ship white; they were the last bright surfaces. -->
  <Style TargetType="TextBox">
    <Setter Property="Background" Value="#2A1F16"/>
    <Setter Property="Foreground" Value="#F2E4C4"/>
    <Setter Property="BorderBrush" Value="#6A5334"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CaretBrush" Value="#F2E4C4"/>
    <Setter Property="SelectionBrush" Value="#2C5A36"/>
    <Setter Property="Padding" Value="4,2"/>
    <Setter Property="VerticalContentAlignment" Value="Center"/>
    <Style.Triggers>
      <!-- Focus must stay DARK. The point of the highlight is to show which
           box has the caret, not to blank it out under light-coloured text. -->
      <Trigger Property="IsFocused" Value="True">
        <Setter Property="Background" Value="#33261B"/>
        <Setter Property="BorderBrush" Value="#D9A441"/>
      </Trigger>
    </Style.Triggers>
  </Style>

  <Style x:Key="AT3ComboToggle" TargetType="ToggleButton">
    <Setter Property="OverridesDefaultStyle" Value="True"/>
    <Setter Property="IsTabStop" Value="False"/>
    <Setter Property="Focusable" Value="False"/>
    <Setter Property="ClickMode" Value="Press"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ToggleButton">
          <Border x:Name="cb" Background="#2A1F16" BorderBrush="#6A5334" BorderThickness="1">
            <Path x:Name="ar" HorizontalAlignment="Right" VerticalAlignment="Center"
                  Margin="0,0,7,0" Fill="#D9A441" Data="M 0 0 L 8 0 L 4 5 Z"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="cb" Property="Background" Value="#33261B"/>
              <Setter TargetName="cb" Property="BorderBrush" Value="#5E8C4A"/>
            </Trigger>
            <Trigger Property="IsChecked" Value="True">
              <Setter TargetName="cb" Property="Background" Value="#1F3D26"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ComboBox">
    <Setter Property="Foreground" Value="#F2E4C4"/>
    <Setter Property="FontFamily" Value="Georgia"/>
    <Setter Property="Padding" Value="6,2"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBox">
          <Grid>
            <ToggleButton Style="{StaticResource AT3ComboToggle}"
                          IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}"/>
            <!-- SelectionBoxItemTemplate is what applies DisplayMemberPath.
                 Without it the box renders the bound object's ToString(), e.g.
                 "@{Id=01; Display=Gizzard Gulch}" instead of the name. -->
            <ContentPresenter Margin="{TemplateBinding Padding}"
                              HorizontalAlignment="Left" VerticalAlignment="Center"
                              Content="{TemplateBinding SelectionBoxItem}"
                              ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"
                              ContentTemplateSelector="{Binding ItemTemplateSelector, RelativeSource={RelativeSource TemplatedParent}}"
                              IsHitTestVisible="False"/>
            <Popup x:Name="PART_Popup" AllowsTransparency="True"
                   IsOpen="{TemplateBinding IsDropDownOpen}"
                   Placement="Bottom" Focusable="False" PopupAnimation="Slide">
              <Border Background="#1B1410" BorderBrush="#6A5334" BorderThickness="1"
                      MinWidth="{TemplateBinding ActualWidth}"
                      MaxHeight="{TemplateBinding MaxDropDownHeight}">
                <ScrollViewer>
                  <StackPanel IsItemsHost="True" KeyboardNavigation.DirectionalNavigation="Contained"/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ComboBoxItem">
    <Setter Property="Foreground" Value="#F2E4C4"/>
    <Setter Property="FontFamily" Value="Georgia"/>
    <Setter Property="Padding" Value="6,3"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBoxItem">
          <Border x:Name="ib" Background="Transparent" Padding="{TemplateBinding Padding}">
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsHighlighted" Value="True">
              <Setter TargetName="ib" Property="Background" Value="#2C5A36"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <!-- TabControl ships with a bright grey strip and a white body, which is
       every bit as loud as the TextBox/ComboBox defaults were. Added for the
       Character Creator, whose sections are tabs rather than one long scroll,
       and by the Weapon Creator. -->
  <Style TargetType="TabControl">
    <Setter Property="Background" Value="#120D0A"/>
    <Setter Property="BorderBrush" Value="#4A3524"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Padding" Value="0"/>
  </Style>

  <Style TargetType="TabItem">
    <Setter Property="Foreground" Value="#C8BB9B"/>
    <Setter Property="FontFamily" Value="Georgia"/>
    <Setter Property="FontSize" Value="12"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="TabItem">
          <Border x:Name="tb" Background="#1B1410" BorderBrush="#4A3524"
                  BorderThickness="1,1,1,0" Margin="0,0,2,0" Padding="10,5">
            <ContentPresenter ContentSource="Header" VerticalAlignment="Center"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsSelected" Value="True">
              <Setter TargetName="tb" Property="Background" Value="#120D0A"/>
              <Setter TargetName="tb" Property="BorderBrush" Value="#8A6D3B"/>
              <Setter Property="Foreground" Value="#F2E4C4"/>
            </Trigger>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="tb" Property="Background" Value="#2A1F16"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Foreground" Value="#6A5F4C"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

</ResourceDictionary>
'@

function Set-AT3Theme {
    param([Parameter(Mandatory)]$Target)
    try {
        $sr = New-Object System.IO.StringReader $script:ThemeXaml
        $xr = [System.Xml.XmlReader]::Create($sr)
        $dict = [Windows.Markup.XamlReader]::Load($xr)
        [void]$Target.Resources.MergedDictionaries.Add($dict)
    } catch { }
}

# ===========================================================================
# Selection highlight
#
# The stock Windows highlight is a bright blue that the launcher's pale text
# sits on top of almost invisibly. Overriding the SystemColors brush keys
# retargets every selectable surface at once - DataGrid rows and cells, list
# and combo items, menu items - instead of restyling each control.
# ===========================================================================
$script:SelBrush     = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#1F3D26")
$script:SelTextBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")

function Set-AT3Selection {
    param([Parameter(Mandatory)]$Target)
    $r = $Target.Resources
    $r[[System.Windows.SystemColors]::HighlightBrushKey]                        = $script:SelBrush
    $r[[System.Windows.SystemColors]::HighlightTextBrushKey]                    = $script:SelTextBrush
    $r[[System.Windows.SystemColors]::InactiveSelectionHighlightBrushKey]       = $script:SelBrush
    $r[[System.Windows.SystemColors]::InactiveSelectionHighlightTextBrushKey]   = $script:SelTextBrush
    $r[[System.Windows.SystemColors]::MenuHighlightBrushKey]                    = $script:SelBrush
    $r[[System.Windows.SystemColors]::HighlightColorKey]                        = $script:SelBrush.Color
    $r[[System.Windows.SystemColors]::HighlightTextColorKey]                    = $script:SelTextBrush.Color
}

# ===========================================================================
# AT3 v2 - main window
# ===========================================================================
[xml]$mainXaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Stranger: Armed to the Teeth" Height="440" Width="660"
        WindowStartupLocation="CenterScreen" ResizeMode="CanMinimize"
        Background="#1B1410">
  <Window.Resources>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#E8D9B5"/>
      <Setter Property="FontFamily" Value="Georgia"/>
    </Style>
  </Window.Resources>

  <Grid Margin="14">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- actions | logo | editors -->
    <Grid Grid.Row="0" Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="180"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="180"/>
      </Grid.ColumnDefinitions>

      <StackPanel Grid.Column="0">
        <Button x:Name="btnLaunch"  Content="OPEN LAUNCHER"  />
        <Button x:Name="btnRestore" Content="RESTORE VANILLA"/>
        <Button x:Name="btnPresets" Content="PRESETS"/>
      </StackPanel>

      <Image x:Name="imgLogo" Grid.Column="1" Margin="8,0,8,0"
             Stretch="Uniform" VerticalAlignment="Top" MaxHeight="120"/>

      <StackPanel Grid.Column="2">
        <Button x:Name="btnGameplay" Content="Gameplay Editor"/>
        <Button x:Name="btnMap"      Content="Map Editor"     />
        <Button x:Name="btnCreator"  Content="Creator"        />
      </StackPanel>
    </Grid>

    <Border Grid.Row="1" Background="#120D0A" BorderBrush="#4A3524" BorderThickness="1" Padding="8">
      <ScrollViewer VerticalScrollBarVisibility="Auto">
        <TextBlock x:Name="txtFeedback" FontFamily="Consolas" FontSize="11"
                   Foreground="#C8BB9B" TextWrapping="Wrap"/>
      </ScrollViewer>
    </Border>

    <TextBlock Grid.Row="2" Margin="0,10,0,0" FontSize="11" Foreground="#8A7A5C"
               TextWrapping="Wrap"
               Text="Stranger: Armed to the Teeth (v0.3.0) by Racewizard is an extension of Stranger's Wrath Script Extender, an unofficial modding platform for Oddworld: Stranger's Wrath HD"/>
  </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader $mainXaml
$window = [Windows.Markup.XamlReader]::Load($reader)

$btnLaunch   = $window.FindName("btnLaunch")
$btnRestore  = $window.FindName("btnRestore")
$btnPresets  = $window.FindName("btnPresets")
$btnGameplay = $window.FindName("btnGameplay")
$btnMap      = $window.FindName("btnMap")
$btnCreator  = $window.FindName("btnCreator")
$txtFeedback = $window.FindName("txtFeedback")
$imgLogo     = $window.FindName("imgLogo")

Set-AT3Theme -Target $window
Set-AT3Selection -Target $window

# Sizing that used to live in the keyed styles. Deliberately not in the
# implicit Button style, or the small revert buttons inherit a bottom margin.
foreach ($b in @($btnLaunch, $btnRestore, $btnPresets, $btnGameplay, $btnMap, $btnCreator)) {
    $b.Height = 30
    $b.Margin = New-Object System.Windows.Thickness 0,0,0,6
    $b.FontSize = 12
}
$greenBg = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#26402A")
$greenBd = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#5E8C4A")
$btnGameplay.Background = $greenBg
$btnGameplay.BorderBrush = $greenBd
$blueBg = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A3145")
$blueBd = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#5A6E9C")
$btnMap.Background = $blueBg
$btnMap.BorderBrush = $blueBd
$plumBg = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#3A2438")
$plumBd = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8C5E86")
$btnCreator.Background = $plumBg
$btnCreator.BorderBrush = $plumBd

$logoPath = Join-Path $AT3Dir "header_logo.png"
if (Test-Path $logoPath) {
    $bmp = New-Object System.Windows.Media.Imaging.BitmapImage
    $bmp.BeginInit()
    $bmp.UriSource = New-Object System.Uri($logoPath)
    $bmp.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bmp.EndInit()
    $imgLogo.Source = $bmp
}

# Feedback box. Startup diagnostics stay at the top; actions append below.
$script:FeedbackHead = ""
function Set-AT3Feedback {
    param([string]$Text, [switch]$Append)
    if ($Append) {
        $txtFeedback.Text = ($script:FeedbackHead + "`r`n`r`n" + $Text).Trim()
    } else {
        $script:FeedbackHead = $Text
        $txtFeedback.Text = $Text
    }
}

$window.Title = "Stranger: Armed to the Teeth v" + $script:AT3Version
Set-AT3Feedback -Text (Get-AT3Startup)

# ---------------------------------------------------------------------------
# Flyout menus - open to the LEFT of their button, off the window edge
# ---------------------------------------------------------------------------
function New-AT3Menu {
    param([Parameter(Mandatory)]$Owner, [Parameter(Mandatory)][string[]]$Items,
          [string]$Background = "#26402A", [string]$Border = "#5E8C4A",
          [Parameter(Mandatory)][scriptblock]$OnPick)
    $menu = New-Object System.Windows.Controls.ContextMenu
    $menu.Placement = [System.Windows.Controls.Primitives.PlacementMode]::Left
    $menu.PlacementTarget = $Owner
    $menu.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString($Background)
    $menu.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString($Border)
    $menu.BorderThickness = New-Object System.Windows.Thickness 1
    foreach ($label in $Items) {
        $mi = New-Object System.Windows.Controls.MenuItem
        $mi.Header = $label
        $mi.Tag = $label
        $mi.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
        $mi.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
        $mi.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString($Background)
        [void]$mi.Add_Click($OnPick)
        [void]$menu.Items.Add($mi)
    }
    $Owner.ContextMenu = $menu
    $owner = $Owner
    [void]$Owner.Add_Click({
        try { $owner.ContextMenu.IsOpen = $true } catch { }
    }.GetNewClosure())
    return $menu
}

# ===========================================================================
# Shared chrome for editor panels
# ===========================================================================
function New-AT3Panel {
    param([string]$Title, [int]$Width = 720, [int]$Height = 620, [string]$Accent = "gold")
    $w = New-Object System.Windows.Window
    $w.Title = $Title
    $w.Width = $Width
    $w.Height = $Height
    $w.WindowStartupLocation = [System.Windows.WindowStartupLocation]::CenterOwner
    # Setting Owner throws outright if the main window has not been shown.
    try { if ($window -and $window.IsVisible) { $w.Owner = $window } } catch { }
    $w.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#1B1410")
    Set-AT3Theme -Target $w
    Set-AT3Selection -Target $w
    return $w
}

# Gold for the Gameplay Editor, blue for the Map Editor, so a window's colour
# says which menu it came from.
$script:AccentBrushes = @{ gold = "#D9A441"; blue = "#7FA6E8"; plum = "#D9A0D0" }

function New-AT3Header {
    param([string]$Text, [string]$Accent = "gold")
    $t = New-Object System.Windows.Controls.TextBlock
    $t.Text = $Text
    $t.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $t.FontWeight = [System.Windows.FontWeights]::Bold
    $t.FontSize = 13
    $hex = $script:AccentBrushes[$Accent]
    if (-not $hex) { $hex = "#D9A441" }
    $t.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString($hex)
    $t.Margin = New-Object System.Windows.Thickness 0,14,0,6
    return $t
}

function New-AT3Note {
    param([string]$Text)
    $t = New-Object System.Windows.Controls.TextBlock
    $t.Text = $Text
    $t.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $t.FontStyle = [System.Windows.FontStyles]::Italic
    $t.FontSize = 11
    $t.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $t.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
    $t.Margin = New-Object System.Windows.Thickness 0,0,0,8
    return $t
}

# label / textbox / revert, as one row of a StackPanel
function New-AT3Field {
    param([string]$Label, [string]$Value, [string]$Default, [switch]$Disabled)
    $row = New-Object System.Windows.Controls.DockPanel
    $row.Margin = New-Object System.Windows.Thickness 0,0,0,5
    $lbl = New-Object System.Windows.Controls.TextBlock
    $lbl.Text = $Label
    $lbl.Width = 250
    $lbl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $lbl.FontSize = 13
    $lbl.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
    $lbl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString($(if ($Disabled) { "#6A5F4C" } else { "#E8D9B5" }))
    [void]$row.Children.Add($lbl)

    $box = New-Object System.Windows.Controls.TextBox
    $box.Width = 90
    $box.Height = 22
    $box.Text = $Value
    $box.IsEnabled = (-not $Disabled)
    $box.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $box.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $box.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#6A5334")
    $box.VerticalContentAlignment = [System.Windows.VerticalAlignment]::Center
    [void]$row.Children.Add($box)

    if (-not $Disabled) {
        $rst = New-Object System.Windows.Controls.Button
        $rst.Content = [string][char]0x21A9
        $rst.Width = 26
        $rst.Height = 22
        $rst.Padding = New-Object System.Windows.Thickness 0
        $rst.Margin = New-Object System.Windows.Thickness 6,0,0,0
        $rst.ToolTip = "Reset to default ($Default)"
        $rst.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#4A3524")
        $rst.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
        $rst.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A6D3B")
        # Capture the box and the default directly. $this is not reliably set
        # inside a GetNewClosure scriptblock, and reading the value back out of
        # the tooltip text was fragile besides.
        $defaultText = $Default
        [void]$rst.Add_Click({
            try { if ($null -ne $box.Tag) { $box.Text = [string]$box.Tag } else { $box.Text = $defaultText } } catch { }
        }.GetNewClosure())
        [void]$row.Children.Add($rst)
    }
    return @{ Row = $row; Box = $box }
}

# Intentional Miss is shown as a MULTIPLIER over the game's 10ms base, so 1 is
# default and 2 means 20. The value kept in the model and written to presets
# stays RAW (10 = default), which is what aiprefs.txt and the v1 launcher both
# expect - only the field on screen is scaled.
$script:MissBase = 10.0

function ConvertTo-AT3MissDisplay {
    param([string]$Raw)
    if ([string]::IsNullOrWhiteSpace($Raw)) { return "1" }
    $v = 0.0
    if (-not [double]::TryParse($Raw, [ref]$v)) { return "1" }
    return ("{0:0.###}" -f ($v / $script:MissBase))
}

function ConvertFrom-AT3MissDisplay {
    param([string]$Shown)
    if ([string]::IsNullOrWhiteSpace($Shown)) { return "" }
    $v = 0.0
    if (-not [double]::TryParse($Shown, [ref]$v)) { return "" }
    return ("{0:0.###}" -f ($v * $script:MissBase))
}

# ===========================================================================
# Global Game Rules
# ===========================================================================
function Show-AT3GlobalRules {
    $w = New-AT3Panel -Title "Global Game Rules" -Width 640 -Height 520
    $sv = New-Object System.Windows.Controls.ScrollViewer
    $sv.VerticalScrollBarVisibility = "Auto"
    $sv.Margin = New-Object System.Windows.Thickness 16
    $sp = New-Object System.Windows.Controls.StackPanel
    $sv.Content = $sp
    $w.Content = $sv

    [void]$sp.Children.Add((New-AT3Header "---- PLAYER CONTROLS ----"))
    [void]$sp.Children.Add((New-AT3Note ("Player Health and Stamina are affected by difficulty setting. " +
        "Start a New Game in Normal for exact values. May take a moment to implement upon loading into a new region. " +
        "Leave a field blank to keep the game's own value.")))

    $fHealth  = New-AT3Field -Label "Player Health"  -Value $script:GlobalRules.Health  -Default ""
    $fStamina = New-AT3Field -Label "Player Stamina" -Value $script:GlobalRules.Stamina -Default ""
    $fSpeed   = New-AT3Field -Label "Player Speed [WIP]"       -Value "" -Default "" -Disabled
    $fJump    = New-AT3Field -Label "Player Jump Height [WIP]" -Value "" -Default "" -Disabled
    foreach ($f in @($fHealth,$fStamina,$fSpeed,$fJump)) { [void]$sp.Children.Add($f.Row) }

    [void]$sp.Children.Add((New-AT3Header "---- GLOBAL ENEMY CONTROLS ----"))
    $fFire   = New-AT3Field -Label "Fire Rate Multiplier"        -Value $script:GlobalRules.FireRate -Default "1"
    $fReload = New-AT3Field -Label "Reload Speed Multiplier"     -Value $script:GlobalRules.Reload   -Default "1"
    $fCone   = New-AT3Field -Label "Fire Cone Multiplier"        -Value $script:GlobalRules.Accuracy -Default "1"
    $fMiss   = New-AT3Field -Label "Intentional Miss Multiplier" -Value (ConvertTo-AT3MissDisplay $script:GlobalRules.MissTime) -Default "1"
    foreach ($f in @($fFire,$fReload,$fCone,$fMiss)) { [void]$sp.Children.Add($f.Row) }


    # Values live in the model, not the controls, so the panel can be reopened.
    #
    # $rules holds the SAME hashtable as $script:GlobalRules. Assigning through
    # $script: in here would not work: GetNewClosure binds the scriptblock to a
    # new dynamic module, so $script: resolves to that module - the write is
    # lost and PowerShell raises PropertyNotFound on every close. Capturing the
    # object and mutating it is what actually reaches the model.
    $rules = $script:GlobalRules
    $cfm = Add-AT3ConfirmBar -Window $w
    [void]$w.Add_Closed({
        if (-not $cfm.Ok) { return }
        try {
            $rules.Health   = $fHealth.Box.Text.Trim()
            $rules.Stamina  = $fStamina.Box.Text.Trim()
            $rules.FireRate = $fFire.Box.Text.Trim()
            $rules.Reload   = $fReload.Box.Text.Trim()
            $rules.Accuracy = $fCone.Box.Text.Trim()
            $rules.MissTime = ConvertFrom-AT3MissDisplay $fMiss.Box.Text.Trim()
        } catch { }
    }.GetNewClosure())

    [void]$w.ShowDialog()
    if ($cfm.Ok) { Invoke-AT3Apply -RulesOnly }
}

# ===========================================================================
# Ammotype Config - three tables over one shared model
# ===========================================================================
function New-AT3AmmoTable {
    param([string[]]$Names)
    $t = New-Object System.Data.DataTable
    foreach ($c in @("Name","Display","Knock","KnockPlayer")) { [void]$t.Columns.Add($c, [string]) }
    foreach ($n in $Names) {
        $r = $t.NewRow()
        $r["Name"] = $n
        $r["Display"] = Get-AT3AmmoDisplay $n
        $r["Knock"] = ("{0:0.###}" -f [double]$script:AmmoCur[$n].Knock)
        $r["KnockPlayer"] = ("{0:0.###}" -f [double]$script:AmmoCur[$n].KnockPlayer)
        $t.Rows.Add($r)
    }
    $t.AcceptChanges()
    return ,$t
}

# ---------------------------------------------------------------------------
# Grid edit boxes
# ---------------------------------------------------------------------------
# A DataGridTextColumn supplies its OWN editing style, which beats the implicit
# dark `TargetType="TextBox"` style in the theme. That default sets no
# Background, so the editor falls back to the stock white TextBox - a white box
# under light-coloured text, unreadable while you type in it.
#
# The style is built in code rather than pulled from window resources because
# the ammo grid is created in a function with no window in scope, so
# FindResource is not available there.
$script:AT3GridEditStyle = $null
function Get-AT3GridEditStyle {
    if ($script:AT3GridEditStyle) { return $script:AT3GridEditStyle }
    $c = New-Object System.Windows.Media.BrushConverter
    $st = New-Object System.Windows.Style([System.Windows.Controls.TextBox])
    $pairs = @(
        @([System.Windows.Controls.Control]::BackgroundProperty,  $c.ConvertFromString("#1B1410")),
        @([System.Windows.Controls.Control]::ForegroundProperty,  $c.ConvertFromString("#F2E4C4")),
        @([System.Windows.Controls.Control]::BorderBrushProperty, $c.ConvertFromString("#D9A441")),
        @([System.Windows.Controls.Primitives.TextBoxBase]::CaretBrushProperty,     $c.ConvertFromString("#F2E4C4")),
        @([System.Windows.Controls.Primitives.TextBoxBase]::SelectionBrushProperty, $c.ConvertFromString("#2C5A36")),
        @([System.Windows.Controls.Control]::BorderThicknessProperty, (New-Object System.Windows.Thickness 1)),
        @([System.Windows.Controls.Control]::PaddingProperty, (New-Object System.Windows.Thickness 3,1,3,1)),
        @([System.Windows.Controls.Control]::VerticalContentAlignmentProperty, [System.Windows.VerticalAlignment]::Center)
    )
    foreach ($pr in $pairs) {
        [void]$st.Setters.Add((New-Object System.Windows.Setter($pr[0], $pr[1])))
    }
    $st.Seal()
    $script:AT3GridEditStyle = $st
    return $st
}

function Set-AT3GridEditStyle {
    param($Grid)
    $st = Get-AT3GridEditStyle
    foreach ($col in $Grid.Columns) {
        if ($col -is [System.Windows.Controls.DataGridTextColumn]) {
            $col.EditingElementStyle = $st
        }
    }
}

function New-AT3AmmoGrid {
    param($Table, [switch]$ShowKnock, [switch]$ShowPlayer)
    $conv = New-Object System.Windows.Media.BrushConverter
    $g = New-Object System.Windows.Controls.DataGrid
    $g.AutoGenerateColumns = $false
    $g.CanUserAddRows = $false
    $g.CanUserDeleteRows = $false
    $g.CanUserSortColumns = $false
    $g.HeadersVisibility = "Column"
    $g.GridLinesVisibility = "Horizontal"
    $g.Background   = $conv.ConvertFromString("#120D0A")
    $g.RowBackground = $conv.ConvertFromString("#1B1410")
    $g.Foreground   = $conv.ConvertFromString("#E8D9B5")
    $g.BorderBrush  = $conv.ConvertFromString("#4A3524")
    $g.HorizontalScrollBarVisibility = "Disabled"
    $g.MaxHeight = 300

    $c = New-Object System.Windows.Controls.DataGridTextColumn
    $c.Header = "Ammo Type"
    $c.IsReadOnly = $true
    $c.Binding = New-Object System.Windows.Data.Binding "Display"
    # star width so the name column absorbs the slack - a fixed width
    # leaves an empty filler column to the right of the revert button
    $c.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.Controls.DataGridLengthUnitType]::Star)
    [void]$g.Columns.Add($c)

    if ($ShowKnock) {
        $k = New-Object System.Windows.Controls.DataGridTextColumn
        $k.Header = $(if ($ShowPlayer) { "vs Enemies" } else { "Power" })
        $b = New-Object System.Windows.Data.Binding "Knock"
        $b.Mode = [System.Windows.Data.BindingMode]::TwoWay
        $b.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
        $k.Binding = $b
        $k.Width = New-Object System.Windows.Controls.DataGridLength 110
        [void]$g.Columns.Add($k)
    }
    if ($ShowPlayer) {
        $p = New-Object System.Windows.Controls.DataGridTextColumn
        $p.Header = $(if ($ShowKnock) { "vs Player" } else { "Power" })
        $b2 = New-Object System.Windows.Data.Binding "KnockPlayer"
        $b2.Mode = [System.Windows.Data.BindingMode]::TwoWay
        $b2.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
        $p.Binding = $b2
        $p.Width = New-Object System.Windows.Controls.DataGridLength 110
        [void]$g.Columns.Add($p)
    }

    $revert = New-Object System.Windows.Controls.DataGridTemplateColumn
    $revert.Header = ""
    $revert.Width = New-Object System.Windows.Controls.DataGridLength 40
    $xamlTpl = '<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">' +
               '<Button Content="&#x21A9;" Width="26" Height="20" Padding="0" FontSize="12" ' +
               'ToolTip="Reset to the game default" ' +
               'Background="#4A3524" Foreground="#F2E4C4" BorderBrush="#8A6D3B"/></DataTemplate>'
    $revert.CellTemplate = [Windows.Markup.XamlReader]::Parse($xamlTpl)
    [void]$g.Columns.Add($revert)
    Set-AT3GridEditStyle -Grid $g

    # One handler for every revert button in this grid. $van is captured so the
    # lookup does not depend on $script: resolving from inside a handler.
    $van = $script:AmmoVan
    [void]$g.AddHandler(
        [System.Windows.Controls.Button]::ClickEvent,
        [System.Windows.RoutedEventHandler]{
            param($sender, $e)
            try {
                $b = $e.OriginalSource
                if (-not ($b -is [System.Windows.Controls.Button])) { return }
                if ([string]$b.Content -ne [string][char]0x21A9) { return }
                $view = $b.DataContext
                if (-not ($view -is [System.Data.DataRowView])) { return }
                $n = [string]$view.Row["Name"]
                if (-not $van.ContainsKey($n)) { return }
                $view.Row["Knock"]       = ("{0:0.###}" -f [double]$van[$n].Knock)
                $view.Row["KnockPlayer"] = ("{0:0.###}" -f [double]$van[$n].KnockPlayer)
            } catch { }
        }.GetNewClosure())

    $g.ItemsSource = $Table.DefaultView
    return $g
}

function Show-AT3AmmoConfig {
    $w = New-AT3Panel -Title "Ammotype Config" -Width 620 -Height 720

    $enemyNames = @($script:AmmoOrder | Where-Object { $script:AmmoMeta[$_].Enemies } |
                    Sort-Object { $script:AmmoMeta[$_].Order })
    $aoeNames   = @($script:AmmoOrder | Where-Object { $script:AmmoMeta[$_].AoE } |
                    Sort-Object { $script:AmmoMeta[$_].Order })
    $expNames   = @($script:AmmoOrder | Where-Object {
                        (-not $script:AmmoMeta[$_].Enemies) -and (-not $script:AmmoMeta[$_].AoE) } |
                    Sort-Object { $script:AmmoMeta[$_].Order })

    $tEnemy = New-AT3AmmoTable -Names $enemyNames
    $tAoe   = New-AT3AmmoTable -Names $aoeNames
    $tExp   = New-AT3AmmoTable -Names $expNames

    $sv = New-Object System.Windows.Controls.ScrollViewer
    $sv.VerticalScrollBarVisibility = "Auto"
    $sv.Margin = New-Object System.Windows.Thickness 16
    $sp = New-Object System.Windows.Controls.StackPanel
    $sv.Content = $sp
    $w.Content = $sv

    [void]$sp.Children.Add((New-AT3Header "---- POWER AGAINST ENEMIES ----"))
    [void]$sp.Children.Add((New-AT3Note "May affect both knockback and damage dealt."))
    $gEnemy = New-AT3AmmoGrid -Table $tEnemy -ShowKnock
    [void]$sp.Children.Add($gEnemy)

    [void]$sp.Children.Add((New-AT3Header "---- POWER AGAINST PLAYER ----"))
    [void]$sp.Children.Add((New-AT3Note "Only affects knockback dealt to player."))
    $gAoe = New-AT3AmmoGrid -Table $tAoe -ShowPlayer
    [void]$sp.Children.Add($gAoe)

    [void]$sp.Children.Add((New-AT3Header "---- EXPERIMENTAL ----"))
    [void]$sp.Children.Add((New-AT3Note "Effects not fully understood."))
    $gExp = New-AT3AmmoGrid -Table $tExp -ShowKnock -ShowPlayer
    [void]$sp.Children.Add($gExp)


    # Fold every table back into the one model. The AoE table owns only
    # KnockPlayer and the Enemies table owns only Knock, so the ammo that appear
    # in both cannot clobber one another.
    # $cur is the SAME hashtable as $script:AmmoCur - see the note in
    # Show-AT3GlobalRules for why assigning through $script: in here silently
    # fails and throws on every close.
    $cur = $script:AmmoCur
    $cfm = Add-AT3ConfirmBar -Window $w
    [void]$w.Add_Closed({
        if (-not $cfm.Ok) { return }
        try {
            foreach ($g in @($gEnemy, $gAoe, $gExp)) {
                try { [void]$g.CommitEdit([System.Windows.Controls.DataGridEditingUnit]::Row, $true) } catch { }
            }
            $sets = @(
                @{ T = $tEnemy; K = $true;  P = $false }
                @{ T = $tAoe;   K = $false; P = $true  }
                @{ T = $tExp;   K = $true;  P = $true  }
            )
            foreach ($s in $sets) {
                foreach ($r in $s.T.Rows) {
                    $n = [string]$r["Name"]
                    if (-not $cur.ContainsKey($n)) { continue }
                    $v = 0.0
                    if ($s.K -and [double]::TryParse([string]$r["Knock"], [ref]$v))       { $cur[$n].Knock = $v }
                    if ($s.P -and [double]::TryParse([string]$r["KnockPlayer"], [ref]$v)) { $cur[$n].KnockPlayer = $v }
                }
            }
        } catch { }
    }.GetNewClosure())

    [void]$w.ShowDialog()
    if ($cfm.Ok) { Invoke-AT3Apply }
}

function Show-AT3Placeholder {
    param([string]$Name)
    $w = New-AT3Panel -Title $Name -Width 440 -Height 220
    $t = New-Object System.Windows.Controls.TextBlock
    $t.Text = "$Name is not rebuilt in this launcher yet." + [Environment]::NewLine + [Environment]::NewLine +
              "Its editor still lives in the previous launcher, and anything already configured there still applies whenever a tool is confirmed."
    $t.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $t.Margin = New-Object System.Windows.Thickness 20
    $t.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $t.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    $w.Content = $t
    [void]$w.ShowDialog()
}


# ===========================================================================
# CREATOR  (plum)
#
# CHARACTER CREATOR - the Anatomy tab is four dropdowns that constrain each
# other, and none of that relationship is stored anywhere in the game. It is
# derived by ModTools\char_model.py, which walks
#
#   character record -> m_animationConfigFile (a PATH) -> the compiled config
#   record -> its clip dwords -> /data/geometry/characters/<X>/ -> X = SKELETON
#
# and emits CharacterModel.json. This window is a renderer over that file and
# nothing else - it never opens a bundle. That is the Layer 4 rule from
# BUILDER_DESIGN.md: the UI never touches a byte.
#
# WHAT IT DOES NOT DO YET: write. Layer 3 (the build pipeline - resolve, plan,
# apply, place, register, doctor) is not built, so the selections here produce
# a recipe and stop. Saying so in the window is deliberate; a creator that
# looked like it applied and did not would be the worst possible failure.
# ===========================================================================
$script:CharModelPath = Join-Path $AT3Dir "CharacterModel.json"

# ---------------------------------------------------------------------------
# Character names and the hash they determine
#
# A custom character's hash is not chosen - it is DERIVED from its name stem:
#   game_hash("\data\prefs\Characters\<stem>Prefs.txt")
# Verified against CustomHashes.csv: AT3_outlaw_artillery -> B47D78A2 and
# AT3_BF36 -> FFFFDB52. So a name is not a label stuck on afterwards; to the
# game, a different name is a different character.
#
# Transcribed from ModTools\gamehash.py, itself transcribed from stranger.exe
# RVA 0x24D920: reflected CRC-32, init 0xFFFFFFFF, NO final xor, '/' folded
# to '\', ASCII upper-cased, then the low byte of the length folded in as one
# extra byte.
#
# All arithmetic is int64 masked to 32 bits ON PURPOSE. PowerShell 5.1 parses
# a hex literal above 0x7FFFFFFF as a NEGATIVE int32, so 0xEDB88320 and
# 0xFFFFFFFF silently become -306674912 and -1 - the table would be garbage
# with no error. The decimal forms below are those same constants.
# ---------------------------------------------------------------------------
$script:AT3CrcTable = $null

function Get-AT3GameHash {
    param([string]$Path)
    if (-not $script:AT3CrcTable) {
        $t = New-Object 'int64[]' 256
        for ($i = 0; $i -lt 256; $i++) {
            [int64]$c = $i
            for ($k = 0; $k -lt 8; $k++) {
                if ($c -band 1) { $c = ($c -shr 1) -bxor 3988292384 } else { $c = $c -shr 1 }
            }
            $t[$i] = $c
        }
        $script:AT3CrcTable = $t
    }
    $tbl = $script:AT3CrcTable
    [int64]$crc = 4294967295
    $n = 0
    foreach ($ch in $Path.ToCharArray()) {
        $c = [int]$ch
        if ($c -eq 0x2F) { $c = 0x5C }
        elseif ($c -ge 0x61 -and $c -le 0x7A) { $c = $c - 0x20 }
        $crc = (($crc -shr 8) -bxor $tbl[[int](($crc -bxor $c) -band 0xFF)]) -band 4294967295
        $n++
    }
    $crc = (($crc -shr 8) -bxor $tbl[[int](($crc -bxor ($n -band 0xFF)) -band 0xFF)]) -band 4294967295
    return $crc.ToString("X8")
}

function ConvertTo-AT3Stem {
    # "Killer Clakker" -> "AT3_killer_clakker". Lower-case, every run of
    # anything that is not a letter or digit becomes one underscore - the
    # shape every existing custom stem already has.
    param([string]$Name)
    if (-not $Name) { return $null }
    $s = ($Name.ToLowerInvariant() -replace '[^a-z0-9]+', '_').Trim('_')
    if (-not $s) { return $null }
    return ("AT3_" + $s)
}

function Get-AT3StemHash {
    # The same derivations as build_character.py / build_weapon.py - they must
    # agree, or BUILD would enable for a name the builder then refuses.
    param([string]$Stem, [string]$Kind = "character")
    switch ($Kind) {
        "weapon" { return (Get-AT3GameHash -Path ("\data\prefs\Weapons\NPC\" + $Stem + ".txt")) }
        "effect" { return (Get-AT3GameHash -Path ("\data\prefs\Weapons\NPC\Effects\" + $Stem + ".txt")) }
        default  { return (Get-AT3GameHash -Path ("\data\prefs\Characters\" + $Stem + "Prefs.txt")) }
    }
}

function Find-AT3CustomHash {
    # The CustomHashes.csv row matching a hash or a display name, or $null.
    # A FUNCTION rather than an inline read so a GetNewClosure handler can
    # call it - a $script: read inside such a handler resolves to the
    # closure's own scope and comes back empty, which is the bug that made
    # the port button silently do nothing.
    param([string]$Hash, [string]$Name)
    $p = Join-Path $AT3Dir "CustomHashes.csv"
    if (-not (Test-Path $p)) { return $null }
    foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
        if ($Hash -and (([string]$r.Hash).Trim().ToUpper() -eq $Hash.ToUpper())) { return $r }
        if ($Name -and (([string]$r.Name).Trim() -ieq $Name.Trim())) { return $r }
    }
    return $null
}

function Update-AT3CharacterModel {
    # Rebuilt from live files, never cached to disk as a source of truth -
    # same reason at3names refuses to ship a hash table. A character added
    # since the last run must show up.
    $s = Join-Path $ModToolsDir "char_model.py"
    if (-not (Test-Path $s)) { return $false }
    $r = Invoke-AT3Python -Arguments @($s, "--json", $script:CharModelPath) `
        -Activity "Deriving the character compatibility graph"
    if (-not $r.Ok) { Write-AT3Log ("char_model.py failed: " + $r.Output) }
    return [bool]$r.Ok
}

# Newest write time across the record bundles the graph is derived from.
# Backups (.knockbak, .at3bak, .envbak...) carry a second dot and are skipped,
# exactly as every other tool here does - restoring a backup must not look like
# a content change. ~54 ms over 1,634 files, so it is free to do on open.
function Get-AT3DataNewest {
    try {
        $di = New-Object System.IO.DirectoryInfo (Join-Path $GameRoot "data")
        if (-not $di.Exists) { return [DateTime]::MaxValue }
        $newest = [DateTime]::MinValue
        foreach ($f in $di.EnumerateFiles("*.sm*", [System.IO.SearchOption]::AllDirectories)) {
            if ($f.Name.Split('.').Count -gt 2) { continue }
            if ($f.LastWriteTimeUtc -gt $newest) { $newest = $f.LastWriteTimeUtc }
        }
        return $newest
    } catch {
        return [DateTime]::MaxValue      # cannot tell -> treat as stale
    }
}

# THERE IS NO MANUAL RESCAN, DELIBERATELY.
#
# An earlier version put a "Rebuild Model" button in the creator. It could not
# ever be useful: the creator is modal on the main window, so while it is open
# APPLY CHANGES, the Prop Editor and the Spawns Editor are all unreachable and
# nothing can alter the game files behind the user's back. A button asking them
# to guess whether a rescan is needed is a question they have no way to answer.
#
# The snapshot CAN be stale on OPEN, though - from a previous session, or from
# ModTools scripts run by hand. So the check happens here, automatically, and
# costs ~54 ms. When Layer 3 lands and the creator can write a character, this
# is also where the post-apply refresh belongs.
$script:CharModelNote = ""

function Get-AT3CharacterModel {
    $rebuilt = $false
    $note = ""
    if (-not (Test-Path $script:CharModelPath)) {
        $rebuilt = $true
        $note = "first run - deriving the character graph"
    } else {
        $snap = (Get-Item -LiteralPath $script:CharModelPath).LastWriteTimeUtc
        if ((Get-AT3DataNewest) -gt $snap) {
            $rebuilt = $true
            $note = "game files changed since the last scan - re-derived"
        } else {
            $note = ("options current as of " + $snap.ToLocalTime().ToString("MMM d, HH:mm"))
        }
    }
    if ($rebuilt) { [void](Update-AT3CharacterModel) }
    $script:CharModelNote = $note
    if (-not (Test-Path $script:CharModelPath)) { return $null }
    try {
        return (Get-Content -LiteralPath $script:CharModelPath -Raw | ConvertFrom-Json)
    } catch {
        Write-AT3Log ("CharacterModel.json unreadable: " + $_.Exception.Message)
        return $null
    }
}

# label + combo, as one row. Mirrors New-AT3Field's shape so the two kinds of
# row line up when they sit in the same panel.
function New-AT3ComboRow {
    param([string]$Label, [int]$LabelWidth = 190, [int]$ComboWidth = 320)
    $row = New-Object System.Windows.Controls.DockPanel
    $row.Margin = New-Object System.Windows.Thickness 0,0,0,6
    $lbl = New-Object System.Windows.Controls.TextBlock
    $lbl.Text = $Label
    $lbl.Width = $LabelWidth
    $lbl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $lbl.FontSize = 13
    $lbl.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
    $lbl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    [void]$row.Children.Add($lbl)
    $cmb = New-Object System.Windows.Controls.ComboBox
    $cmb.Width = $ComboWidth
    $cmb.Height = 24
    $cmb.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $cmb.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $cmb.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $cmb.DisplayMemberPath = "Display"
    [void]$row.Children.Add($cmb)
    return @{ Row = $row; Combo = $cmb; Label = $lbl }
}

function New-AT3CreatorTab {
    param([string]$Header, $Content, [switch]$Disabled)
    $ti = New-Object System.Windows.Controls.TabItem
    $ti.Header = $Header
    $ti.IsEnabled = (-not $Disabled)
    $sv = New-Object System.Windows.Controls.ScrollViewer
    $sv.VerticalScrollBarVisibility = "Auto"
    $sv.Padding = New-Object System.Windows.Thickness 12
    $sv.Content = $Content
    $ti.Content = $sv
    return $ti
}

# ===========================================================================
# SPRAY DESIGNER
#
# A collectable spawner is a 43-byte record - what it drops, how many, and
# six parameters governing how hard it sprays. It is authored here rather
# than in a tool of its own for three reasons: six fields is not a tool; a
# spray has no meaning without something to drop it; and the only SAFE
# operation is minting a new record, which is the recipe pipeline's job and
# the pipeline lives here.
#
# NEVER EDIT AN EXISTING SPAWNER. 29 characters share 47188952 - changing it
# would alter every townsfolk in the game. This returns a DEFINITION; the
# build pipeline derives a fresh hash for it the way every other custom
# record in this project is minted.
#
# The parameters beyond count are UNNAMED, deliberately. Only +12 and +16 are
# confirmed. The three vanilla parameter sets are offered as presets - they
# are the only combinations the game itself ships - but every byte stays
# editable, because finding out what these do in game is the point.
#
# Written as a standalone panel so a prop or crate editor can reuse it.
# ===========================================================================
function Show-AT3SprayDesigner {
    param($Model, $Existing)

    $w = New-AT3Panel -Title "Spray Designer" -Width 620 -Height 620 -Accent "plum"
    $sp = New-Object System.Windows.Controls.StackPanel
    $sp.Margin = New-Object System.Windows.Thickness 16

    [void]$sp.Children.Add((New-AT3Note ("A spray is one collectable, a count, and how violently it comes " +
        "out. This never edits an existing spawner - 29 characters share the townsfolk moolah spray, so " +
        "editing it would change every one of them. A new record is minted instead.")))

    [void]$sp.Children.Add((New-AT3Header "---- CONTENT ----" -Accent "plum"))
    $rColl = New-AT3ComboRow -Label "Collectable" -LabelWidth 170 -ComboWidth 330
    [void]$sp.Children.Add($rColl.Row)
    $fCount = New-AT3Field -Label "How many" -Value "3" -Default "3"
    [void]$sp.Children.Add($fCount.Row)
    $residency = New-Object System.Windows.Controls.TextBlock
    $residency.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $residency.FontSize = 11
    $residency.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $residency.Margin = New-Object System.Windows.Thickness 170,0,0,8
    $residency.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
    [void]$sp.Children.Add($residency)

    [void]$sp.Children.Add((New-AT3Header "---- VIOLENCE ----" -Accent "plum"))
    $rPreset = New-AT3ComboRow -Label "Start from" -LabelWidth 170 -ComboWidth 330
    [void]$sp.Children.Add($rPreset.Row)
    [void]$sp.Children.Add((New-AT3Note ("The only parameter sets the game ships. Picking one fills the " +
        "fields below; change anything afterwards and it becomes Custom.")))

    # Every byte of the record that is not the hash, the count or the
    # collectable. Names unknown on purpose - see the header.
    $dials = [ordered]@{}
    foreach ($d in @(
            @("f20", "+20  float",  "3"),
            @("f27", "+27  float",  "6"),
            @("f31", "+31  float",  "0.25"),
            @("f35", "+35  float",  "1.5"),
            @("f39", "+39  float",  "0.3"),
            @("b24", "+24  byte",   "1"),
            @("b25", "+25  byte",   "0"),
            @("b26", "+26  byte",   "0"))) {
        $f = New-AT3Field -Label $d[1] -Value $d[2] -Default $d[2]
        $dials[$d[0]] = $f
        [void]$sp.Children.Add($f.Row)
    }
    [void]$sp.Children.Add((New-AT3Note ("These have NO confirmed meaning. +12 and +16 are the only fields in " +
        "this record anyone has verified. The killer clakker's x8 spray is byte-identical to the Moolah_Large " +
        "x30 apart from count and payload, which is why it sprays hard - but that moved several values at " +
        "once, so it is not evidence about any single one. Change one, launch, write down what happened.")))

    $bar = New-Object System.Windows.Controls.StackPanel
    $bar.Orientation = "Horizontal"
    $bar.Margin = New-Object System.Windows.Thickness 0,10,0,0
    $bOk = New-Object System.Windows.Controls.Button
    $bOk.Content = "Use this spray"; $bOk.Height = 30; $bOk.MinWidth = 140
    $bOk.Margin = New-Object System.Windows.Thickness 0,0,8,0
    $bCancel = New-Object System.Windows.Controls.Button
    $bCancel.Content = "Cancel"; $bCancel.Height = 30; $bCancel.MinWidth = 100
    [void]$bar.Children.Add($bOk)
    [void]$bar.Children.Add($bCancel)
    [void]$sp.Children.Add($bar)

    # Ammo first - it is the reason this designer exists, and there are more
    # ammo collectables (15) than everything else put together (7).
    foreach ($grp in @("ammo", "moolah", "treasure")) {
        foreach ($c in ($Model.collectables | Where-Object { $_.kind -eq $grp })) {
            $reg = @($c.regions)
            [void]$rColl.Combo.Items.Add([pscustomobject]@{
                Display = ("{0,-22} {1,-9} {2}" -f $c.label, ("[" + $c.kind + "]"),
                           $(if ($reg.Count) { "regions " + ($reg -join ",") } else { "NOT RESIDENT ANYWHERE" }))
                Key = $c.hash; Label = $c.label; Kind = $c.kind; Regions = $reg })
        }
    }
    # Presets, taken from the distinct parameter sets the game actually ships.
    $presets = @(
        @{ n = "Ammo crate  (gentle, wide)"; p = @{f20="0";f27="1";f31="0.5";f35="2";f39="0.5";b24="1";b25="1";b26="1"} },
        @{ n = "Townsfolk moolah  (soft)";   p = @{f20="3";f27="6";f31="0.25";f35="1.5";f39="0.3";b24="1";b25="0";b26="0"} },
        @{ n = "Violent  (Moolah_Large / killer clakker)"; p = @{f20="3";f27="9";f31="0.25";f35="5";f39="0.5";b24="1";b25="1";b26="0"} },
        @{ n = "Sniper wasp  (odd one out)"; p = @{f20="6";f27="0.01";f31="0.8";f35="0.9";f39="0.8";b24="1";b25="1";b26="0"} })
    foreach ($pr in $presets) {
        [void]$rPreset.Combo.Items.Add([pscustomobject]@{ Display = $pr.n; Params = $pr.p })
    }

    [void]$rColl.Combo.Add_SelectionChanged({
        $s = $rColl.Combo.SelectedItem
        if (-not $s) { $residency.Text = ""; return }
        if (@($s.Regions).Count) {
            $residency.Text = "resident in region(s): " + (@($s.Regions) -join ", ") +
                              " - anywhere else needs the geometry ported first"
        } else {
            $residency.Text = "NOT RESIDENT IN ANY SHIPPED REGION - this will need porting wherever it is used"
        }
    }.GetNewClosure())

    [void]$rPreset.Combo.Add_SelectionChanged({
        $s = $rPreset.Combo.SelectedItem
        if (-not $s) { return }
        foreach ($k in $s.Params.Keys) { $dials[$k].Box.Text = [string]$s.Params[$k] }
    }.GetNewClosure())

    if ($Existing) {
        foreach ($it in $rColl.Combo.Items) { if ($it.Key -eq $Existing.Collectable) { $rColl.Combo.SelectedItem = $it } }
        $fCount.Box.Text = [string]$Existing.Count
        foreach ($k in $dials.Keys) { if ($Existing.Params.$k -ne $null) { $dials[$k].Box.Text = [string]$Existing.Params.$k } }
    } else {
        $rPreset.Combo.SelectedIndex = 1
        # Moolah_Small, not whatever sorts first - it is the only collectable
        # resident in more than three regions, so it is the one least likely
        # to need a port.
        $rColl.Combo.SelectedIndex = 0
        foreach ($it in $rColl.Combo.Items) {
            if ($it.Label -eq "Moolah_Small") { $rColl.Combo.SelectedItem = $it }
        }
    }

    $w.Tag = $null
    [void]$bOk.Add_Click({
        $c = $rColl.Combo.SelectedItem
        if (-not $c) {
            [void][System.Windows.MessageBox]::Show("Pick a collectable first.", "Spray Designer", "OK", "Warning")
            return
        }
        $n = 0
        if (-not [int]::TryParse($fCount.Box.Text, [ref]$n) -or $n -lt 1 -or $n -gt 100) {
            [void][System.Windows.MessageBox]::Show(
                "How many must be a whole number from 1 to 100. The game's own sprays run 1 to 30.",
                "Spray Designer", "OK", "Warning")
            return
        }
        $p = @{}
        foreach ($k in $dials.Keys) { $p[$k] = $dials[$k].Box.Text }
        $w.Tag = @{
            Collectable = $c.Key; Label = $c.Label; Regions = $c.Regions
            Count = $n; Params = $p }
        $w.DialogResult = $true
        $w.Close()
    }.GetNewClosure())
    [void]$bCancel.Add_Click({ $w.Close() }.GetNewClosure())

    $sv = New-Object System.Windows.Controls.ScrollViewer
    $sv.VerticalScrollBarVisibility = "Auto"
    $sv.Content = $sp
    $w.Content = $sv
    [void]$w.ShowDialog()
    return $w.Tag
}


# ===========================================================================
# BUILD DIALOG
#
# Returns the chosen name, or $null for GO BACK. The result travels on the
# window's Tag, NOT a $script: variable - a $script: value written inside a
# GetNewClosure click handler lands in the closure's own scope and the
# function reads back $null. That is the bug that made the port button
# silently do nothing, and the Spray Designer had it too.
# ===========================================================================
function Show-AT3BuildDialog {
    param([string[]]$Regions, [string]$BaseName, [string[]]$Edits, [string]$Kind = "character")
    $isWeapon = ($Kind -eq "weapon")
    $w = New-AT3Panel -Title $(if ($isWeapon) { "Build Weapon" } else { "Build Character" }) -Width 640 -Height 560 -Accent "plum"
    $sp = New-Object System.Windows.Controls.StackPanel
    $sp.Margin = New-Object System.Windows.Thickness 22

    $msg = New-Object System.Windows.Controls.TextBlock
    if ($isWeapon) {
        $msg.Text = ("You are about to create a new weapon to be resident inside region(s) " + ($Regions -join ", ") +
                     ". This does not arm any character and requires the CHARACTER CREATOR to do so. " +
                     "To proceed, give the weapon a common name and select BUILD.")
    } else {
        $msg.Text = ("You are about to create a new character to be resident inside region(s) " + ($Regions -join ", ") +
                     ". This does not create any spawn instances and requires the SPAWNS EDITOR to do so. " +
                     "To proceed, give the character a common name and select BUILD.")
    }
    $msg.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $msg.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $msg.FontSize = 13
    $msg.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    $msg.Margin = New-Object System.Windows.Thickness 0,0,0,10
    [void]$sp.Children.Add($msg)
    [void]$sp.Children.Add((New-AT3Note ("Cloned from " + $BaseName + ".")))
    $ed = New-Object System.Windows.Controls.TextBlock
    $ed.Tag = "edits"
    $ed.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $ed.FontSize = 11
    $ed.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $ed.Margin = New-Object System.Windows.Thickness 0,0,0,10
    $ed.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    $editList = @($Edits | Where-Object { $_ })
    if ($editList.Count) {
        $et = ("Fields that will be written ({0}):" -f $editList.Count)
        foreach ($x in @($editList | Select-Object -First 14)) { $et += [Environment]::NewLine + "   " + $x }
        if ($editList.Count -gt 14) { $et += [Environment]::NewLine + ("   ...and {0} more" -f ($editList.Count - 14)) }
    } else {
        $et = "No fields changed - this will be an exact copy of " + $BaseName + "."
    }
    $ed.Text = $et
    [void]$sp.Children.Add($ed)

    $txt = New-Object System.Windows.Controls.TextBox
    $txt.Height = 26
    $txt.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $txt.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $txt.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#6A5334")
    $txt.VerticalContentAlignment = [System.Windows.VerticalAlignment]::Center
    [void]$sp.Children.Add($txt)

    $info = New-Object System.Windows.Controls.TextBlock
    $info.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $info.FontSize = 11
    $info.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $info.Margin = New-Object System.Windows.Thickness 0,6,0,12
    $info.Tag = "name-status"
    [void]$sp.Children.Add($info)

    $bar = New-Object System.Windows.Controls.StackPanel
    $bar.Orientation = "Horizontal"
    $bBuild = New-Object System.Windows.Controls.Button
    $bBuild.Content = "BUILD"; $bBuild.Height = 30; $bBuild.MinWidth = 120
    $bBuild.Margin = New-Object System.Windows.Thickness 0,0,10,0
    $bBuild.IsEnabled = $false
    $bBack = New-Object System.Windows.Controls.Button
    $bBack.Content = "GO BACK"; $bBack.Height = 30; $bBack.MinWidth = 120
    [void]$bar.Children.Add($bBuild)
    [void]$bar.Children.Add($bBack)
    [void]$sp.Children.Add($bar)

    # BUILD enables only for a name that can actually be built. A taken hash
    # would alias or overwrite a real record and a reused name makes two
    # indistinguishable library entries, so both keep it disabled.
    $check = {
        $nm = [string]$txt.Text
        $conv = New-Object System.Windows.Media.BrushConverter
        $bBuild.IsEnabled = $false
        if (-not $nm.Trim()) { $info.Text = ""; return }
        $stem = ConvertTo-AT3Stem -Name $nm
        if (-not $stem) {
            $info.Text = "That name has no letters or digits, so it cannot form a stem."
            $info.Foreground = $conv.ConvertFromString("#D97A6A"); return
        }
        $h = Get-AT3StemHash -Stem $stem -Kind $Kind
        $head = "stem " + $stem + "   hash " + $h
        $byHash = Find-AT3CustomHash -Hash $h
        $byName = Find-AT3CustomHash -Name $nm
        if (Test-AT3HashResident -Hash $h) {
            $who = if ($byHash) { "'" + [string]$byHash.Name + "'" } else { "an existing game record" }
            $info.Text = $head + [Environment]::NewLine + "TAKEN - that hash already belongs to " + $who + ". Choose another name."
            $info.Foreground = $conv.ConvertFromString("#D97A6A"); return
        }
        # A weapon mints a second hash for its own effect record; both must be free.
        if ($isWeapon) {
            $he = Get-AT3StemHash -Stem $stem -Kind "effect"
            $head += "   effect " + $he
            if (Test-AT3HashResident -Hash $he) {
                $info.Text = $head + [Environment]::NewLine + "TAKEN - the effect-record hash for that name already exists. Choose another name."
                $info.Foreground = $conv.ConvertFromString("#D97A6A"); return
            }
        }
        if ($byName) {
            $info.Text = $head + [Environment]::NewLine + "NAME IN USE - '" + [string]$byName.Name + "' is already " + ([string]$byName.Hash).ToUpper() + " in the library."
            $info.Foreground = $conv.ConvertFromString("#D9A441"); return
        }
        $info.Text = $head + [Environment]::NewLine + "available"
        $info.Foreground = $conv.ConvertFromString("#8FBF7A")
        $bBuild.IsEnabled = $true
    }.GetNewClosure()
    [void]$txt.Add_TextChanged({ & $check }.GetNewClosure())

    $w.Tag = $null
    [void]$bBack.Add_Click({ $w.Tag = $null; $w.DialogResult = $false; $w.Close() }.GetNewClosure())
    [void]$bBuild.Add_Click({
        $w.Tag = ([string]$txt.Text).Trim() -replace '"', ''
        $w.DialogResult = $true
        $w.Close()
    }.GetNewClosure())
    [void]$w.Add_Loaded({ [void]$txt.Focus() }.GetNewClosure())

    $w.Content = $sp
    $r = $w.ShowDialog()
    if ($r -eq $true -and $w.Tag) { return [string]$w.Tag }
    return $null
}


# ===========================================================================
# CHARACTER CREATOR FIELD HELPERS
#
# Functions, not scriptblocks: GetNewClosure handlers can call functions
# safely, but a $script: read inside such a handler resolves to the closure's
# own scope (see memory getnewclosure-script-scope).
# ===========================================================================
function New-AT3FieldEntry {
    param([string]$Kind, $Ctl, [string[]]$Fields)
    $el = if ($Kind -eq "check") { $Ctl } else { $Ctl.Row }
    return @{ Kind = $Kind; Ctl = $Ctl; Fields = $Fields; Tip = $el.ToolTip }
}

function Set-AT3FieldValue {
    param($Entry, $Value)
    switch ($Entry.Kind) {
        "text" {
            # ConvertFrom-Json hands floats back as [decimal] - 1500.0 shows as
            # "1500.0" and 191.000015 as "191.000015". Show float32 precision.
            $shown = if ($null -eq $Value) { "" }
                     elseif ($Value -is [double] -or $Value -is [decimal] -or $Value -is [single]) {
                         ([double]$Value).ToString("G7", [System.Globalization.CultureInfo]::InvariantCulture) }
                     else { [string]$Value }
            $Entry.Ctl.Box.Text = $shown
            $Entry.Ctl.Box.Tag = $(if ($null -eq $Value) { $null } else { $shown })
            foreach ($c in $Entry.Ctl.Row.Children) {
                if ($c -is [System.Windows.Controls.Button]) {
                    $c.ToolTip = $(if ($null -eq $Value) { "Reset" } else { "Reset to this base's value (" + $shown + ")" })
                }
            }
        }
        "check" { $Entry.Ctl.IsChecked = ($null -ne $Value -and [string]$Value -ne "0") }
        "combo" {
            $cb = $Entry.Ctl.Combo
            $pick = $null
            foreach ($it in $cb.Items) { if ([string]$it.Key -eq [string]$Value) { $pick = $it; break } }
            $cb.SelectedItem = $pick
        }
        "multi" {
            # A list of hashes -> one checkbox each. Duplicates collapse on
            # screen; collectEdits keeps them when the set is unchanged.
            $on = @{}
            foreach ($x in @($Value)) { if ($x) { $on[([string]$x).ToUpper()] = $true } }
            foreach ($k in @($Entry.Ctl.Boxes.Keys)) { $Entry.Ctl.Boxes[$k].IsChecked = $on.ContainsKey(([string]$k).ToUpper()) }
        }
        "attach" { & $Entry.Ctl.Set $Value }
        # A control with its own Set/Get (spawn on gib): the value is plain, so
        # collectEdits compares it like any text or combo field.
        "custom" { & $Entry.Ctl.Set $Value }
    }
}

function Get-AT3FieldValue {
    param($Entry)
    switch ($Entry.Kind) {
        "text"  { return ([string]$Entry.Ctl.Box.Text).Trim() }
        "check" { if ($Entry.Ctl.IsChecked) { return 1 } else { return 0 } }
        "combo" { $it = $Entry.Ctl.Combo.SelectedItem; if ($it) { return $it.Key } else { return $null } }
        "multi" { return ,@(@($Entry.Ctl.Boxes.Keys) | Where-Object { $Entry.Ctl.Boxes[$_].IsChecked }) }
        "attach" { return ,@((& $Entry.Ctl.Get).List) }
        "custom" { return (& $Entry.Ctl.Get) }
    }
}

function Set-AT3FieldEnabled {
    param($Entry, [bool]$On, [string]$Why)
    $el = if ($Entry.Kind -eq "check") { $Entry.Ctl } else { $Entry.Ctl.Row }
    $el.IsEnabled = $On
    [System.Windows.Controls.ToolTipService]::SetShowOnDisabled($el, $true)
    if ($On) { $el.ToolTip = $Entry.Tip }
    else { $el.ToolTip = "Not editable here: " + $Why + $(if ($Entry.Tip) { "   (" + [string]$Entry.Tip + ")" } else { "" }) }
}

function Test-AT3FieldSame {
    # Numbers compare with a float32 tolerance; everything else as text,
    # case-insensitively (hashes). Empty and $null are the same thing.
    param($A, $B)
    $sa = if ($null -eq $A) { "" } else { ([string]$A).Trim() }
    $sb = if ($null -eq $B) { "" } else { ([string]$B).Trim() }
    if ($sa -eq $sb) { return $true }
    if ($sa -eq "" -or $sb -eq "") { return $false }
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $sty = [System.Globalization.NumberStyles]::Float
    $fa = 0.0; $fb = 0.0
    if ($sa -match '^[0-9+\-.eE]+$' -and $sb -match '^[0-9+\-.eE]+$' -and
        [double]::TryParse($sa, $sty, $inv, [ref]$fa) -and [double]::TryParse($sb, $sty, $inv, [ref]$fb) -and
        -not [double]::IsInfinity($fa) -and -not [double]::IsInfinity($fb)) {
        return ([math]::Abs($fa - $fb) -le 1e-4 * [math]::Max(1.0, [math]::Abs($fb)))
    }
    return ($sa.ToUpperInvariant() -eq $sb.ToUpperInvariant())
}


# ===========================================================================
# ATTACHMENT BLOCKS (Character Creator > Attachments)
#
# One block per m_defaultAttachments entry: bone, mesh, position, rotation,
# scale. Built by FUNCTIONS so each block's handlers close over this call's own
# locals - a handler created inside a form-level closure cannot see that
# closure's captures (memory getnewclosure-script-scope).
#
# An untouched number goes back as the model's own value, never re-parsed from
# its box: G7 text does not always round-trip a float32, and an entry nobody
# changed must be written back byte for byte. The same goes for rotation - the
# stored matrix is sent unless one of its three angle boxes was edited.
# ===========================================================================
function New-AT3MiniLabel {
    param([string]$Text, [int]$Width = 0, [string]$Tip = "")
    $l = New-Object System.Windows.Controls.TextBlock
    $l.Text = $Text
    if ($Width) { $l.Width = $Width }
    $l.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
    $l.Margin = New-Object System.Windows.Thickness 0,0,4,0
    $l.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $l.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    if ($Tip) { $l.ToolTip = $Tip }
    return $l
}

function New-AT3MiniBox {
    param([string]$Text, [int]$Width = 54, [string]$Tip = "")
    $conv = New-Object System.Windows.Media.BrushConverter
    $t = New-Object System.Windows.Controls.TextBox
    $t.Text = $Text
    $t.Width = $Width
    $t.Height = 22
    $t.Margin = New-Object System.Windows.Thickness 0,0,10,0
    $t.VerticalContentAlignment = [System.Windows.VerticalAlignment]::Center
    $t.Background = $conv.ConvertFromString("#2A1F16")
    $t.Foreground = $conv.ConvertFromString("#F2E4C4")
    $t.BorderBrush = $conv.ConvertFromString("#6B4E36")
    if ($Tip) { $t.ToolTip = $Tip }
    return $t
}

function New-AT3MiniCombo {
    param([int]$Width = 200)
    $conv = New-Object System.Windows.Media.BrushConverter
    $c = New-Object System.Windows.Controls.ComboBox
    $c.Width = $Width
    $c.Height = 24
    $c.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $c.FontSize = 11
    $c.Background = $conv.ConvertFromString("#2A1F16")
    $c.Foreground = $conv.ConvertFromString("#F2E4C4")
    $c.DisplayMemberPath = "Display"
    return $c
}

# The bones an attachment may name: the chosen mesh's own rig when one is
# chosen (every character mesh references exactly one rig record), otherwise
# every bone on any rig of the skeleton. Bones shipped characters of this
# skeleton hang gear from are listed first.
function Get-AT3AttachBoneItems {
    param($Model, [string]$Skel, [string]$GeoHash)
    if (-not $Model -or -not $Skel) { return }
    $sk = $Model.skeletons.PSObject.Properties[$Skel]
    if (-not $sk) { return }
    $bones = @()
    if ($GeoHash) {
        foreach ($g in $sk.Value.geometries.PSObject.Properties) {
            if ([string]$g.Value.hash -eq $GeoHash -and @($g.Value.bones).Count) { $bones = @($g.Value.bones); break }
        }
    }
    if (-not $bones.Count) { $bones = @($sk.Value.bones) }
    $worn = @{}
    if ($sk.Value.worn_bones) { foreach ($p in $sk.Value.worn_bones.PSObject.Properties) { $worn[$p.Name] = [int]$p.Value } }
    $first = @($bones | Where-Object { $worn.ContainsKey($_) } | Sort-Object @{ Expression = { -$worn[$_] } }, @{ Expression = { $_ } })
    foreach ($bn in @($first + @($bones | Where-Object { -not $worn.ContainsKey($_) }))) {
        [pscustomobject]@{
            Display = $(if ($worn.ContainsKey($bn)) { "{0,-24} worn {1}x on this skeleton" -f $bn, $worn[$bn] } else { [string]$bn })
            Key = [string]$bn }
    }
}

function Get-AT3AttachRigText {
    param($Model, [string]$Skel, [string]$GeoHash, [int]$Count)
    if (-not $Skel) { return "Choose a Skeletal Species on the Anatomy tab - attachments hang from its bones." }
    if ($Model -and $GeoHash) {
        $sk = $Model.skeletons.PSObject.Properties[$Skel]
        if ($sk) {
            foreach ($g in $sk.Value.geometries.PSObject.Properties) {
                if ([string]$g.Value.hash -eq $GeoHash -and @($g.Value.bones).Count) {
                    return ("Bones: the {0} bones of {1}'s rig (record {2}). 'worn' marks bones shipped {3} characters hang gear from." -f
                            $Count, $g.Name, $g.Value.rig, $Skel)
                }
            }
        }
    }
    return ("Bones: every bone on any {0} rig ({1}). Choose a Character Geometry on Anatomy for that mesh's exact rig - a bone the mesh lacks renders nothing." -f $Skel, $Count)
}

# Keeps the current bone. One the new rig lacks stays selected, labelled - a
# silent swap to another bone would move the gear without saying so.
function Set-AT3AttachBoneChoices {
    param($Combo, $Items, [string]$Keep)
    $Combo.Items.Clear()
    $pick = $null
    foreach ($it in @($Items)) {
        [void]$Combo.Items.Add($it)
        if ($Keep -and [string]$it.Key -ceq $Keep) { $pick = $it }
    }
    if ($Keep -and -not $pick) {
        $pick = [pscustomobject]@{ Display = ("{0,-24} NOT in this mesh's rig - will not render" -f $Keep); Key = $Keep }
        [void]$Combo.Items.Insert(0, $pick)
    }
    if ($pick) { $Combo.SelectedItem = $pick }
    elseif ($Combo.Items.Count) { $Combo.SelectedIndex = 0 }
}

function Get-AT3AttachGeoItems {
    param($Model)
    foreach ($g in @($Model.attachment_geos)) {
        $wb = @($g.worn_by)
        $where = if ($g.global) { "global" } elseif (@($g.regions).Count) { "in " + (@($g.regions) -join ",") } else { "nowhere" }
        $fold = ([string]$g.folder) -replace '^geometry\\attachments\\?', ''
        [pscustomobject]@{
            Display = ("{0,-34} {1,-20} {2}{3}" -f $g.name, $fold, $where, $(if ($wb.Count) { "   worn by " + ($wb -join ", ") } else { "" }))
            Key = [string]$g.hash; Name = [string]$g.name }
    }
}

function New-AT3AttachmentBlock {
    param($State, $Entry)
    $conv = New-Object System.Windows.Media.BrushConverter
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $border = New-Object System.Windows.Controls.Border
    $border.BorderBrush = $conv.ConvertFromString("#4A3524")
    $border.BorderThickness = New-Object System.Windows.Thickness 1
    $border.Padding = New-Object System.Windows.Thickness 8,6,8,6
    $border.Margin = New-Object System.Windows.Thickness 0,0,0,8
    $stack = New-Object System.Windows.Controls.StackPanel
    $border.Child = $stack

    $row1 = New-Object System.Windows.Controls.StackPanel
    $row1.Orientation = "Horizontal"
    $row1.Margin = New-Object System.Windows.Thickness 0,0,0,6
    [void]$row1.Children.Add((New-AT3MiniLabel -Text "Bone" -Width 38 -Tip "m_boneToAttachTo - a bone of the body mesh's rig. A name the rig lacks renders nothing, with no error."))
    $bone = New-AT3MiniCombo -Width 230
    [void]$row1.Children.Add($bone)
    $ml = New-AT3MiniLabel -Text "Mesh" -Width 38 -Tip "m_geoToAttach - the mesh worn on that bone."
    $ml.Margin = New-Object System.Windows.Thickness 14,0,4,0
    [void]$row1.Children.Add($ml)
    $geo = New-AT3MiniCombo -Width 350
    [void]$row1.Children.Add($geo)
    $rm = New-Object System.Windows.Controls.Button
    $rm.Content = "Remove"
    $rm.Height = 24
    $rm.MinWidth = 72
    $rm.Margin = New-Object System.Windows.Thickness 12,0,0,0
    [void]$row1.Children.Add($rm)
    [void]$stack.Children.Add($row1)

    $tr = @(0, 0, 0); $eu = @(0, 0, 0); $sc = 1
    if ($Entry) { $tr = @($Entry.tr); $eu = @($Entry.euler); $sc = $Entry.scale }
    $shown = @{ Pos = @("", "", ""); Rot = @("", "", ""); Scale = "" }
    $pos = @(); $rot = @()
    $row2 = New-Object System.Windows.Controls.StackPanel
    $row2.Orientation = "Horizontal"
    $axis = @("X", "Y", "Z")
    $posTip = @("X - lateral: + moves it to the character's left", "Y - depth: + moves it backward", "Z - vertical: + moves it up")
    [void]$row2.Children.Add((New-AT3MiniLabel -Text "Position" -Width 58 -Tip "In the bone's own frame, in world units - the Killer Clakker's shovel hangs 1.5 below its hand."))
    foreach ($j in 0..2) {
        $t = ([double]$tr[$j]).ToString("G7", $inv)
        $shown.Pos[$j] = $t
        [void]$row2.Children.Add((New-AT3MiniLabel -Text $axis[$j] -Tip $posTip[$j]))
        $bx = New-AT3MiniBox -Text $t -Tip $posTip[$j]
        $pos += $bx
        [void]$row2.Children.Add($bx)
    }
    $rl = New-AT3MiniLabel -Text "Rotation" -Width 58 -Tip "Degrees about X, then Y, then Z. Which way each one turns has not been checked in game."
    $rl.Margin = New-Object System.Windows.Thickness 8,0,4,0
    [void]$row2.Children.Add($rl)
    foreach ($j in 0..2) {
        $t = ([double]$eu[$j]).ToString("G7", $inv)
        $shown.Rot[$j] = $t
        [void]$row2.Children.Add((New-AT3MiniLabel -Text $axis[$j]))
        $bx = New-AT3MiniBox -Text $t -Width 50 -Tip ("Degrees about " + $axis[$j])
        $rot += $bx
        [void]$row2.Children.Add($bx)
    }
    $sl = New-AT3MiniLabel -Text "Scale" -Tip "1 = the mesh's authored size. Retail uses 0.5 to 1."
    $sl.Margin = New-Object System.Windows.Thickness 8,0,4,0
    [void]$row2.Children.Add($sl)
    $shown.Scale = ([double]$sc).ToString("G7", $inv)
    $scale = New-AT3MiniBox -Text $shown.Scale -Width 50 -Tip "1 = the mesh's authored size."
    [void]$row2.Children.Add($scale)
    [void]$stack.Children.Add($row2)

    Set-AT3AttachBoneChoices -Combo $bone -Items @(Get-AT3AttachBoneItems -Model $State.Model -Skel $State.Skel -GeoHash $State.GeoHash) `
        -Keep $(if ($Entry) { [string]$Entry.bone } else { "" })
    foreach ($it in @($State.GeoItems)) { [void]$geo.Items.Add($it) }
    [void]$geo.Items.Add([pscustomobject]@{ Display = "Choose other Geometry..."; Key = "OTHER"; Name = "" })
    if ($Entry) {
        $pick = $null
        foreach ($it in $geo.Items) { if ([string]$it.Key -eq [string]$Entry.geo) { $pick = $it; break } }
        if (-not $pick) {
            $pick = [pscustomobject]@{ Display = ("{0,-34} other geometry" -f ("mesh " + [string]$Entry.geo)); Key = [string]$Entry.geo; Name = "" }
            $geo.Items.Insert($geo.Items.Count - 1, $pick)
        }
        $geo.SelectedItem = $pick
    }

    $blk = @{ Panel = $border; Bone = $bone; Geo = $geo; Pos = $pos; Rot = $rot; Scale = $scale; Base = $Entry; Shown = $shown; Remove = $rm }

    # "Choose other Geometry..." - the Weapon Creator's projectile pattern: a
    # pick becomes a real entry above the command, a cancel restores the last.
    $gs = @{ Last = $geo.SelectedItem; Busy = $false }
    [void]$geo.Add_SelectionChanged({
        if ($gs.Busy) { return }
        $sel = $geo.SelectedItem
        if (-not $sel -or [string]$sel.Key -ne "OTHER") {
            $gs.Last = $sel
            if ($State.Validate) { & $State.Validate }
            return
        }
        $gs.Busy = $true
        try {
            $g = Show-AT3GeometryPicker -Purpose "attachment"
            if ($g) {
                $item = $null
                foreach ($it in $geo.Items) { if ([string]$it.Key -eq [string]$g.Hash) { $item = $it; break } }
                if (-not $item) {
                    $gw = if ($g.Global) { "global" } elseif (@($g.Regions).Count) { "in " + (@($g.Regions) -join ",") } else { "nowhere" }
                    $item = [pscustomobject]@{ Display = ("{0,-34} other geometry       {1}" -f $g.Name, $gw); Key = [string]$g.Hash; Name = [string]$g.Name }
                    $geo.Items.Insert($geo.Items.Count - 1, $item)
                }
                $geo.SelectedItem = $item
                $gs.Last = $item
                if ($State.Status) {
                    $State.Status.Text = ("Attachment mesh set to " + $g.Name + " - ported with its textures when you build or save. A mesh " +
                                          "not authored as an attachment hangs from its own pivot, so expect to adjust position, rotation and scale.")
                }
            } else {
                $geo.SelectedItem = $gs.Last
            }
        } finally { $gs.Busy = $false }
        if ($State.Validate) { & $State.Validate }
    }.GetNewClosure())
    [void]$bone.Add_SelectionChanged({ if ($State.Validate) { & $State.Validate } }.GetNewClosure())
    foreach ($tb in @($pos + $rot + @($scale))) {
        [void]$tb.Add_TextChanged({ if ($State.Validate) { & $State.Validate } }.GetNewClosure())
    }
    [void]$rm.Add_Click({
        [void]$State.List.Children.Remove($blk.Panel)
        [void]$State.Entries.Remove($blk)
        Update-AT3AttachHeader -State $State
        if ($State.Validate) { & $State.Validate }
    }.GetNewClosure())
    return $blk
}

function Add-AT3AttachBlock {
    param($State, $Entry)
    $blk = New-AT3AttachmentBlock -State $State -Entry $Entry
    [void]$State.Entries.Add($blk)
    [void]$State.List.Children.Add($blk.Panel)
    return $blk
}

function Update-AT3AttachHeader {
    param($State)
    $n = $State.Entries.Count
    $State.Count.Text = $(if ($n -ge 16) { "16 attachments - the most one character can carry here" } else { "{0} attachment(s)" -f $n })
    $State.AddButton.IsEnabled = ($n -lt 16)
}

function Update-AT3AttachBones {
    param($State)
    $items = @(Get-AT3AttachBoneItems -Model $State.Model -Skel $State.Skel -GeoHash $State.GeoHash)
    foreach ($blk in $State.Entries) {
        $keep = if ($blk.Bone.SelectedItem) { [string]$blk.Bone.SelectedItem.Key } else { "" }
        Set-AT3AttachBoneChoices -Combo $blk.Bone -Items $items -Keep $keep
    }
    if ($State.Rig) { $State.Rig.Text = Get-AT3AttachRigText -Model $State.Model -Skel $State.Skel -GeoHash $State.GeoHash -Count $items.Count }
}

function Set-AT3AttachList {
    param($State, $List)
    $State.List.Children.Clear()
    $State.Entries.Clear()
    foreach ($e in @($List)) { if ($null -ne $e) { [void](Add-AT3AttachBlock -State $State -Entry $e) } }
    $State.BaseCanon = Get-AT3AttachCanon -State $State
    Update-AT3AttachHeader -State $State
}

# What the boxes show, as one string - unchanged from the base means nothing
# is sent, whatever the numbers would parse to.
function Get-AT3AttachCanon {
    param($State)
    $parts = foreach ($blk in $State.Entries) {
        $vals = @([string]$blk.Bone.SelectedItem.Key, [string]$blk.Geo.SelectedItem.Key)
        foreach ($tb in @($blk.Pos + $blk.Rot + @($blk.Scale))) { $vals += $tb.Text.Trim() }
        $vals -join "|"
    }
    return (@($parts) -join ";")
}

function Get-AT3AttachList {
    param($State)
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $sty = [System.Globalization.NumberStyles]::Float
    foreach ($blk in $State.Entries) {
        $e = [ordered]@{ bone = [string]$blk.Bone.SelectedItem.Key; geo = [string]$blk.Geo.SelectedItem.Key }
        $base = $blk.Base
        $tr = @()
        foreach ($j in 0..2) {
            $t = $blk.Pos[$j].Text.Trim()
            if ($base -and $t -eq $blk.Shown.Pos[$j]) { $tr += $base.tr[$j] }
            else { $v = 0.0; [void][double]::TryParse($t, $sty, $inv, [ref]$v); $tr += $v }
        }
        $e["tr"] = $tr
        $rotEdited = @(0..2 | Where-Object { $blk.Rot[$_].Text.Trim() -ne $blk.Shown.Rot[$_] }).Count
        if ($base -and -not $rotEdited) {
            $e["rot"] = @($base.rot)
        } else {
            $eu = @()
            foreach ($j in 0..2) { $v = 0.0; [void][double]::TryParse($blk.Rot[$j].Text.Trim(), $sty, $inv, [ref]$v); $eu += $v }
            $e["euler"] = $eu
        }
        $t = $blk.Scale.Text.Trim()
        if ($base -and $t -eq $blk.Shown.Scale) { $e["scale"] = $base.scale }
        else { $v = 1.0; [void][double]::TryParse($t, $sty, $inv, [ref]$v); $e["scale"] = $v }
        $e
    }
}

function Get-AT3AttachProblem {
    param($State)
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $sty = [System.Globalization.NumberStyles]::Float
    $i = 0
    foreach ($blk in $State.Entries) {
        $i++
        if (-not $blk.Bone.SelectedItem) { return ("attachment {0} needs a bone" -f $i) }
        $g = $blk.Geo.SelectedItem
        if (-not $g -or [string]$g.Key -eq "OTHER") { return ("attachment {0} needs a mesh" -f $i) }
        foreach ($j in 0..2) {
            $v = 0.0
            if (-not [double]::TryParse($blk.Pos[$j].Text.Trim(), $sty, $inv, [ref]$v) -or [math]::Abs($v) -gt 100) {
                return ("attachment {0}: Position {1} must be a number within +/-100" -f $i, @("X", "Y", "Z")[$j])
            }
            if (-not [double]::TryParse($blk.Rot[$j].Text.Trim(), $sty, $inv, [ref]$v) -or [double]::IsInfinity($v)) {
                return ("attachment {0}: Rotation {1} must be a number of degrees" -f $i, @("X", "Y", "Z")[$j])
            }
        }
        $v = 0.0
        if (-not [double]::TryParse($blk.Scale.Text.Trim(), $sty, $inv, [ref]$v) -or $v -le 0 -or $v -gt 100) {
            return ("attachment {0}: Scale must be above 0 and at most 100" -f $i)
        }
    }
    return ""
}

# One line per edit for the confirm box and the log - an attachment list as
# bone=mesh pairs rather than a type name.
function Format-AT3EditLines {
    param($Edits)
    foreach ($k in @($Edits.Keys)) {
        $v = $Edits[$k]
        if ($k -eq "m_defaultAttachments") {
            $l = @($v)
            $k + " = " + ("{0} attachment(s)" -f $l.Count) + $(if ($l.Count) { ": " + (@($l | ForEach-Object { [string]$_["bone"] + "=" + [string]$_["geo"] }) -join ", ") } else { "" })
        } elseif ($v -is [System.Collections.IDictionary] -and $v.Contains("spray")) {
            $s = $v["spray"]
            $k + " = custom spray: " + [string]$s["collectable"] + " x" + [string]$s["count"] + "  " +
                (@($s["params"].Keys | Sort-Object | ForEach-Object { $_ + "=" + [string]$s["params"][$_] }) -join " ")
        } elseif ($null -eq $v) {
            $k + " = (nothing)"
        } else {
            $k + " = " + [string]$v
        }
    }
}


# Message boxes as functions, so a headless test can answer them and the
# windows that raise them stay testable end to end.
function Confirm-AT3Choice {
    param([string]$Text, [string]$Title)
    return ([System.Windows.MessageBox]::Show($Text, $Title, "YesNo", "Warning") -eq "Yes")
}

function Show-AT3Notice {
    param([string]$Text, [string]$Title, [string]$Icon = "Information")
    [void][System.Windows.MessageBox]::Show($Text, $Title, "OK", $Icon)
}

# ===========================================================================
# CHARACTER LIBRARY PICKER  (Character Studio > Edit Existing)
#
# Every character the model knows - the game's own and this project's - with
# the skeleton and template it belongs to, so the Character Creator can open on
# it exactly as if it had been chosen as a base.
# ===========================================================================
function Show-AT3CharacterLibraryPicker {
    Use-AT3Catalogue
    # -Purpose "gib" reuses the library to choose the character another one
    # spawns when it gibs; the default opens a character for editing.
    param([string]$Purpose = "edit")
    $model = Get-AT3CharacterModel
    if (-not $model) {
        Show-AT3Notice -Title "Character Library" -Icon "Warning" -Text "CharacterModel.json could not be built. See at3_debug.log."
        return $null
    }
    $spawns = @{}
    $gc = Join-Path $RegionDataDir "GlobalCatalogue.csv"
    if (Test-Path $gc) {
        foreach ($r in @(Import-Csv -LiteralPath $gc -ErrorAction SilentlyContinue)) { $spawns[([string]$r.Hash).ToUpper()] = [string]$r.Spawns }
    }
    $rows = New-Object System.Collections.ArrayList
    foreach ($sk in $model.skeletons.PSObject.Properties) {
        foreach ($tp in $sk.Value.templates.PSObject.Properties) {
            foreach ($c in @($tp.Value.characters)) {
                $hp = ""
                if ($c.values -and $null -ne $c.values.m_health) {
                    $hp = ([double]$c.values.m_health).ToString("G7", [System.Globalization.CultureInfo]::InvariantCulture)
                }
                [void]$rows.Add([pscustomobject]@{
                    Name = [string]$c.name; Hash = [string]$c.hash; Template = [string]$tp.Name; Skel = [string]$sk.Name
                    Tmpl = [string]$tp.Name; Origin = [string]$c.origin; HP = $hp
                    Spawns = $(if ($spawns.ContainsKey([string]$c.hash)) { $spawns[[string]$c.hash] } else { "" })
                    Regions = (@($c.regions) -join ","); Rec = $c
                    Search = ([string]$c.name + " " + [string]$c.hash + " " + [string]$tp.Name + " " + [string]$sk.Name + " " +
                              [string]$c.origin).ToLowerInvariant() })
            }
        }
    }
    $sorted = New-Object System.Collections.ArrayList
    foreach ($x in @($rows | Sort-Object @{ Expression = { $_.Name } })) { [void]$sorted.Add($x) }
    $note = ("Every character in the game's files - {0} of them, the game's own and the ones you built. Pick one to edit it " +
        "IN PLACE: it keeps its hash, so every spawn of it in the regions you save to changes too. Search matches every " +
        "word you type, in the name, hash, template, skeleton or origin (stock / custom).") -f $sorted.Count
    $title = "Character Library"; $ok = "Edit this character"
    if ($Purpose -eq "gib") {
        $title = "Spawn on Gib"; $ok = "Spawn this character"
        $note = ("Every character in the game's files - {0} of them. The one you pick takes this character's place when it " +
            "gibs. It is ported, with its mesh, animations and weapons, into each region you build or save to that lacks it " +
            "- the Regions column says where it already lives. Search matches every word you type, in the name, hash, " +
            "template, skeleton or origin.") -f $sorted.Count
    }
    return (Show-AT3SearchPicker -Title $title -Note $note -Items $sorted -OkText $ok `
        -Noun "characters" -Width 1000 -Columns @(
            @{ H = "Character"; B = "Name";     W = 0 },
            @{ H = "Hash";      B = "Hash";     W = 80 },
            @{ H = "Template";  B = "Template"; W = 190 },
            @{ H = "Origin";    B = "Origin";   W = 70 },
            @{ H = "HP";        B = "HP";       W = 70 },
            @{ H = "Spawns";    B = "Spawns";   W = 60 },
            @{ H = "Regions";   B = "Regions";  W = 150 }))
}

# The Character Creator opens on a CHOICE, not on the form. Starting straight
# in the editor presents a blank Anatomy tab with no indication that loading an
# existing character is even possible, and "Create New" as a button inside the
# form reads as "discard what I am looking at" rather than "begin".
function Show-AT3CharacterCreator {
    $w = New-AT3Panel -Title "Character Studio" -Width 560 -Height 330 -Accent "plum"
    $sp = New-Object System.Windows.Controls.StackPanel
    $sp.Margin = New-Object System.Windows.Thickness 22

    $ttl = New-Object System.Windows.Controls.TextBlock
    $ttl.Text = "Welcome to the Character Studio"
    $ttl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $ttl.FontSize = 17
    $ttl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#D9A0D0")
    $ttl.Margin = New-Object System.Windows.Thickness 0,0,0,16
    [void]$sp.Children.Add($ttl)

    $bNew = New-Object System.Windows.Controls.Button
    $bNew.Content = "Create New"
    $bNew.Height = 34
    $bNew.FontSize = 13
    $bNew.Margin = New-Object System.Windows.Thickness 0,0,0,4
    [void]$sp.Children.Add($bNew)
    [void]$sp.Children.Add((New-AT3Note "Create a new character and choose which regions it's resident in."))

    $bLoad = New-Object System.Windows.Controls.Button
    $bLoad.Content = "Edit Existing"
    $bLoad.Height = 34
    $bLoad.FontSize = 13
    $bLoad.Margin = New-Object System.Windows.Thickness 0,8,0,4
    [void]$sp.Children.Add($bLoad)
    [void]$sp.Children.Add((New-AT3Note ("Change attributes of a character that already exists. These changes will affect " +
        "all spawns of this character across all regions.")))

    $w.Tag = $null
    [void]$bNew.Add_Click({ $w.Tag = "new"; $w.DialogResult = $true; $w.Close() }.GetNewClosure())
    [void]$bLoad.Add_Click({ $w.Tag = "edit"; $w.DialogResult = $true; $w.Close() }.GetNewClosure())

    $w.Content = $sp
    $r = $w.ShowDialog()
    if ($r -ne $true) { return }
    if ($w.Tag -eq "edit") {
        $pick = Show-AT3CharacterLibraryPicker
        if ($pick) { Show-AT3CharacterCreatorForm -EditTarget $pick }
    } else {
        Show-AT3CharacterCreatorForm
    }
}

function Show-AT3CharacterCreatorForm {
    # -EditTarget (a Show-AT3CharacterLibraryPicker row) opens the form ON an
    # existing character: it is preselected as the base and locked, and Save
    # writes the changed fields back into that record in place
    # (edit_character.py) instead of building a new one.
    param($EditTarget)
    $editing = [bool]$EditTarget
    $w = New-AT3Panel -Title $(if ($editing) { "Character Editor - " + [string]$EditTarget.Name } else { "Character Creator" }) `
        -Width 880 -Height 700 -Accent "plum"

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 12

    # --- status line, docked bottom so it is always visible -----------------
    $status = New-Object System.Windows.Controls.TextBlock
    $status.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $status.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $status.FontSize = 11
    $status.Margin = New-Object System.Windows.Thickness 0,10,0,0
    $status.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    [void][System.Windows.Controls.DockPanel]::SetDock($status, "Bottom")
    [void]$root.Children.Add($status)

    $model = Get-AT3CharacterModel
    if (-not $model) {
        $status.Text = "CharacterModel.json could not be built. See at3_debug.log."
    }

    # --- top bar: Create New / Load Preset / Rebuild ------------------------
    $top = New-Object System.Windows.Controls.StackPanel
    $top.Orientation = "Horizontal"
    $top.Margin = New-Object System.Windows.Thickness 0,0,0,10
    [void][System.Windows.Controls.DockPanel]::SetDock($top, "Top")
    # "Create New" / "Load Existing" moved to the chooser that opens first, and
    # there is no rescan button - see Get-AT3CharacterModel for why. That
    # leaves exactly one thing the user can do to the form itself.
    foreach ($spec in @(, @($(if ($editing) { "Reset" } else { "Clear All" }), "new"))) {
        $b = New-Object System.Windows.Controls.Button
        $b.Content = $spec[0]
        $b.Tag = $spec[1]
        $b.Height = 26
        $b.MinWidth = 120
        $b.Margin = New-Object System.Windows.Thickness 0,0,8,0
        $b.FontSize = 12
        [void]$top.Children.Add($b)
    }
    [void]$root.Children.Add($top)

    # =======================================================================
    # ANATOMY
    # =======================================================================
    $an = New-Object System.Windows.Controls.StackPanel
    [void]$an.Children.Add((New-AT3Note ("Determines how the character looks and acts, and which weapons it can " +
        "meaningfully carry. Incompatible picks are allowed - they produce a visually odd character, not a broken " +
        "one. The engine falls back to a T-pose where a template has no animation for something.")))

    [void]$an.Children.Add((New-AT3Header "---- BASE ----" -Accent "plum"))
    $rSkel = New-AT3ComboRow -Label "Skeletal Species"
    $rTmpl = New-AT3ComboRow -Label "Behavioral Template"
    $rGeo  = New-AT3ComboRow -Label "Character Geometry"
    foreach ($r in @($rSkel, $rTmpl, $rGeo)) { [void]$an.Children.Add($r.Row) }
    $rTmpl.Combo.IsEnabled = $false
    $rGeo.Combo.IsEnabled = $false

    $eligible = New-Object System.Windows.Controls.TextBlock
    $eligible.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $eligible.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $eligible.FontSize = 11
    $eligible.Margin = New-Object System.Windows.Thickness 190,2,0,10
    $eligible.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
    [void]$an.Children.Add($eligible)

    [void]$an.Children.Add((New-AT3Header "---- IDENTITY ----" -Accent "plum"))
    $rAff   = New-AT3ComboRow -Label "Affiliation"
    $rVoice = New-AT3ComboRow -Label "Voice"
    $rPitch = New-AT3ComboRow -Label "Voice Pitch" -ComboWidth 120
    foreach ($r in @($rAff, $rVoice, $rPitch)) { [void]$an.Children.Add($r.Row) }
    [void]$an.Children.Add((New-AT3Note ("Affiliation is m_species, and it is one switch over three things at " +
        "once: sound-bank fallback, willingness to start a fight, and whether the HUD draws a view cone. " +
        "Affiliations marked (x) are hostile. Voice is m_audioName - if a cue is missing from that bank the game " +
        "falls back to the Affiliation's bank. Pitch is an index into five authored presets, not a scale.")))

    [void]$an.Children.Add((New-AT3Header "---- WEAPONS ----" -Accent "plum"))
    $rMelee  = New-AT3ComboRow -Label "Melee weapon" -ComboWidth 560
    $rRanged = New-AT3ComboRow -Label "Ranged weapon" -ComboWidth 560
    foreach ($r in @($rMelee, $rRanged)) { [void]$an.Children.Add($r.Row) }
    [void]$an.Children.Add((New-AT3Note ("m_meleeWeapon and m_rangedWeapon. Each slot offers every weapon whose TYPE a " +
        "shipped character carries in that slot - including the ones you build in the Weapon Creator. Which kinds this " +
        "template's own characters carry is listed under Behavioral Template above; anything else is allowed and may " +
        "simply look wrong (a mortar playing a knife-throw). A weapon from another region is ported, with its effects, " +
        "when you build.")))
    if ($model -and $model.PSObject.Properties["weapons"]) {
        foreach ($slotSpec in @(@($rMelee, "melee"), @($rRanged, "ranged"))) {
            $cmb = $slotSpec[0].Combo
            [void]$cmb.Items.Add([pscustomobject]@{ Display = "(none)"; Key = "" })
            foreach ($wp in @($model.weapons | Where-Object { $_.slot -eq $slotSpec[1] } |
                    Sort-Object @{ Expression = { if ($_.origin -eq "stock") { 0 } else { 1 } } },
                                @{ Expression = { $_.type } }, @{ Expression = { $_.name } })) {
                $wreg = @($wp.regions)
                [void]$cmb.Items.Add([pscustomobject]@{
                    Display = ("{0}   [{1}{2}]   in {3}{4}" -f $wp.name, $wp.type,
                               $(if ($wp.projectile) { " - " + $wp.projectile } else { "" }),
                               $(if ($wreg.Count) { $wreg -join "," } else { "nowhere" }),
                               $(if ($wp.origin -ne "stock") { "   [" + $wp.origin + "]" } else { "" }))
                    Key = $wp.hash })
            }
        }
    }

    if ($model) {
        foreach ($p in ($model.skeletons.PSObject.Properties | Sort-Object { -[int]$_.Value.characters })) {
            $n = ($p.Value.templates.PSObject.Properties | Measure-Object).Count
            [void]$rSkel.Combo.Items.Add([pscustomobject]@{
                Display = ("{0}   ({1} characters, {2} template(s))" -f $p.Name, $p.Value.characters, $n)
                Key = $p.Name; Node = $p.Value })
        }
        foreach ($s in $model.species) {
            $mark = ""
            if ($s.hostile) { $mark = "   (x)" }
            [void]$rAff.Combo.Items.Add([pscustomobject]@{
                Display = ($s.name + $mark); Key = $s.name; Hash = $s.hash })
        }
        # Voice offers every m_audioName string characters actually carry, not
        # the five species names - joMomma is 'outlawr', and offering only
        # 'outlaw' would silently change its voice.
        foreach ($vname in @($model.voices)) {
            [void]$rVoice.Combo.Items.Add([pscustomobject]@{ Display = $vname; Key = $vname })
        }
        foreach ($i in 0..4) {
            $tag = @("0  lowest", "1", "2", "3", "4  highest")[$i]
            [void]$rPitch.Combo.Items.Add([pscustomobject]@{ Display = $tag; Key = $i })
        }
    }

    # cascade: skeleton -> templates, and skeleton -> geometries
    [void]$rSkel.Combo.Add_SelectionChanged({
        $sel = $rSkel.Combo.SelectedItem
        $rTmpl.Combo.Items.Clear()
        $rGeo.Combo.Items.Clear()
        $eligible.Text = ""
        if (-not $sel) { return }
        foreach ($p in ($sel.Node.templates.PSObject.Properties | Sort-Object Name)) {
            [void]$rTmpl.Combo.Items.Add([pscustomobject]@{
                Display = $p.Name; Key = $p.Name; Node = $p.Value })
        }
        # Geometry is gated by SKELETON, not by template - a geometry is
        # rigged to a skeleton, so anything on this skeleton will bind. Which
        # template it is native to is shown, because borrowing one from a
        # sibling template is exactly the sort of thing worth knowing.
        foreach ($p in ($sel.Node.geometries.PSObject.Properties | Sort-Object Name)) {
            $tag = ""
            if ($p.Value.origin -ne "stock") { $tag = ("   [" + $p.Value.origin + "]") }
            $greg = @($p.Value.regions)
            [void]$rGeo.Combo.Items.Add([pscustomobject]@{
                Display = ("{0}   (via {1})  in {2}{3}" -f $p.Name, ($p.Value.templates -join ", "),
                           $(if ($greg.Count) { $greg -join "," } else { "nowhere" }), $tag)
                Key = $p.Value.hash; Name = $p.Name })
        }
        $rTmpl.Combo.IsEnabled = $true
        $rGeo.Combo.IsEnabled = $true
        if ($validatePort) { & $validatePort }
        if ($rTmpl.Combo.Items.Count -eq 1) { $rTmpl.Combo.SelectedIndex = 0 }
        if ($rGeo.Combo.Items.Count -eq 1) { $rGeo.Combo.SelectedIndex = 0 }
        $status.Text = ("Skeleton {0}: {1} template(s), {2} geometry/geometries." -f
            $sel.Key, $rTmpl.Combo.Items.Count, $rGeo.Combo.Items.Count)
    }.GetNewClosure())

    # template -> what weapons this template's characters actually carry
    [void]$rTmpl.Combo.Add_SelectionChanged({
        $t = $rTmpl.Combo.SelectedItem
        if (-not $t) { $eligible.Text = ""; return }
        $lines = @()
        $melee = @($t.Node.melee_kinds_stock)
        $ranged = @($t.Node.ranged_kinds_stock)
        if ($melee.Count) { $lines += ("melee  : " + ($melee -join ", ")) }
        else { $lines += "melee  : no shipped character using this template carries one" }
        if ($ranged.Count) { $lines += ("ranged : " + ($ranged -join ", ")) }
        else { $lines += "ranged : NONE - this template's AI never calls for a ranged weapon," }
        if (-not $ranged.Count) { $lines += "         so arming one is harmless but does nothing" }
        $missing = @()
        foreach ($f in $t.Node.families.PSObject.Properties) {
            if ([int]$f.Value -eq 0) { $missing += $f.Name }
        }
        if ($missing.Count) {
            $lines += ("no clips: " + ($missing -join ", ") + "  (T-poses - cosmetic, not a fault)")
        }
        $eligible.Text = ($lines -join [Environment]::NewLine)
    }.GetNewClosure())

    # =======================================================================
    # ATTACHMENTS
    #
    # Gated by SKELETON: a bone only means something on a rig, so the tab stays
    # disabled until a Skeletal Species is chosen, and the bone lists follow
    # the Character Geometry's own rig once one is. Entries load from the base
    # like every other field (Kind "attach").
    # =======================================================================
    $att = New-Object System.Windows.Controls.StackPanel
    [void]$att.Children.Add((New-AT3Note ("The meshes this character wears (m_defaultAttachments). Each hangs from a BONE of " +
        "the body mesh's rig, so only that rig's bones are offered. The gun or blade a character visibly holds is usually " +
        "one of these, on a weapnode_ bone - changing its weapon slot does not change what it holds. Position is in the " +
        "bone's own frame: X lateral (+ left), Y depth (+ back), Z vertical (+ up), as tested on the Killer Clakker. " +
        "Typical meshes are the ones authored to be worn plus any a character already wears; 'Choose other Geometry...' " +
        "at the bottom of each list offers every mesh in the game. A mesh from another region is ported with its " +
        "textures when you build or save.")))
    [void]$att.Children.Add((New-AT3Header "---- WORN MESHES ----" -Accent "plum"))
    $attRig = New-Object System.Windows.Controls.TextBlock
    $attRig.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $attRig.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $attRig.FontSize = 11
    $attRig.Margin = New-Object System.Windows.Thickness 0,0,0,8
    $attRig.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
    [void]$att.Children.Add($attRig)
    $attBody = New-Object System.Windows.Controls.StackPanel
    $attBar = New-Object System.Windows.Controls.StackPanel
    $attBar.Orientation = "Horizontal"
    $attBar.Margin = New-Object System.Windows.Thickness 0,0,0,8
    $btnAddAtt = New-Object System.Windows.Controls.Button
    $btnAddAtt.Content = "Add attachment"
    $btnAddAtt.Height = 26
    $btnAddAtt.MinWidth = 150
    [void]$attBar.Children.Add($btnAddAtt)
    $attCount = New-Object System.Windows.Controls.TextBlock
    $attCount.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
    $attCount.Margin = New-Object System.Windows.Thickness 12,0,0,0
    $attCount.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    [void]$attBar.Children.Add($attCount)
    [void]$attBody.Children.Add($attBar)
    $attList = New-Object System.Windows.Controls.StackPanel
    [void]$attBody.Children.Add($attList)
    [void]$att.Children.Add($attBody)
    $attState = @{
        Entries = (New-Object System.Collections.ArrayList); List = $attList; Count = $attCount; AddButton = $btnAddAtt
        Rig = $attRig; Status = $status; Model = $model; GeoItems = @(); Skel = ""; GeoHash = ""
        BaseCanon = ""; Validate = $null; Tab = $null }
    if ($model -and $model.PSObject.Properties["attachment_geos"]) { $attState.GeoItems = @(Get-AT3AttachGeoItems -Model $model) }
    Update-AT3AttachHeader -State $attState

    $attGate = {
        $sk = $rSkel.Combo.SelectedItem
        $gm = $rGeo.Combo.SelectedItem
        $attState.Skel = $(if ($sk) { [string]$sk.Key } else { "" })
        $attState.GeoHash = $(if ($gm) { [string]$gm.Key } else { "" })
        if ($attState.Tab) {
            $attState.Tab.IsEnabled = [bool]$sk
            $attState.Tab.ToolTip = $(if ($sk) { $null } else { "Choose a Skeletal Species on the Anatomy tab first - attachments hang from its bones." })
        }
        Update-AT3AttachBones -State $attState
    }.GetNewClosure()
    [void]$rSkel.Combo.Add_SelectionChanged({ & $attGate }.GetNewClosure())
    [void]$rGeo.Combo.Add_SelectionChanged({ & $attGate }.GetNewClosure())
    [void]$btnAddAtt.Add_Click({
        if ($attState.Entries.Count -ge 16) { return }
        $blk = Add-AT3AttachBlock -State $attState -Entry $null
        Update-AT3AttachHeader -State $attState
        if ($attState.Validate) { & $attState.Validate }
        $blk.Panel.BringIntoView()
    }.GetNewClosure())

    # =======================================================================
    # REWARDS
    # =======================================================================
    $rw = New-Object System.Windows.Controls.StackPanel
    [void]$rw.Children.Add((New-AT3Note ("What this character is worth, and what falls out of it. Bountying " +
        "needs a bounty animation on the skeleton; without one the character can still be sucked up, it just " +
        "T-poses on the way.")))

    [void]$rw.Children.Add((New-AT3Header "---- BOUNTY ----" -Accent "plum"))
    $chkBounty = New-AT3Check -Text "Can be bountied" -Checked $true `
        -Tip "m_canBeBountied - ANC+62. 1 on outlaws, 0 on townsfolk."
    [void]$rw.Children.Add($chkBounty)

    # Everything the checkbox gates lives in one panel, so showing and hiding
    # it is a single Visibility flip rather than a per-control dance.
    $bounty = New-Object System.Windows.Controls.StackPanel
    $bounty.Margin = New-Object System.Windows.Thickness 14,0,0,0
    $rCat = New-AT3ComboRow -Label "Bounty Category" -LabelWidth 200 -ComboWidth 300
    [void]$bounty.Children.Add($rCat.Row)
    [void]$bounty.Children.Add((New-AT3Note ("m_icon. This is the portrait the bounty store shows. The NAME " +
        "beside it is not text anywhere in the data - the store is Flash (data\ui\bounty-store.swf) and the " +
        "name is rendered art, so a new one means authoring a texture, not typing a string.")))

    $fAlive = New-AT3Field -Label "Moolah, captured alive" -Value "10" -Default "10"
    $fDead  = New-AT3Field -Label "Moolah, captured dead"  -Value "3"  -Default "3"
    [void]$bounty.Children.Add($fAlive.Row)
    [void]$bounty.Children.Add($fDead.Row)
    [void]$bounty.Children.Add((New-AT3Note ("m_captureMoolah / m_killMoolah, ANC+63 and ANC+67. Both are " +
        "FLOATS - the nailer ships 30.0 and 10.0 - so fractional rewards are legal.")))

    $fAmmo = New-AT3Field -Label "Ammochow boost (0-1)" -Value "0" -Default "0"
    $fEnd  = New-AT3Field -Label "Endurance boost" -Value "20" -Default "20"
    [void]$bounty.Children.Add($fAmmo.Row)
    [void]$bounty.Children.Add($fEnd.Row)
    [void]$bounty.Children.Add((New-AT3Note ("m_bountyAmmoBoost / m_bountyEnduranceBoost, ANC+71 and ANC+75. " +
        "NOT an alive/dead pair - there is ONE ammo value and ONE endurance value, unlike moolah. Ammo is a " +
        "FRACTION, not a count: the game only ever uses 0.05, 0.1, 0.2, 0.3 and 0.5.")))
    [void]$bounty.Children.Add((New-AT3Note ("Vanilla keeps the two currencies disjoint - wolvarks pay ammo " +
        "and zero moolah, outlaws the reverse - but they are independent fields and CAN both pay at once. " +
        "MovieBoss is the proof: 200 moolah alive, 100 dead, AND 0.05 ammo.")))
    [void]$rw.Children.Add($bounty)

    [void]$rw.Children.Add((New-AT3Header "---- DROPPED LOOT ----" -Accent "plum"))
    [void]$rw.Children.Add((New-AT3Note ("What sprays out, and when. Each slot takes a COLLECTABLE SPAWNER - a " +
        "43-byte record naming one collectable and how many of it. Vanilla wires only two of these to " +
        "characters, both dropping moolah (3 for a townsfolk, 8 for your killer clakker). The other seventeen " +
        "belong to AMMO CRATES - the animatedDestructibles under decorators\ammoCrate_<type>_10 - which spray " +
        "ammo through the same spawner record a character uses for moolah. So a character that drops bees " +
        "needs no new record and no new mechanism, just a different hash in this slot.")))
    $rLimit = New-AT3Field -Label "Collectable spawn limit" -Value "3" -Default "3"
    [void]$rw.Children.Add($rLimit.Row)
    # All SEVEN spawner slots (ANC+149..+173, 4 bytes apart), plus the spawn
    # limit above them - the eight parameters this system has. In record order,
    # the tab matches the data rather than a convenient subset. Three of them
    # are blank on every retail character - onDamage and the two ram-dead
    # slots - but they are FUNCTIONAL, so they are offered and simply marked.
    # Hiding an unused-but-working dial is the same mistake as hiding a field
    # nobody has tested: it decides for the user.
    $lootRows = [ordered]@{}
    foreach ($slot in @(
            @("On damage (punched)",        "onDamage",         149, $true),
            @("On exhaust (knocked out)",   "onExhaust",        153, $false),
            @("On death",                   "onDeath",          157, $false),
            @("Rammed alive, by Steef",     "steefRamAlive",    161, $false),
            @("Rammed alive, by Stranger",  "strangerRamAlive", 165, $false),
            @("Rammed dead, by Steef",      "steefRamDead",     169, $true),
            @("Rammed dead, by Stranger",   "strangerRamDead",  173, $true))) {
        $r = New-AT3ComboRow -Label $slot[0] -LabelWidth 200 -ComboWidth 300
        $r.Combo.ToolTip = ("ANC+{0}{1}" -f $slot[2],
            $(if ($slot[3]) { " - blank on every retail character, but functional" } else { "" }))
        if ($slot[3]) {
            $r.Label.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#9A8A6C")
            $r.Label.Text = $slot[0] + "  *"
        }
        $lootRows[$slot[1]] = $r
        [void]$rw.Children.Add($r.Row)
    }
    [void]$rw.Children.Add((New-AT3Note ("* blank on every retail character - the game never uses these three, " +
        "but the fields work. Nothing in vanilla drops anything on being punched, or on being rammed after " +
        "death.")))
    $lootNote = New-Object System.Windows.Controls.TextBlock
    $lootNote.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $lootNote.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $lootNote.FontSize = 11
    $lootNote.Margin = New-Object System.Windows.Thickness 200,4,0,8
    $lootNote.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
    [void]$rw.Children.Add($lootNote)
    [void]$rw.Children.Add((New-AT3Note ("RESIDENCY GATE. A drop only works where the collectable's GEOMETRY " +
        "already lives. Moolah_Large is native to region_02 and crashes on death anywhere else even when the " +
        "prefs record is copied in - the copy brings no geometry. Each option lists the regions it is resident " +
        "in; picking one outside them needs a port first.")))

    if ($model) {
        foreach ($ic in $model.icons) {
            [void]$rCat.Combo.Items.Add([pscustomobject]@{
                Display = $ic.label; Key = $ic.hash; Name = $ic.name })
        }
        foreach ($r in $lootRows.Values) {
            [void]$r.Combo.Items.Add([pscustomobject]@{
                Display = "(nothing)"; Key = $null; Kind = "none"; Regions = @(); Spray = $null })
            [void]$r.Combo.Items.Add([pscustomobject]@{
                Display = "Custom spray..."; Key = "NEW"; Kind = "new"; Regions = @(); Spray = $null })
            foreach ($s in $model.spawners) {
                $reg = @($s.regions)
                $where = if ($reg.Count) { "regions " + ($reg -join ",") } else { "NOT RESIDENT ANYWHERE" }
                # Mark what this project built. E94574EE - the killer clakker's
                # x8 - was being offered as though the game shipped it.
                $tag = if ($s.origin -ne "stock") { "  [" + $s.origin + "]" } else { "" }
                [void]$r.Combo.Items.Add([pscustomobject]@{
                    Display = ("{0} x{1}  [{2}]  {3}{4}" -f $s.label, $s.count, $s.kind, $where, $tag)
                    Key = $s.hash; Kind = $s.kind; Regions = $reg; Spray = $null })
            }
        }
    }

    [void]$chkBounty.Add_Checked({   $bounty.Visibility = "Visible" }.GetNewClosure())
    [void]$chkBounty.Add_Unchecked({ $bounty.Visibility = "Collapsed" }.GetNewClosure())

    foreach ($k in $lootRows.Keys) {
        $cb = $lootRows[$k].Combo
        [void]$cb.Add_SelectionChanged({
            param($src, $ev)
            # "Custom spray..." opens the designer and, on OK, becomes a real
            # entry in THIS slot's list so it can be re-selected and re-edited.
            $sel = $src.SelectedItem
            if ($sel -and $sel.Key -eq "NEW") {
                $spray = Show-AT3SprayDesigner -Model $model
                if ($spray) {
                    $item = [pscustomobject]@{
                        Display = ("{0} x{1}  [custom spray]  {2}" -f $spray.Label, $spray.Count,
                                   $(if (@($spray.Regions).Count) { "regions " + (@($spray.Regions) -join ",") }
                                     else { "NOT RESIDENT ANYWHERE" }))
                        Key = "SPRAY"; Kind = "custom"; Regions = @($spray.Regions); Spray = $spray }
                    [void]$src.Items.Add($item)
                    $src.SelectedItem = $item
                    return
                }
                $src.SelectedIndex = 0
                return
            }
            $picked = @()
            foreach ($kk in $lootRows.Keys) {
                $it = $lootRows[$kk].Combo.SelectedItem
                if ($it -and $it.Key) { $picked += $it }
            }
            if (-not $picked.Count) { $lootNote.Text = ""; return }
            # The regions where EVERY chosen drop is resident - that is where
            # this character can be placed without porting geometry first.
            $common = $null
            foreach ($p in $picked) {
                if ($null -eq $common) { $common = @($p.Regions) }
                else { $common = @($common | Where-Object { $p.Regions -contains $_ }) }
            }
            if ($common.Count) {
                $lootNote.Text = "all chosen drops are resident in region(s): " + ($common -join ", ")
            } else {
                $lootNote.Text = "NO region holds every chosen drop - one of them must be ported, or pick drops that share a region"
            }
        }.GetNewClosure())
    }

    # =======================================================================
    # EXPERIMENTAL
    # =======================================================================
    $ex = New-Object System.Windows.Controls.StackPanel
    [void]$ex.Children.Add((New-AT3Note ("Unconfirmed dials, for finding out what they do. Everything here is " +
        "unverified by definition - expect no effect, odd effects, and occasional crashes. Experimental edits " +
        "are kept in their own block of the recipe so a shared character never carries unexplained bytes " +
        "pretending to be stock.")))
    [void]$ex.Children.Add((New-AT3Header "---- METHOD ----" -Accent "plum"))
    [void]$ex.Children.Add((New-AT3Note ("Change ONE thing per launch and record it, or bisect a group. Six " +
        "fields in this project were written off as inert from single edits and all six were wrong - several " +
        "only do anything as part of a group. 'No visible change' is not evidence a field is dead.")))
    [void]$ex.Children.Add((New-AT3Note ("Run  python ModTools\char_model.py --unknowns  for the current " +
        "candidate list. It reports contiguous runs of bytes that vary between characters and have no confirmed " +
        "field, which is where the unexplored dials are.")))

    # =======================================================================
    $tabs = New-Object System.Windows.Controls.TabControl
    $tabs.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#120D0A")
    # =======================================================================
    # PHYSICAL ATTRIBUTES
    # =======================================================================
    $ph = New-Object System.Windows.Controls.StackPanel
    [void]$ph.Children.Add((New-AT3Note ("How much punishment the character takes and how it occupies space. " +
        "Everything in STATS is anchored on ANC and confirmed; the BODY block is located from the animation " +
        "config path, on every record.")))

    [void]$ph.Children.Add((New-AT3Header "---- STATS ----" -Accent "plum"))
    $physRows = [ordered]@{}
    foreach ($f in @(
            @("Health",                      "m_health",                     "150",  16),
            @("Health regeneration rate",    "m_healthRecoverTime",          "-1",   20),
            @("Stamina",                     "m_stamina",                    "150",  24),
            @("Stamina regeneration rate",   "m_staminaRecoverTime",         "4.5",  28),
            @("Knocked-out duration",        "m_exhaustTime",                "7",    32),
            @("Exhausted recover multiplier","m_exhaustedRecoverMultiplier", "1.2",  36))) {
        $r = New-AT3Field -Label $f[0] -Value $f[2] -Default $f[2]
        $r.Row.ToolTip = ("{0}  -  ANC+{1}, float" -f $f[1], $f[3])
        $physRows[$f[1]] = $r
        [void]$ph.Children.Add($r.Row)
    }
    [void]$ph.Children.Add((New-AT3Note ("Health regeneration is -1 on every character in the game, which is " +
        "how the engine spells 'never regenerates'. Knocked-out duration is m_exhaustTime - how long the " +
        "character stays down - which is the answer to why castaraider (1.2) gets up faster than everyone " +
        "else (7 to 10). It is NOT m_staminaRecoverTime; that was tested and is not the lever.")))

    [void]$ph.Children.Add((New-AT3Header "---- SIZE ----" -Accent "plum"))
    $rScaleMin = New-AT3Field -Label "Scale, minimum" -Value "1" -Default "1"
    $rScaleMax = New-AT3Field -Label "Scale, maximum" -Value "1" -Default "1"
    $rScaleMin.Row.ToolTip = "m_geoScaleMin  -  ANC+8, float"
    $rScaleMax.Row.ToolTip = "m_geoScaleMax  -  ANC+12, float"
    [void]$ph.Children.Add($rScaleMin.Row)
    [void]$ph.Children.Add($rScaleMax.Row)
    [void]$ph.Children.Add((New-AT3Note ("A RANGE, rolled per spawn - set both to the same number for a fixed " +
        "size. TownsfolkKid ships 0.6. This is the field that resized the killer clakker.")))

    [void]$ph.Children.Add((New-AT3Header "---- BODY ----" -Accent "plum"))
    foreach ($f in @(
            @("Mass",                  "m_mass",                  "140",   16),
            @("Body sphere height",    "m_motionSphereHeight",    "1.6",   0),
            @("Body sphere radius",    "m_motionSphereRadius",    "1.2",   4),
            @("Turn speed (deg/sec)",  "m_bipedTurnSpeedDegrees", "150",   8),
            @("Turn speed, panicked",  "m_bipedTurnSpeedDegrees_Panic", "300", 12),
            @("Water offset",          "m_waterOffset",           "-0.45", 20),
            @("Water velocity scale",  "m_waterVelocityScale",    "1.5",   24))) {
        $r = New-AT3Field -Label $f[0] -Value $f[2] -Default $f[2]
        $r.Row.ToolTip = ("{0}  -  MOTION+{1}, float (resolved per record, not a fixed offset)" -f $f[1], $f[3])
        $physRows[$f[1]] = $r
        [void]$ph.Children.Add($r.Row)
    }
    [void]$ph.Children.Add((New-AT3Note ("These floats sit directly before the animation config path - exactly 40 bytes " +
        "before its length prefix on every character copy - so they are located from the path itself and resolve " +
        "whatever values they hold. (An earlier search matched plausible values instead, and lost the whole block once a " +
        "mass of 1,000,000 was saved.) Observed masses: townsfolk 95, nailer 140, cutter 160, gloktigi 500, GiantSleg " +
        "and shocktank 1000.")))

    [void]$ph.Children.Add((New-AT3Header "---- GIBBING ----" -Accent "plum"))
    # THREE INDEPENDENT FIELDS, shown flat. An earlier version put a "Can gib?"
    # master checkbox above these - but the record has no such byte, so the
    # control stood for nothing and its only effect was to hide real fields
    # behind an invented one. The UI mirrors the data here as everywhere else.
    $chkGib = New-AT3Check -Text "Gibs on death" -Checked $false `
        -Tip "m_onDeathGib - ANC+40. True on only three characters in the whole game: shocktank, Tiny and Sekto3."
    $chkGibBolt = New-AT3Check -Text "Can gib from bolts" -Checked $false `
        -Tip "m_allowOnDeathGibFromBolts - ANC+41."
    [void]$ph.Children.Add($chkGib)
    [void]$ph.Children.Add($chkGibBolt)

    # Gib effect: what the body bursts into. The same effect-mix record type
    # destructibles use for debris. A closed list - see char_fields GIB_EFFECTS;
    # bosses whose effect block has another layout show it disabled.
    $rGibFx = New-AT3ComboRow -Label "Gib effect" -LabelWidth 170 -ComboWidth 330
    foreach ($g in @(
            @("DA33DF83", "Default gibs  (flesh and bone - every region)"),
            @("A2A28E4F", "Default gibs  (global copy - every region)"),
            @("026797F2", "Shock Tank chunks  (metal - native to 05, 06)"),
            @("5978F009", "Turret chunks  (metal - native to 02)"),
            @("4ABC85DB", "Mine cart chunks  (native to 03)"))) {
        [void]$rGibFx.Combo.Items.Add([pscustomobject]@{ Display = $g[1]; Key = $g[0] })
    }
    $rGibFx.Combo.ToolTip = "Gib effect mix, 56 bytes before the web-escape effect pair. Outside its native regions the effect and its chunk meshes are ported in at build."
    [void]$ph.Children.Add($rGibFx.Row)

    # Spawn on gib: a hash field chosen from the Character Library rather than
    # typed, so it can only ever name a real character.
    $gibRow = New-Object System.Windows.Controls.StackPanel
    $gibRow.Orientation = "Horizontal"
    $gibRow.Margin = New-Object System.Windows.Thickness 0,4,0,2
    $btnGibSpawn = New-Object System.Windows.Controls.Button
    $btnGibSpawn.Content = "Spawns character upon gibbing..."
    $btnGibSpawn.Height = 28
    $btnGibSpawn.MinWidth = 260
    $btnGibSpawn.ToolTip = "m_onGibSpawnNPC - ANC+42, a character hash. Opens the Character Library."
    [void]$gibRow.Children.Add($btnGibSpawn)
    $btnGibClear = New-Object System.Windows.Controls.Button
    $btnGibClear.Content = "Nothing"
    $btnGibClear.Height = 28
    $btnGibClear.MinWidth = 90
    $btnGibClear.Margin = New-Object System.Windows.Thickness 8,0,0,0
    $btnGibClear.ToolTip = "Spawn nothing when this character gibs."
    [void]$gibRow.Children.Add($btnGibClear)
    [void]$ph.Children.Add($gibRow)
    $gibSpawnLbl = New-Object System.Windows.Controls.TextBlock
    $gibSpawnLbl.Text = "(nothing)"
    $gibSpawnLbl.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $gibSpawnLbl.FontSize = 11
    $gibSpawnLbl.Margin = New-Object System.Windows.Thickness 2,0,0,6
    $gibSpawnLbl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    [void]$ph.Children.Add($gibSpawnLbl)
    $gibState = @{ Hash = ""; Names = @{}; Regions = @{} }
    if ($model) {
        foreach ($gsk in $model.skeletons.PSObject.Properties) {
            foreach ($gtp in $gsk.Value.templates.PSObject.Properties) {
                foreach ($gc in @($gtp.Value.characters)) {
                    $gibState.Names[[string]$gc.hash] = [string]$gc.name
                    $gibState.Regions[[string]$gc.hash] = (@($gc.regions) -join ",")
                }
            }
        }
    }
    $gibShow = {
        $gh = [string]$gibState.Hash
        $gibSpawnLbl.Text = $(if (-not $gh) { "(nothing)" }
            elseif ($gibState.Names.ContainsKey($gh)) { "{0}  ({1})  - lives in {2}" -f $gibState.Names[$gh], $gh, $(if ($gibState.Regions[$gh]) { $gibState.Regions[$gh] } else { "no region" }) }
            else { "{0}  (not a character this install knows)" -f $gh })
    }.GetNewClosure()
    [void]$btnGibSpawn.Add_Click({
        $p = Show-AT3CharacterLibraryPicker -Purpose "gib"
        if ($p) {
            $gibState.Hash = [string]$p.Hash
            & $gibShow
            $status.Text = ("On gibbing this character spawns " + $p.Name + " - ported, with everything it needs, into any region you build or save to that lacks it.")
        }
    }.GetNewClosure())
    [void]$btnGibClear.Add_Click({ $gibState.Hash = ""; & $gibShow }.GetNewClosure())

    [void]$ph.Children.Add((New-AT3Note ("m_onGibSpawnNPC, ANC+42 - the character that takes this one's place when it comes " +
        "apart. The game uses it twice: a Shock Tank becomes a Wolvark shooter, and Tiny becomes Meagly McGraw. Retail sets " +
        "it only on characters that gib, so tick 'Gibs on death' above for it to have a moment to happen. The chosen " +
        "character is ported, with its mesh, animations and weapons, into each region you build or save to that lacks it. " +
        "Picking this character itself makes a chain.")))

    # =======================================================================
    # IMMUNITIES
    #
    # Retail is NOT the prototype here, and the difference decides the UI.
    # The prototype has ~20 m_affBy<Ammo> booleans; retail has m_affGenerally
    # plus m_affList (a LIST, per the engine's reflection table) and only FOUR
    # per-ammo booleans - dynamite, skunk bomb, spider bola, fuzzle. There is
    # no armadillo, bee or chipmunk flag to gate on.
    #
    # The tail is m_affList - a COUNT at ANC+137 and that many ammo-pref
    # hashes - then these four flags, then the drops (char_fields.tail_layout).
    # The earlier "optional block, absent = immune" reading was wrong and is
    # withdrawn: it misread six characters and left twelve unresolved. The
    # flags are writable on every character, and so is the list: char_fields
    # splices it, moves the flags and drops with it, and re-parses the tail.
    # =======================================================================
    # The RULE first, because it decides what the list means - showing the list
    # as "immunities" on its own contradicted Shock Tank and Sekto's Machine,
    # whose rule is the other way round.
    [void]$ph.Children.Add((New-AT3Header "---- AMMO RULE AND LIST ----" -Accent "plum"))
    [void]$ph.Children.Add((New-AT3Note ("Which player ammo works on this character is one RULE plus one LIST, and the rule " +
        "decides what the list means. m_affGenerally = 1 (77 characters): affected by every ammo EXCEPT the listed types - " +
        "Fatty, Lefty and Elboze list SniperDart, the outlaw bosses SendToChipmunk. m_affGenerally = 0 (Shock Tank, Sekto's " +
        "Machine and two region_06 copies): affected ONLY by the listed types - Shock Tank's list leaves out fuzzles, " +
        "stingbees, skunk bombs and chipmunks, exactly what it shrugs off in play. Read from retail data; saving a different " +
        "rule or list has not been tested in game.")))
    $rAffRule = New-AT3ComboRow -Label "Ammo rule" -ComboWidth 520
    [void]$rAffRule.Combo.Items.Add([pscustomobject]@{ Display = "1 - affected by all ammo EXCEPT the types ticked below"; Key = 1 })
    [void]$rAffRule.Combo.Items.Add([pscustomobject]@{ Display = "0 - affected ONLY by the types ticked below"; Key = 0 })
    $rAffRule.Row.ToolTip = "m_affGenerally - ANC+136, byte, directly before m_affList's count."
    [void]$ph.Children.Add($rAffRule.Row)
    $affCaption = New-Object System.Windows.Controls.TextBlock
    $affCaption.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $affCaption.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $affCaption.FontSize = 11
    $affCaption.Margin = New-Object System.Windows.Thickness 0,2,0,6
    $affCaption.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    [void]$ph.Children.Add($affCaption)
    [void]$rAffRule.Combo.Add_SelectionChanged({
        $k = $rAffRule.Combo.SelectedItem
        $affCaption.Text = $(if (-not $k) { "" }
            elseif ([int]$k.Key -eq 1) { "A ticked box = this character is NOT affected by that ammo." }
            else { "A ticked box = that ammo DOES affect this character; every unticked type does nothing to it." })
    }.GetNewClosure())

    # m_affList, editable: one box per player ammo pref. A list whose boxes
    # match the base is not sent at all, so a vanilla list keeps its order and
    # its duplicates (gloktigi lists ImmobilizeBolaBlast three times).
    $affBox = New-Object System.Windows.Controls.StackPanel
    $affWrap = New-Object System.Windows.Controls.WrapPanel
    $affChecks = [ordered]@{}
    if ($model -and $model.PSObject.Properties["aff_options"]) {
        foreach ($o in @($model.aff_options)) {
            $where = if ($o.global) { "global" } else { "resident in " + (@($o.regions) -join ",") }
            $c = New-AT3Check -Text ("{0}  ({1})" -f $o.name, $o.listed_on) -Checked $false `
                -Tip ("{0}  -  listed on {1} shipped character(s); {2}" -f $o.hash, $o.listed_on, $where)
            $c.Width = 290
            $c.Margin = New-Object System.Windows.Thickness 0,0,0,4
            $c.Tag = [string]$o.hash
            $affChecks[[string]$o.hash] = $c
            [void]$affWrap.Children.Add($c)
        }
    }
    [void]$affBox.Children.Add($affWrap)
    [void]$ph.Children.Add($affBox)
    [void]$ph.Children.Add((New-AT3Note ("m_affList. The number beside each ammo type is how many shipped characters list it. " +
        "Upgraded ammo is its own entry (TrapFuzzle and TrapFuzzleRabid are listed separately in vanilla). Ticking or " +
        "unticking a box changes the record's length; saving moves the reaction flags and drops with it and refuses " +
        "unless the tail still parses.")))

    [void]$ph.Children.Add((New-AT3Header "---- REACTIONS ----" -Accent "plum"))
    [void]$ph.Children.Add((New-AT3Note ("Four more bytes - m_respondsTo dynamite, skunk bomb, spider bola and fuzzle trap - and " +
        "they are SEPARATE from the rule and list above: retail sets them independently (Shock Tank lists dynamite AND " +
        "responds to it; Filthy Hands Floyd lists dynamite and skunk bomb with all four ticked). The best reading so far is " +
        "that an unticked box leaves that ammo a single frame of effect - outlawNailer and outlawPyro on skunk bomb.")))

    $immChecks = [ordered]@{}
    $immSubs = @{}
    # Each responds-to owns its tuning fields, revealed only when ticked -
    # there is no point offering spider tuning for a character nothing spiders
    # can touch.
    foreach ($f in @(
            @("Responds to dynamite damage",  "m_respondsToDamageDynamite",       141),
            @("Responds to skunk bomb",       "m_respondsToImmobilizeSkunkBomb",  142),
            @("Responds to spider bola",      "m_respondsToImmobilizeSpiderBola", 143),
            @("Responds to fuzzle trap",      "m_respondsToTrapFuzzle",           144),
            @("Responds to armadillo",        "(armadillo - no flag in retail)",  -1))) {
        $c = New-AT3Check -Text $f[0] -Checked $false -Tip ($(if ($f[2] -ge 0)
                { "{0} - ANC+{1}, byte" -f $f[1], $f[2] }
                else { "NOT a field - shows the armadillo tuning below. No character in the game is armadillo-immune, so retail has no flag." }))
        $immChecks[$f[0]] = $c
        [void]$ph.Children.Add($c)

        $sub = New-Object System.Windows.Controls.StackPanel
        $sub.Margin = New-Object System.Windows.Thickness 22,0,0,4
        $sub.Visibility = "Collapsed"
        switch ($f[0]) {
            "Responds to fuzzle trap" {
                foreach ($g in @(
                        @("Fuzzle shake-off time", "m_fuzzleShakeOffTime",  "5",   115),
                        @("Fuzzle flop frequency", "m_fuzzleFlopFrequency", "0.5", 119),
                        @("Fuzzle flee radius",    "m_fuzzleFleeRadius",    "3.5", 123))) {
                    $r = New-AT3Field -Label $g[0] -Value $g[2] -Default $g[2]
                    $r.Row.ToolTip = ("{0}  -  ANC+{1}, float" -f $g[1], $g[3])
                    $physRows[$g[1]] = $r
                    [void]$sub.Children.Add($r.Row)
                }
            }
            "Responds to armadillo" {
                foreach ($g in @(
                        @("Armadillo stamina multiplier", "m_armadilloStaminaMultiplier", "1", 127),
                        @("Armadillo damage multiplier",  "m_armadilloDamageMultiplier",  "1", 132))) {
                    $r = New-AT3Field -Label $g[0] -Value $g[2] -Default $g[2]
                    $r.Row.ToolTip = ("{0}  -  ANC+{1}, float" -f $g[1], $g[3])
                    $physRows[$g[1]] = $r
                    [void]$sub.Children.Add($r.Row)
                }
                $chkArmKnock = New-AT3Check -Text "Armadillo knocks this character over" -Checked $true `
                    -Tip "m_armadilloKnocks - ANC+131, byte. 0 on GiantSleg, gloktigi and shocktank."
                [void]$sub.Children.Add($chkArmKnock)
            }
            default {
                [void]$sub.Children.Add((New-AT3Note ("No tuning fields located for this one. The prototype " +
                    "has skunk and spider multipliers; in retail they are not where the layout says they " +
                    "should be and have not been found.")))
            }
        }
        $immSubs[$f[0]] = $sub
        [void]$ph.Children.Add($sub)
        $key = $f[0]
        [void]$c.Add_Checked({   $immSubs[$key].Visibility = "Visible" }.GetNewClosure())
        [void]$c.Add_Unchecked({ $immSubs[$key].Visibility = "Collapsed" }.GetNewClosure())
    }

    [void]$ph.Children.Add((New-AT3Note ("WHAT 'RESPONDS TO' MEANS IS UNTESTED. It may gate the reaction " +
        "(panic, flailing) rather than the effect itself - whether a fuzzle refuses to attach, or attaches " +
        "and the character ignores it, is not established. The flags are strictly BINARY in vanilla: across " +
        "100 readings the only values are 0 and 1, never anything between. Whether the engine would treat, " +
        "say, 128 as half-efficiency is untested - it is a byte, so it would fit.")))

    [void]$ph.Children.Add((New-AT3Header "---- MOVEMENT ----" -Accent "plum"))
    $chkPush  = New-AT3Check -Text "Can be pushed (slides aside to make room)" -Checked $true `
        -Tip "m_canBePushed - CFG+0, byte."
    $chkKnock = New-AT3Check -Text "Can be knocked over" -Checked $true `
        -Tip "m_canBeKnocked - CFG+1, byte. 0 on GiantSleg and gloktigi."
    foreach ($c in @($chkPush, $chkKnock)) { [void]$ph.Children.Add($c) }
    [void]$ph.Children.Add((New-AT3Note ("Two booleans at CFG+0 and +1, directly after the animation config path " +
        "(the third, m_onlyStands, is under Experimental) - 0/1 on 74 of 93 records, the other 19 being the live-ammo stubs. " +
        "GiantSleg reads 0,0 (neither pushed nor knocked), gloktigi 1,0, Meagly and MovieBoss 0,1. CAVEAT: " +
        "outlawNailer reads as pushable here, which does not match the recollection that nailers cannot be " +
        "pushed - so either CFG+0 is something else or the behaviour comes from mass. Worth one test before " +
        "trusting it.")))

    # m_onlyStands is real - the engine's own field order puts it at CFG+2, after
    # pushed and knocked - but nothing has been seen to change when it is saved,
    # so it sits with the other dials whose meaning is still being found.
    $chkStand = New-AT3Check -Text "m_onlyStands  (CFG+2)" -Checked $false `
        -Tip "m_onlyStands - CFG+2, byte. MotionImplDummy in the engine's field order: m_canBePushed, m_canBeKnocked, m_onlyStands."
    [void]$ex.Children.Add((New-AT3Header "---- MOTION ----" -Accent "plum"))
    [void]$ex.Children.Add($chkStand)
    [void]$ex.Children.Add((New-AT3CheckNote ("Written exactly where the engine's own field order puts m_onlyStands, directly after " +
        "can-be-pushed and can-be-knocked, and it saves - but no effect has been seen: landmine was saved 1, then 0, then 1 " +
        "(2026-09-13) with no visible difference. In retail it is 1 on exactly one character, Sekto's Machine - a boss that " +
        "never walks - which fits the name, but what it governs is unknown; it may only matter to that kind of AI, not to a " +
        "character that has walking animations.")))

    [void]$ph.Children.Add((New-AT3Header "---- NOT OFFERED: PLAYER-ONLY ----" -Accent "plum"))
    [void]$ph.Children.Add((New-AT3Note ("Twenty-two more floats sit after the config path - jump heights, the " +
        "eight acceleration values, steef drive speeds, skid-to-stop lerpers and the four overVel values. " +
        "Every one is byte-identical on every character checked, which matches your read that they are " +
        "player-only and inert on NPCs. They are listed in the model as inert_fields so nobody re-derives " +
        "them, and they surface in Experimental rather than here.")))

    # =======================================================================
    # BEHAVIOR
    #
    # The four sight blocks are the view cone and they are CONFIRMED: every
    # one of the 32 values in the retail outlawCutter matches the prototype
    # block the player supplied, exactly. Eight fields per block, not the
    # seven CHARACTER_DIALS used to list - the missing m_hideVolSeeDistance
    # is why sight offsets never lined up before.
    #
    # attackParams is a separate section because it is weaker evidence: the
    # ORDER matches the prototype and four values anchor it (20, 100, 3, 75),
    # but retail retuned the rest, and one slot around CFG+262 is unaccounted.
    # =======================================================================
    $bh = New-Object System.Windows.Controls.StackPanel
    [void]$bh.Children.Add((New-AT3Note ("How the character perceives and engages. The view cone is four " +
        "separate eight-field blocks - one per alert state - and the game switches between them as the " +
        "character escalates. All 32 values are confirmed against a known-good reference.")))

    $sightRows = @{}
    foreach ($blk in @(
            @("NORMAL - unaware",   "m_sightNormal", 91,  @("5","50","10","6","90","90","10","1")),
            @("AGITATED - alerted", "m_sightAgit",   123, @("4.5","140","30","30","70","160","10","1")),
            @("COMBAT - fighting",  "m_sightCombat", 155, @("5.5","150","30","30","70","160","10","1")),
            @("PANIC - fleeing",    "m_sightPanic",  187, @("3.5","25","10","10","30","30","10","1")))) {
        [void]$bh.Children.Add((New-AT3Header ("---- VIEW CONE: " + $blk[0] + " ----") -Accent "plum"))
        $i = 0
        foreach ($f in @(
                @("Sixth sense distance",  "m_6thSenseDistance",     0),
                @("See distance",          "m_seeDistance",          4),
                @("See above",             "m_seeAbove",             8),
                @("See below",             "m_seeBelow",             12),
                @("Horizontal angle (deg)","m_horizontalAngleDeg",   16),
                @("Vertical angle (deg)",  "m_verticalAngleDeg",     20),
                @("Instant sight distance","m_instantSightDistance", 24),
                @("Hide-volume see dist",  "m_hideVolSeeDistance",   28))) {
            $r = New-AT3Field -Label $f[0] -Value $blk[3][$i] -Default $blk[3][$i]
            $r.Row.ToolTip = ("{0}.{1}  -  CFG+{2}, float" -f $blk[1], $f[1], ($blk[2] + $f[2]))
            $sightRows[($blk[1] + "." + $f[1])] = $r
            [void]$bh.Children.Add($r.Row)
            $i++
        }
    }
    [void]$bh.Children.Add((New-AT3Note ("Sixth sense is CONTESTED, not confirmed inert. Every result so far " +
        "was confounded by the ordinary sight cone. To isolate it, set NORMAL see distance and horizontal " +
        "angle both to 0 with a large sixth sense - then any passive detection at all is the sixth sense and " +
        "nothing else.")))
    [void]$bh.Children.Add((New-AT3Note ("Note the vertical angle: the cutter runs 90 when unaware but 160 " +
        "when agitated or fighting, so an alerted character sees far more above and below it than a relaxed " +
        "one. Hide-volume see distance is 1 on every block of every character checked.")))

    [void]$bh.Children.Add((New-AT3Header "---- COMBAT TUNING ----" -Accent "plum"))
    [void]$bh.Children.Add((New-AT3Note ("PROBABLE, not confirmed. The field ORDER is established - four " +
        "values (wander radius 20, cover time 100, melee hunt 3, cover use 75) match the reference exactly " +
        "and in sequence - but retail retuned the others, and one slot is unaccounted. The retail NAILER " +
        "carries the reference CUTTER's ranged numbers, which is how the order was pinned.")))
    foreach ($f in @(
            @("Ranged: desired distance min",  "ranged_desiredDistMin",    "40",  246),
            @("Ranged: desired distance max",  "ranged_desiredDistMax",    "60",  250),
            @("Ranged: beat approach distance","ranged_beatApproachDist",  "10",  254),
            @("Fire spot: pause after",        "fireSpot_pauseAfter",      "0",   258),
            @("Fire spot: wander radius",      "fireSpot_wanderRadius",    "20",  266),
            @("Melee: approach dist, front",   "melee_approachDist_Front", "40",  270),
            @("Melee: approach dist, behind",  "melee_approachDist_Behind","60",  274),
            @("Lost sight 1: search time",     "lostLOSTime_1_Search",     "2",   278),
            @("Lost sight 2: cover time",      "lostLOSTime_2_Cover",      "100", 282),
            @("Lost sight 3: hunt time",       "lostLOSTime_3_Hunt",       "4",   286),
            @("Lost sight 3: hunt, no search", "lostLOSTime_3_Hunt_WithoutFireSearch", "5", 290),
            @("Lost sight 3: hunt, melee",     "lostLOSTime_3_Hunt_MeleeGuy", "3", 294),
            @("Ranged: percent use of cover",  "ranged_PercentUseOfCover", "75",  298))) {
        $r = New-AT3Field -Label $f[0] -Value $f[2] -Default $f[2]
        $r.Row.ToolTip = ("{0}  -  CFG+{1}, float (probable)" -f $f[1], $f[3])
        $sightRows[$f[1]] = $r
        [void]$bh.Children.Add($r.Row)
    }
    $rShots = New-AT3Field -Label "Fire spot: number of shots" -Value "2" -Default "2"
    $rShots.Row.ToolTip = "fireSpot_NumShots  -  CFG+232, int. Matches the reference exactly."
    [void]$bh.Children.Add($rShots.Row)

    [void]$bh.Children.Add((New-AT3Header "---- NOT OFFERED ----" -Accent "plum"))
    [void]$bh.Children.Add((New-AT3Note ("Eight combat booleans sit at CFG+236..243 and do differ between " +
        "characters, but six of eight match the reference ordering and two look transposed - so naming them " +
        "individually would be guessing. They stay out until the order is settled.")))
    [void]$bh.Children.Add((New-AT3Note ("The six m_conf* confidence fields are ABSENT from retail - not " +
        "unfound, genuinely dropped, like the affect block. That matches your read that they describe " +
        "behaviour the game never shows. m_isLeader is not located either, and with no known behaviour " +
        "attached there is nothing to test it against.")))

    # =======================================================================
    # FIELD WIRING
    #
    # Every editable control is registered against the char_fields name it
    # writes. Choosing a base loads that record's REAL values into all of
    # them and disables any field char_fields cannot locate on that record,
    # with the reason on hover. At build time the fields that DIFFER from the
    # base become the edits file build_character.py applies.
    #
    # Before this existed every dial here was inert: Build copied the donor
    # byte for byte, and the "defaults" were placeholders read from nothing.
    #
    # $loadBase and $collectEdits take the base as a PARAMETER. $rBase is
    # created further down, and a GetNewClosure block snapshots a local that
    # does not exist yet as $null.
    # =======================================================================
    $fieldCtl = [ordered]@{}
    foreach ($k in $physRows.Keys)  { $fieldCtl[$k] = New-AT3FieldEntry -Kind "text" -Ctl $physRows[$k] -Fields @($k) }
    foreach ($k in $sightRows.Keys) { $fieldCtl[$k] = New-AT3FieldEntry -Kind "text" -Ctl $sightRows[$k] -Fields @($k) }
    foreach ($spec in @(
            @("fireSpot_NumShots", "text", $rShots), @("m_geoScaleMin", "text", $rScaleMin),
            @("m_geoScaleMax", "text", $rScaleMax), @("m_captureMoolah", "text", $fAlive),
            @("m_killMoolah", "text", $fDead), @("m_bountyAmmoBoost", "text", $fAmmo),
            @("m_bountyEnduranceBoost", "text", $fEnd), @("m_collectableSpawnLimit", "text", $rLimit),
            @("m_onDeathGib", "check", $chkGib), @("m_allowOnDeathGibFromBolts", "check", $chkGibBolt),
            @("m_armadilloKnocks", "check", $chkArmKnock), @("m_canBePushed", "check", $chkPush),
            @("m_canBeKnocked", "check", $chkKnock), @("m_onlyStands", "check", $chkStand),
            @("m_canBeBountied", "check", $chkBounty), @("m_icon", "combo", $rCat),
            @("m_geometry", "combo", $rGeo), @("m_species", "combo", $rAff), @("m_audioName", "combo", $rVoice),
            @("m_meleeWeapon", "combo", $rMelee), @("m_rangedWeapon", "combo", $rRanged),
            @("m_affGenerally", "combo", $rAffRule), @("m_gibEffect", "combo", $rGibFx))) {
        $fieldCtl[$spec[0]] = New-AT3FieldEntry -Kind $spec[1] -Ctl $spec[2] -Fields @($spec[0])
    }
    $fieldCtl["m_minRandomSpeechPitch"] = New-AT3FieldEntry -Kind "combo" -Ctl $rPitch `
        -Fields @("m_minRandomSpeechPitch", "m_maxRandomSpeechPitch")
    foreach ($pair in @(@("Responds to dynamite damage", "m_respondsToDamageDynamite"),
                        @("Responds to skunk bomb", "m_respondsToImmobilizeSkunkBomb"),
                        @("Responds to spider bola", "m_respondsToImmobilizeSpiderBola"),
                        @("Responds to fuzzle trap", "m_respondsToTrapFuzzle"))) {
        $fieldCtl[$pair[1]] = New-AT3FieldEntry -Kind "check" -Ctl $immChecks[$pair[0]] -Fields @($pair[1])
    }
    $slotField = @{ onDamage = "m_onDamageCollectableSpawner"; onExhaust = "m_onExhaustCollectableSpawner";
                    onDeath = "m_onDeathCollectableSpawner"; steefRamAlive = "m_onSteefRamAliveCollectableSpawner";
                    strangerRamAlive = "m_onStrangerRamAliveCollectableSpawner";
                    steefRamDead = "m_onSteefRamDeadCollectableSpawner";
                    strangerRamDead = "m_onStrangerRamDeadCollectableSpawner" }
    foreach ($k in $lootRows.Keys) {
        $fieldCtl[$slotField[$k]] = New-AT3FieldEntry -Kind "combo" -Ctl $lootRows[$k] -Fields @($slotField[$k])
    }
    $armToggle = $immChecks["Responds to armadillo"]
    $fieldCtl["m_affList"] = New-AT3FieldEntry -Kind "multi" -Ctl @{ Row = $affBox; Boxes = $affChecks } -Fields @("m_affList")
    $fieldCtl["m_onGibSpawnNPC"] = New-AT3FieldEntry -Kind "custom" -Fields @("m_onGibSpawnNPC") -Ctl @{
        Row = $gibRow
        Set = { param($v) $gibState.Hash = $(if ($v) { ([string]$v).ToUpper() } else { "" }); & $gibShow }.GetNewClosure()
        Get = { return $(if ($gibState.Hash) { [string]$gibState.Hash } else { $null }) }.GetNewClosure() }
    $fieldCtl["m_defaultAttachments"] = New-AT3FieldEntry -Kind "attach" -Fields @("m_defaultAttachments") -Ctl @{
        Row = $attBody
        Set = { param($v) Set-AT3AttachList -State $attState -List $v }.GetNewClosure()
        Get = { return @{ List = @(Get-AT3AttachList -State $attState)
                          Changed = ((Get-AT3AttachCanon -State $attState) -ne $attState.BaseCanon) } }.GetNewClosure() }

    $loadBase = {
        param($b)
        $has = [bool]($b -and $b.Rec -and $b.Rec.values)
        foreach ($key in @($fieldCtl.Keys)) {
            $e = $fieldCtl[$key]
            $f0 = @($e.Fields)[0]
            if (-not $has) {
                Set-AT3FieldValue -Entry $e -Value $null
                Set-AT3FieldEnabled -Entry $e -On $false -Why "choose a base character first - Anatomy > Behavioral Template, then Residency > Clone from"
                continue
            }
            $vp = $b.Rec.values.PSObject.Properties[$f0]
            $wp = if ($b.Rec.unwritable) { $b.Rec.unwritable.PSObject.Properties[$f0] } else { $null }
            Set-AT3FieldValue -Entry $e -Value $(if ($vp) { $vp.Value } else { $null })
            Set-AT3FieldEnabled -Entry $e -On (-not $wp) -Why $(if ($wp) { [string]$wp.Value } else { "" })
        }
        if ($has) {
            $armToggle.IsChecked = $true
            $status.Text = ("Loaded {0} ({1}) - every field shows its real values; the ones you change are written when you build." -f $b.Rec.name, $b.Rec.hash)
        } elseif ($b) {
            $status.Text = "This base has no field values in CharacterModel.json - reopen the Character Creator to rebuild the model."
        }
    }.GetNewClosure()

    $collectEdits = {
        param($b)
        $edits = [ordered]@{}
        if (-not ($b -and $b.Rec -and $b.Rec.values)) { return $edits }
        foreach ($key in @($fieldCtl.Keys)) {
            $e = $fieldCtl[$key]
            $f0 = @($e.Fields)[0]
            if ($b.Rec.unwritable -and $b.Rec.unwritable.PSObject.Properties[$f0]) { continue }
            if ($e.Kind -eq "combo" -and $null -eq $e.Ctl.Combo.SelectedItem) { continue }
            $vp = $b.Rec.values.PSObject.Properties[$f0]
            $baseVal = if ($vp) { $vp.Value } else { $null }
            if ($e.Kind -eq "attach") {
                # Unchanged boxes send nothing; any change sends the WHOLE list,
                # untouched entries carrying their own stored numbers.
                $cur = & $e.Ctl.Get
                if ($cur.Changed) { $edits[$f0] = @($cur.List) }
                continue
            }
            if ($e.Kind -eq "multi") {
                # Compare as SETS. Unchanged sends nothing, which preserves the
                # base's order and duplicates; changed keeps the base order for
                # what stays (entries with no box are kept too) and appends
                # what was newly ticked.
                $base = @(@($baseVal) | Where-Object { $_ } | ForEach-Object { ([string]$_).ToUpper() })
                $on = @(@($e.Ctl.Boxes.Keys) | Where-Object { $e.Ctl.Boxes[$_].IsChecked } | ForEach-Object { ([string]$_).ToUpper() })
                if ((@($base | Sort-Object -Unique) -join ",") -ne (@($on | Sort-Object -Unique) -join ",")) {
                    $newList = New-Object System.Collections.ArrayList
                    foreach ($x in $base) { if (($on -contains $x) -or -not $e.Ctl.Boxes.Contains($x)) { [void]$newList.Add($x) } }
                    foreach ($x in $on) { if ($base -notcontains $x) { [void]$newList.Add($x) } }
                    $edits[$f0] = $newList.ToArray()
                }
                continue
            }
            if ($e.Kind -eq "combo" -and $e.Ctl.Combo.SelectedItem.Key -eq "SPRAY") {
                # A designed spray travels as its definition; spray.py mints the
                # record (content-addressed, so the same spray is never minted twice).
                $s = $e.Ctl.Combo.SelectedItem.Spray
                $edits[$f0] = @{ spray = @{ collectable = [string]$s.Collectable; count = [int]$s.Count; params = $s.Params } }
                continue
            }
            $cur = Get-AT3FieldValue -Entry $e
            if (-not (Test-AT3FieldSame -A $cur -B $baseVal)) {
                foreach ($f in @($e.Fields)) { $edits[$f] = $cur }
            }
        }
        return $edits
    }.GetNewClosure()

    & $loadBase $null

    # =======================================================================
    # RESIDENCY
    #
    # A character can only be spawned where every asset it references already
    # lives. A copied record brings NO geometry with it - that is why
    # Moolah_Large crashes on death outside region_02 even when its prefs
    # record has been copied in. So this tab is a manifest: pick the target
    # regions, and it says what is already there and what has to travel.
    #
    # It does not port anything yet. The porting operation is Layer 3 and is
    # not built; this is the input that feature will consume, and it is
    # useful on its own for knowing which region is cheapest to test in.
    # =======================================================================
    $rs = New-Object System.Windows.Controls.StackPanel
    [void]$rs.Children.Add((New-AT3Note ("Where this character will exist. A region only holds what has been " +
        "put there - copying a character record does NOT bring its mesh, animations or weapon along, so every " +
        "asset it references has to be resident too or the game crashes when it spawns.")))

    [void]$rs.Children.Add((New-AT3Header "---- BASE CHARACTER ----" -Accent "plum"))
    $rBase = New-AT3ComboRow -Label "Clone from" -LabelWidth 170 -ComboWidth 350
    [void]$rs.Children.Add($rBase.Row)
    [void]$rs.Children.Add((New-AT3Note ("Populated from the Behavioral Template chosen on the Anatomy tab. " +
        "This is the record the new character is cloned from, and its dependencies are what must be resident.")))

    [void]$rs.Children.Add((New-AT3Header "---- TARGET REGIONS ----" -Accent "plum"))
    $regionChecks = [ordered]@{}
    $regionWrap = New-Object System.Windows.Controls.WrapPanel
    $regionWrap.Margin = New-Object System.Windows.Thickness 0,0,0,8
    if ($model) {
        foreach ($r in $model.regions) {
            $c = New-AT3Check -Text $r.label -Checked $false -Tip ("region key: " + $r.key)
            $c.Width = 210
            $c.Margin = New-Object System.Windows.Thickness 0,0,0,4
            $c.Tag = $r.key
            $regionChecks[$r.key] = $c
            [void]$regionWrap.Children.Add($c)
        }
    }
    [void]$rs.Children.Add($regionWrap)

    [void]$rs.Children.Add((New-AT3Header "---- PORT MANIFEST ----" -Accent "plum"))
    $manifest = New-Object System.Windows.Controls.TextBlock
    $manifest.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $manifest.FontSize = 11
    $manifest.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $manifest.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#C8BB9B")
    $manifest.Text = "Pick a Behavioral Template on the Anatomy tab, then a target region."
    [void]$rs.Children.Add($manifest)
    [void]$rs.Children.Add((New-AT3Header "---- BUILD CHARACTER ----" -Accent "plum"))
    $btnPort = New-Object System.Windows.Controls.Button
    $btnPort.Content = "Build character"
    $btnPort.Height = 32
    $btnPort.MinWidth = 240
    $btnPort.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $btnPort.Margin = New-Object System.Windows.Thickness 0,2,0,6
    $btnPort.IsEnabled = $false
    [void]$rs.Children.Add($btnPort)
    $portWhy = New-Object System.Windows.Controls.TextBlock
    $portWhy.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $portWhy.FontSize = 11
    $portWhy.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $portWhy.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#8A7A5C")
    [void]$rs.Children.Add($portWhy)
    [void]$rs.Children.Add((New-AT3Note ("One button, one character. Build makes the donor's mesh, textures, " +
        "weapons and animation config resident in each target region, adds a NEW record under a hash derived " +
        "from the name you give, verifies the blockmap the game actually reads, and registers the name so the " +
        "character appears in the Spawns Editor library. It does not place a spawn instance.")))
    [void]$rs.Children.Add((New-AT3Note ("Every field on the other tabs loads the base's REAL values when you " +
        "choose it, and the ones you change are written into the new record. A field that cannot be located " +
        "on this base is disabled, with the reason on hover. Choosing a mesh from another region ports it too. " +
        "Each build backs up the target region's bundle and blockmap first and restores both on any failure.")))

    # A port needs: a base record, a source region that actually holds it, and
    # a destination. Anything missing is named rather than left to guess.
    $validatePort = {
        $b = $rBase.Combo.SelectedItem
        $want = @()
        foreach ($k in $regionChecks.Keys) { if ($regionChecks[$k].IsChecked) { $want += $k } }
        $miss = @()
        $attProblem = Get-AT3AttachProblem -State $attState
        if ($attProblem -and $b) { $miss += "Attachments: " + $attProblem }
        if ($editing) {
            if (-not $b) { $miss += "the character being edited is not loaded" }
            if (-not $want.Count) { $miss += "Residency: at least one region to save the changes in" }
            if ($miss.Count) {
                $btnPort.IsEnabled = $false
                $portWhy.Text = "Cannot save yet - still needed:" + [Environment]::NewLine +
                                (($miss | ForEach-Object { "   - " + $_ }) -join [Environment]::NewLine)
            } else {
                $btnPort.IsEnabled = $true
                $portWhy.Text = "Ready: save the changed fields into " + $b.Rec.name + " (" + $b.Rec.hash + ") in region(s) " +
                                ($want -join ", ") + ". Every spawn of it there changes too."
            }
            return
        }
        if (-not $rSkel.Combo.SelectedItem) { $miss += "Anatomy: Skeletal Species" }
        if (-not $rTmpl.Combo.SelectedItem) { $miss += "Anatomy: Behavioral Template" }
        if (-not $rGeo.Combo.SelectedItem)  { $miss += "Anatomy: Character Geometry" }
        if (-not $b)                        { $miss += "Residency: a base character to clone from" }
        if (-not $want.Count)               { $miss += "Residency: at least one target region" }
        $src = $null
        if ($b) {
            # The source must be a NUMBERED region - port_to_utility indexes
            # region_NN/lm_level_NN and cannot read a workspace as a source.
            foreach ($r in @($b.Rec.regions)) {
                if ($r -match '^[0-9]') { if ($want -notcontains $r) { $src = $r; break } }
            }
            if (-not $src) {
                foreach ($r in @($b.Rec.regions)) { if ($r -match '^[0-9]') { $src = $r; break } }
            }
            if (-not $src) { $miss += "this base lives only in a workspace - no numbered source region to copy from" }
        }
        $already = @()
        if ($b -and $src) { foreach ($t in $want) { if (@($b.Rec.regions) -contains $t) { $already += $t } } }
        if ($miss.Count) {
            $btnPort.IsEnabled = $false
            $portWhy.Text = "Cannot build yet - still needed:" + [Environment]::NewLine +
                            (($miss | ForEach-Object { "   - " + $_ }) -join [Environment]::NewLine)
        } else {
            $btnPort.IsEnabled = $true
            $t = "Ready: build a new character cloned from " + $b.Rec.name + " (source region " + $src + ") into " + ($want -join ", ") + "."
            if ($already.Count) { $t += " (already resident in " + ($already -join ", ") + " - its assets are already there; only the new record is added.)" }
            $portWhy.Text = $t
        }
    }.GetNewClosure()
    $attState.Validate = $validatePort

    # Source/target are RECOMPUTED in the click handler below, not stashed in
    # script-scoped variables. A $script: value written inside a GetNewClosure
    # scriptblock is not the same variable another closure reads back - that
    # is what made this button silently do nothing: the handler read $null and
    # hit its own guard clause with no message at all.
    $portInputs = {
        $b = $rBase.Combo.SelectedItem
        $want = @()
        foreach ($k in $regionChecks.Keys) { if ($regionChecks[$k].IsChecked) { $want += $k } }
        $src = $null
        if ($b) {
            foreach ($r in @($b.Rec.regions)) {
                if ($r -match '^[0-9]') { if ($want -notcontains $r) { $src = $r; break } }
            }
            if (-not $src) {
                foreach ($r in @($b.Rec.regions)) { if ($r -match '^[0-9]') { $src = $r; break } }
            }
        }
        return @{ Base = $b; Source = $src; Targets = $want }
    }.GetNewClosure()

    [void]$btnPort.Add_Click({
        $in = & $portInputs
        $b = $in.Base; $src = $in.Source; $targets = @($in.Targets)
        if ($editing) {
            if (-not $b -or -not $targets.Count) { return }
            $edits = & $collectEdits $b
            if (-not $edits.Count) {
                Show-AT3Notice -Title "Save Character" -Text ("Nothing to save - every field still matches " + $b.Rec.name + ".")
                return
            }
            $editLines = @(Format-AT3EditLines -Edits $edits)
            $msg = ("Save {0} change(s) to '{1}' ({2}) in region(s) {3}?" -f $edits.Count, $b.Rec.name, $b.Rec.hash, ($targets -join ", ")) +
                [Environment]::NewLine + [Environment]::NewLine +
                "This edits the EXISTING character, so every spawn of it in those regions changes too - the game's own " +
                "placements included. Each region's bundle and blockmap are backed up first and restored if anything fails." +
                [Environment]::NewLine + [Environment]::NewLine + (@($editLines | Select-Object -First 14) -join [Environment]::NewLine) +
                $(if ($editLines.Count -gt 14) { [Environment]::NewLine + ("...and {0} more" -f ($editLines.Count - 14)) } else { "" })
            if (-not (Confirm-AT3Choice -Title "Save Character" -Text $msg)) { $portWhy.Text = "Save cancelled - nothing was written."; return }
            $argv = @((Join-Path $ModToolsDir "edit_character.py"), $b.Rec.hash)
            foreach ($t in $targets) { $argv += @("--to", $t) }
            $editsPath = Join-Path ([System.IO.Path]::GetTempPath()) ("at3_cedits_" + [guid]::NewGuid().ToString("N") + ".json")
            # Depth 6: an attachment list is edits > list > entry > numbers, and
            # ConvertTo-Json silently flattens anything deeper than -Depth.
            [System.IO.File]::WriteAllText($editsPath, ($edits | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding $false))
            $argv += @("--edits", $editsPath)
            $r = Invoke-AT3Python -Arguments $argv -Activity ("Saving " + $b.Rec.name)
            Remove-Item -LiteralPath $editsPath -ErrorAction SilentlyContinue
            $txt = [string]$r.Output
            Write-AT3Log ("edit '" + $b.Rec.name + "' " + $b.Rec.hash + " edits [" + ($editLines -join "; ") + "] ok=" + $r.Ok + " :: " + ($txt -replace "`r?`n", " | "))
            $manifest.Text = $txt
            $done = @([regex]::Matches($txt, "(EDITED|UNCHANGED) [0-9A-F]{8} in region (\S+)") | ForEach-Object { $_.Groups[2].Value })
            $problem = @($txt -split "`r?`n" | Where-Object { $_ -match "REFUSED|FAILED" })
            if ($done.Count) {
                [void](Update-AT3Index)
                [void](Update-AT3Catalogue)
                [void](Update-AT3CharacterModel)
                # The form now compares against the SAVED values, so a second
                # save only sends what changed after this one.
                $fresh = Get-AT3CharacterModel
                if ($fresh) {
                    foreach ($skp in $fresh.skeletons.PSObject.Properties) {
                        foreach ($tpp in $skp.Value.templates.PSObject.Properties) {
                            foreach ($cc in @($tpp.Value.characters)) { if ([string]$cc.hash -eq [string]$b.Rec.hash) { $b.Rec = $cc } }
                        }
                    }
                    & $loadBase $b
                }
            }
            if ($done.Count -eq $targets.Count -and -not $problem.Count) {
                $portWhy.Text = "Saved " + $b.Rec.name + " in region(s) " + ($done -join ", ") + "."
                Show-AT3Notice -Title "Save Character" -Text ("'" + $b.Rec.name + "' was saved in region(s): " + ($done -join ", ") +
                    [Environment]::NewLine + [Environment]::NewLine + "Every spawn of it there uses the new values. To undo one region: " +
                    "python ModTools\edit_character.py --revert " + $b.Rec.hash + " --to <region>")
            } else {
                $portWhy.Text = "Save did not complete in every region - see the manifest box above for the reason."
                Show-AT3Notice -Title "Save Character" -Icon "Warning" -Text (((@($done | ForEach-Object { "saved: region " + $_ }) + $problem) -join [Environment]::NewLine) +
                    [Environment]::NewLine + [Environment]::NewLine + "Any region that failed was restored from its backup.")
            }
            return
        }
        if (-not $b -or -not $src -or -not $targets.Count) {
            [void][System.Windows.MessageBox]::Show(
                ("Nothing to build." + [Environment]::NewLine +
                 "base: " + $(if ($b) { $b.Rec.name } else { "(none)" }) + [Environment]::NewLine +
                 "source region: " + $(if ($src) { $src } else { "(none)" }) + [Environment]::NewLine +
                 "targets: " + $(if ($targets.Count) { $targets -join ", " } else { "(none)" })),
                "Build Character", "OK", "Warning")
            return
        }
        $edits = & $collectEdits $b
        $editLines = @(Format-AT3EditLines -Edits $edits)
        $name = Show-AT3BuildDialog -Regions $targets -BaseName $b.Rec.name -Edits $editLines
        if (-not $name) { $portWhy.Text = "Build cancelled - nothing was written."; return }
        $argv = @((Join-Path $ModToolsDir "build_character.py"), $b.Rec.hash, "--from", $src,
                  "--name", $name, "--donor-name", ([string]$b.Rec.name -replace '"', ''))
        foreach ($t in $targets) { $argv += @("--to", $t) }
        $editsPath = Join-Path ([System.IO.Path]::GetTempPath()) ("at3_edits_" + [guid]::NewGuid().ToString("N") + ".json")
        $editsJson = if ($edits.Count) { $edits | ConvertTo-Json -Depth 6 } else { "{}" }
        [System.IO.File]::WriteAllText($editsPath, $editsJson, (New-Object System.Text.UTF8Encoding $false))
        $argv += @("--edits", $editsPath)
        $r = Invoke-AT3Python -Arguments $argv -Activity ("Building " + $name)
        Remove-Item -LiteralPath $editsPath -ErrorAction SilentlyContinue
        $txt = [string]$r.Output
        Write-AT3Log ("build '" + $name + "' from " + $b.Rec.hash + " edits [" + ($editLines -join "; ") + "] ok=" + $r.Ok + " :: " + ($txt -replace "`r?`n", " | "))
        $manifest.Text = $txt
        $built = @([regex]::Matches($txt, "BUILT ([0-9A-F]{8}) into region (\S+)") | ForEach-Object { $_.Groups[2].Value + " (" + $_.Groups[1].Value + ")" })
        if ($built.Count) {
            [void](Update-AT3Index)
            [void](Update-AT3Catalogue)
            [void](Update-AT3CharacterModel)
        }
        $problem = @($txt -split "`r?`n" | Where-Object { $_ -match "REFUSED|FAILED" })
        if ($built.Count -and -not $problem.Count) {
            $portWhy.Text = "Built '" + $name + "' into " + ($built -join ", ") + "."
            [void][System.Windows.MessageBox]::Show(
                ("'" + $name + "' was built into region(s): " + ($built -join ", ") + [Environment]::NewLine + [Environment]::NewLine +
                 "It is now in the character library. To see it in game, place an instance with Map Editor > Spawns Editor."),
                "Build Character", "OK", "Information")
        } else {
            $portWhy.Text = "Build did not complete - see the manifest box above for the reason."
            [void][System.Windows.MessageBox]::Show(
                ((@($built | ForEach-Object { "built: " + $_ }) + $problem) -join [Environment]::NewLine) +
                 [Environment]::NewLine + [Environment]::NewLine + "Any region that failed was restored from its backup.",
                "Build Character", "OK", "Warning")
        }
    }.GetNewClosure())

    $updateManifest = {
        $b = $rBase.Combo.SelectedItem
        $want = @()
        foreach ($k in $regionChecks.Keys) { if ($regionChecks[$k].IsChecked) { $want += $k } }
        if (-not $b) { $manifest.Text = "No base character - choose a Behavioral Template on the Anatomy tab."; return }
        if (-not $want.Count) { $manifest.Text = "No target region selected."; return }
        $lines = @()
        $need = 0
        foreach ($tgt in $want) {
            $lines += ("region " + $tgt + ":")
            $rows = @(, [pscustomobject]@{ what = "character"; name = $b.Rec.name; regions = @($b.Rec.regions) })
            foreach ($d in $b.Rec.deps) {
                $rows += [pscustomobject]@{ what = $d.what; name = $d.name; regions = @($d.regions) }
            }
            foreach ($r in $rows) {
                $have = $r.regions -contains $tgt
                if (-not $have) { $need++ }
                $lines += ("   {0}  {1,-14} {2,-30} {3}" -f
                    $(if ($have) { "resident" } else { "PORT    " }), $r.what, $r.name,
                    $(if (@($r.regions).Count) { "(in " + (@($r.regions) -join ",") + ")" } else { "(nowhere)" }))
            }
        }
        if ($need -eq 0) {
            $lines += ""
            $lines += "Nothing to port - every asset is already resident. Safe to spawn here."
        } else {
            $lines += ""
            $lines += ("{0} asset(s) must be ported before this character can spawn." -f $need)
        }
        $manifest.Text = ($lines -join [Environment]::NewLine)
    }.GetNewClosure()

    [void]$rBase.Combo.Add_SelectionChanged({ & $updateManifest; & $loadBase $rBase.Combo.SelectedItem; & $validatePort }.GetNewClosure())
    foreach ($k in $regionChecks.Keys) {
        [void]$regionChecks[$k].Add_Checked({   & $updateManifest; & $validatePort }.GetNewClosure())
        [void]$regionChecks[$k].Add_Unchecked({ & $updateManifest; & $validatePort }.GetNewClosure())
    }

    # Anatomy's template picker feeds this tab's base list.
    [void]$rTmpl.Combo.Add_SelectionChanged({
        $t = $rTmpl.Combo.SelectedItem
        $rBase.Combo.Items.Clear()
        if (-not $t) { return }
        # Stock donors first. A custom clone - one of your own test builds - is
        # still offered, but must not silently become the default base.
        foreach ($c in @($t.Node.characters | Sort-Object @{ Expression = { if ($_.origin -eq "stock") { 0 } else { 1 } } }, @{ Expression = { $_.name } })) {
            $tag = ""
            if ($c.origin -ne "stock") { $tag = "  [" + $c.origin + "]" }
            [void]$rBase.Combo.Items.Add([pscustomobject]@{
                Display = ("{0}  {1}  (in {2}){3}" -f $c.hash, $c.name,
                           $(if (@($c.regions).Count) { @($c.regions) -join "," } else { "nowhere" }), $tag)
                Rec = $c })
        }
        if ($rBase.Combo.Items.Count -ge 1) { $rBase.Combo.SelectedIndex = 0 }
        & $validatePort
    }.GetNewClosure())
    [void]$rGeo.Combo.Add_SelectionChanged({ & $validatePort }.GetNewClosure())
    & $validatePort

    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Anatomy" -Content $an))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Residency" -Content $rs))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Physical Attributes" -Content $ph))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Behavior" -Content $bh))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Rewards" -Content $rw))
    $attTab = New-AT3CreatorTab -Header "Attachments" -Content $att -Disabled
    [System.Windows.Controls.ToolTipService]::SetShowOnDisabled($attTab, $true)
    $attState.Tab = $attTab
    [void]$tabs.Items.Add($attTab)
    & $attGate
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Experimental" -Content $ex))
    [void]$root.Children.Add($tabs)

    foreach ($b in $top.Children) {
        [void]$b.Add_Click({
            param($s, $e)
            switch ([string]$s.Tag) {
                "new" {
                    if ($editing) {
                        & $loadBase $rBase.Combo.SelectedItem
                        & $validatePort
                        $status.Text = "Reset - every field is back to the character's saved values."
                        return
                    }
                    $rSkel.Combo.SelectedIndex = -1
                    $rTmpl.Combo.Items.Clear(); $rTmpl.Combo.IsEnabled = $false
                    $rGeo.Combo.Items.Clear();  $rGeo.Combo.IsEnabled = $false
                    $rAff.Combo.SelectedIndex = -1
                    $rVoice.Combo.SelectedIndex = -1
                    $rPitch.Combo.SelectedIndex = -1
                    $rBase.Combo.Items.Clear()
                    $eligible.Text = ""
                    $status.Text = "Cleared. Pick a Skeletal Species and Behavioral Template first - together they choose the record this character is cloned from, which fills in every other default."
                }
            }
        }.GetNewClosure())
    }

    if (-not $status.Text) {
        $n = ($model.skeletons.PSObject.Properties | Measure-Object).Count
        $status.Text = ("{0} skeletons - {1}. Choose a base: every field loads that character's real values, and Build writes the ones you change." `
            -f $n, $script:CharModelNote)
    }

    if ($editing) {
        # Open ON the character: skeleton, template and base picked exactly as a
        # user would pick them, then locked - an edit changes fields, not what
        # the record is.
        foreach ($it in $rSkel.Combo.Items) { if ([string]$it.Key -eq [string]$EditTarget.Skel) { $rSkel.Combo.SelectedItem = $it } }
        foreach ($it in $rTmpl.Combo.Items) { if ([string]$it.Key -eq [string]$EditTarget.Tmpl) { $rTmpl.Combo.SelectedItem = $it } }
        foreach ($it in $rBase.Combo.Items) { if ([string]$it.Rec.hash -eq [string]$EditTarget.Hash) { $rBase.Combo.SelectedItem = $it } }
        $lockTip = "Editing an existing character - its skeleton, template and record are fixed. Use Create New to make a different one."
        foreach ($lr in @($rSkel, $rTmpl, $rBase)) {
            $lr.Combo.IsEnabled = $false
            [System.Windows.Controls.ToolTipService]::SetShowOnDisabled($lr.Combo, $true)
            $lr.Combo.ToolTip = $lockTip
        }
        $held = @($EditTarget.Rec.regions)
        foreach ($k in @($regionChecks.Keys)) {
            # edit_character.py edits numbered regions only - a ticked utility
            # box would be refused on save, so it is disabled with the reason.
            if ($k -match '^[0-9]' -and $held -contains $k) {
                $regionChecks[$k].IsChecked = $true
            } else {
                $regionChecks[$k].IsEnabled = $false
                [System.Windows.Controls.ToolTipService]::SetShowOnDisabled($regionChecks[$k], $true)
                $regionChecks[$k].ToolTip = $(if ($k -match '^[0-9]') { "This character does not exist in " + $k + "." } else { $k + " is not a numbered region - only those can be edited in place." })
            }
        }
        $btnPort.Content = "Save changes to character"
        [void]$rs.Children.Insert(0, (New-AT3Note ("EDITING " + [string]$EditTarget.Name + " (" + [string]$EditTarget.Hash + "). Save writes the " +
            "fields you change back into this record in each ticked region - it keeps its hash, so every spawn of it there changes " +
            "too. A newly chosen mesh, weapon, drop or ammo type is ported into the region first. Regions this character is not in " +
            "cannot be ticked.")))
        $status.Text = ("Editing " + [string]$EditTarget.Name + " (" + [string]$EditTarget.Hash + ") - every field shows its current values; the ones you change are saved in place.")
        & $validatePort
    }

    $w.Content = $root
    [void]$w.ShowDialog()
}

# ===========================================================================
# GEOMETRY PICKER
#
# Every NAMED geometry record in the game, searchable - the Map Editor's
# object-library pattern. Rows come from GeometryCatalog.csv, which
# char_model.py writes beside CharacterModel.json whenever the game data
# changes; it is read only when this window opens, so a 3,420-row list costs
# nothing until someone asks for it. The chosen row comes back on the window's
# Tag, or $null (Tag, not $script: - see Show-AT3BuildDialog).
# ===========================================================================
function Show-AT3GeometryPicker {
    param([string]$Purpose = "projectile")
    $csvPath = Join-Path $AT3Dir "GeometryCatalog.csv"
    if (-not (Test-Path $csvPath)) { [void](Update-AT3CharacterModel) }
    if (-not (Test-Path $csvPath)) {
        Show-AT3Notice -Title "Choose Geometry" -Icon "Warning" -Text "GeometryCatalog.csv could not be built. See at3_debug.log."
        return $null
    }
    $all = New-Object System.Collections.ArrayList
    foreach ($r in @(Import-Csv -LiteralPath $csvPath)) {
        $reg = @(([string]$r.Regions) -split "," | Where-Object { $_ })
        $glob = ([string]$r.Global -eq "1")
        [void]$all.Add([pscustomobject]@{
            Name = [string]$r.Name; Folder = [string]$r.Folder; Hash = [string]$r.Hash; Path = [string]$r.Path
            KB = [int]$r.KB; Regions = $reg; Global = $glob
            Where = $(if ($glob) { "global" } else { $reg -join "," })
            Search = ([string]$r.Name + " " + [string]$r.Folder + " " + [string]$r.Hash).ToLowerInvariant() })
    }
    $noteText = ("Every named mesh in the game - {0} of them. Any can be written into the {1} slot, but only the ones a " +
        "shipped weapon fires are known to work: how any other mesh renders in flight, and at what size, is untested - no " +
        "projectile scale field is known. Character meshes will not animate, and entries under levels\ are whole pieces of " +
        "terrain. Building ports the chosen mesh and its textures from a region that holds it. Search matches every word " +
        "you type, in the name, folder or hash.")
    if ($Purpose -eq "attachment") {
        $noteText = ("Every named mesh in the game - {0} of them. Any can be worn. The ones under attachments\ were authored " +
            "to sit on a bone; any other mesh hangs from the bone at its own pivot and authored size, so expect to adjust " +
            "its position, rotation and scale - the Killer Clakker's shovel is a debris chunk worn this way. Character meshes " +
            "will not animate, and entries under levels\ are whole pieces of terrain. Building or saving ports the chosen " +
            "mesh and its textures from a region that holds it. Search matches every word you type, in the name, folder or hash.")
    }
    if ($Purpose -eq "prop") {
        $noteText = ("Every named mesh in the game - {0} of them. The chosen one is copied into this region with its " +
            "textures and its home bundle's lighting records, and added to the Object Library as '(ported)'. It lights " +
            "with the region's uniform fallback rather than its own baked lighting, so it may look flatter or brighter " +
            "than native props. Character meshes will not animate; entries under levels\ are whole pieces of terrain. " +
            "Search matches every word you type, in the name, folder or hash.")
    }
    return (Show-AT3SearchPicker -Title "Choose Geometry" -Note ($noteText -f $all.Count, $Purpose) -Items $all `
        -OkText "Use this geometry" -Noun "geometries" -Columns @(
            @{ H = "Geometry";    B = "Name";   W = 0 },
            @{ H = "Folder";      B = "Folder"; W = 340 },
            @{ H = "Resident in"; B = "Where";  W = 150 },
            @{ H = "KB";          B = "KB";     W = 60 },
            @{ H = "Hash";        B = "Hash";   W = 80 }))
}

# ===========================================================================
# SEARCH PICKER
#
# The Map Editor's object-library pattern as one reusable window: a note, a
# search bar that must match EVERY word typed, a sortable read-only grid and an
# OK button (double-click works too). Items need a lower-case `Search`
# property. Used by the geometry picker and the Character Library.
# ===========================================================================
function Show-AT3SearchPicker {
    param([string]$Title, [string]$Note, $Items, $Columns, [string]$OkText = "Use this",
          [string]$Noun = "items", [int]$Width = 960)
    $all = New-Object System.Collections.ArrayList
    foreach ($it in @($Items)) { [void]$all.Add($it) }

    $w = New-AT3Panel -Title $Title -Width $Width -Height 700 -Accent "plum"
    $conv = New-Object System.Windows.Media.BrushConverter
    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 12

    # Not $note: PowerShell names ignore case, so that IS the [string]$Note
    # parameter and the TextBlock would be converted to its type name.
    $noteBlock = New-AT3Note $Note
    [void][System.Windows.Controls.DockPanel]::SetDock($noteBlock, "Top")
    [void]$root.Children.Add($noteBlock)

    $searchBar = New-Object System.Windows.Controls.DockPanel
    $searchBar.Margin = New-Object System.Windows.Thickness 0,0,0,8
    [void][System.Windows.Controls.DockPanel]::SetDock($searchBar, "Top")
    [void]$root.Children.Add($searchBar)
    $sl = New-Object System.Windows.Controls.TextBlock
    $sl.Text = "Search"
    $sl.Width = 60
    $sl.VerticalAlignment = "Center"
    $sl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $sl.Foreground = $conv.ConvertFromString("#E8D9B5")
    [void]$searchBar.Children.Add($sl)
    $search = New-Object System.Windows.Controls.TextBox
    $search.Height = 24
    $search.Background = $conv.ConvertFromString("#2A1F16")
    $search.Foreground = $conv.ConvertFromString("#F2E4C4")
    $search.BorderBrush = $conv.ConvertFromString("#8A5C84")
    $search.VerticalContentAlignment = [System.Windows.VerticalAlignment]::Center
    [void]$searchBar.Children.Add($search)

    $bar = New-Object System.Windows.Controls.DockPanel
    $bar.Margin = New-Object System.Windows.Thickness 0,8,0,0
    [void][System.Windows.Controls.DockPanel]::SetDock($bar, "Bottom")
    [void]$root.Children.Add($bar)
    $bCancel = New-Object System.Windows.Controls.Button
    $bCancel.Content = "Cancel"; $bCancel.Height = 30; $bCancel.MinWidth = 100
    $bCancel.Margin = New-Object System.Windows.Thickness 8,0,0,0
    [void][System.Windows.Controls.DockPanel]::SetDock($bCancel, "Right")
    [void]$bar.Children.Add($bCancel)
    $bOk = New-Object System.Windows.Controls.Button
    $bOk.Content = $OkText; $bOk.Height = 30; $bOk.MinWidth = 170
    $bOk.Margin = New-Object System.Windows.Thickness 8,0,0,0
    $bOk.IsEnabled = $false
    [void][System.Windows.Controls.DockPanel]::SetDock($bOk, "Right")
    [void]$bar.Children.Add($bOk)
    $count = New-Object System.Windows.Controls.TextBlock
    $count.VerticalAlignment = "Center"
    $count.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $count.FontSize = 11
    $count.Foreground = $conv.ConvertFromString("#C8BB9B")
    $count.Text = ("{0} {1}" -f $all.Count, $Noun)
    [void]$bar.Children.Add($count)

    $grid = New-Object System.Windows.Controls.DataGrid
    $grid.AutoGenerateColumns = $false
    $grid.CanUserAddRows = $false
    $grid.IsReadOnly = $true
    $grid.SelectionMode = "Single"
    $grid.HeadersVisibility = "Column"
    $grid.GridLinesVisibility = "Horizontal"
    $grid.Background = $conv.ConvertFromString("#120D0A")
    $grid.RowBackground = $conv.ConvertFromString("#1B1410")
    $grid.Foreground = $conv.ConvertFromString("#E8D9B5")
    $grid.BorderBrush = $conv.ConvertFromString("#4A3524")
    $grid.VerticalScrollBarVisibility = "Visible"
    foreach ($spec in @($Columns)) {
        $col = New-Object System.Windows.Controls.DataGridTextColumn
        $col.Header = $spec.H
        $col.Binding = New-Object System.Windows.Data.Binding $spec.B
        if ($spec.W -eq 0) {
            $col.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.GridUnitType]::Star)
        } else {
            $col.Width = New-Object System.Windows.Controls.DataGridLength $spec.W
        }
        [void]$grid.Columns.Add($col)
    }
    $grid.ItemsSource = $all
    [void]$root.Children.Add($grid)

    # Every word must match - "barrel explosive" finds barrel_explosive.geo in
    # any folder. A foreach, not Where-Object: this runs on every keystroke over
    # 3,420 rows, and the pipeline is several times slower in PowerShell 5.1.
    [void]$search.Add_TextChanged({
        $terms = @(([string]$search.Text).Trim().ToLowerInvariant() -split "\s+" | Where-Object { $_ })
        if (-not $terms.Count) {
            $grid.ItemsSource = $all
            $count.Text = ("{0} {1}" -f $all.Count, $Noun)
            return
        }
        $hits = New-Object System.Collections.ArrayList
        foreach ($it in $all) {
            $ok = $true
            foreach ($t in $terms) { if (-not $it.Search.Contains($t)) { $ok = $false; break } }
            if ($ok) { [void]$hits.Add($it) }
        }
        $grid.ItemsSource = $hits
        $count.Text = ("{0} of {1} {2} match" -f $hits.Count, $all.Count, $Noun)
    }.GetNewClosure())

    [void]$grid.Add_SelectionChanged({ $bOk.IsEnabled = ($null -ne $grid.SelectedItem) }.GetNewClosure())
    $w.Tag = $null
    $use = {
        $sel = $grid.SelectedItem
        if (-not $sel) { return }
        $w.Tag = $sel
        $w.DialogResult = $true
        $w.Close()
    }.GetNewClosure()
    [void]$bOk.Add_Click({ & $use }.GetNewClosure())
    [void]$grid.Add_MouseDoubleClick({ & $use }.GetNewClosure())
    [void]$bCancel.Add_Click({ $w.Tag = $null; $w.Close() }.GetNewClosure())
    [void]$w.Add_Loaded({ [void]$search.Focus() }.GetNewClosure())

    $w.Content = $root
    [void]$w.ShowDialog()
    return $w.Tag
}


# ===========================================================================
# WEAPON CREATOR
#
# The Character Creator's shape, for the same reasons. Every dial loads the
# chosen base's REAL values from CharacterModel.json - read through
# weapon_fields.py, the same locators build_weapon.py writes through. A field
# that cannot be located on that base is disabled with the reason on hover,
# and Build writes only what differs from the base.
#
# A weapon drags less with it than a character: its effect record, the
# projectile mesh and textures, particle prefs, and the per-surface impact
# records the engine composes from NAME strings (no dword points at those -
# weapon_fields.needs finds them). Sounds are in the global audio banks and
# never travel.
# ===========================================================================
function Show-AT3WeaponCreator {
    $w = New-AT3Panel -Title "Weapon Studio" -Width 560 -Height 350 -Accent "plum"
    $sp = New-Object System.Windows.Controls.StackPanel
    $sp.Margin = New-Object System.Windows.Thickness 22

    $ttl = New-Object System.Windows.Controls.TextBlock
    $ttl.Text = "Welcome to the Weapon Studio"
    $ttl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $ttl.FontSize = 17
    $ttl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#D9A0D0")
    $ttl.Margin = New-Object System.Windows.Thickness 0,0,0,16
    [void]$sp.Children.Add($ttl)

    $bNew = New-Object System.Windows.Controls.Button
    $bNew.Content = "Create New"
    $bNew.Height = 34
    $bNew.FontSize = 13
    $bNew.Margin = New-Object System.Windows.Thickness 0,0,0,4
    [void]$sp.Children.Add($bNew)
    [void]$sp.Children.Add((New-AT3Note ("Start from one of the game's own weapons. Pick its type and the weapon to " +
        "clone - every tab then loads that weapon's real values, and Build writes a new weapon under its own hash.")))

    # Cloning an existing weapon is already what Create New does, so the second
    # button EDITS one in place instead (edit_weapon.py) - the Character
    # Studio's Edit Existing, for weapons.
    $bLoad = New-Object System.Windows.Controls.Button
    $bLoad.Content = "Edit Existing"
    $bLoad.Height = 34
    $bLoad.FontSize = 13
    $bLoad.Margin = New-Object System.Windows.Thickness 0,8,0,4
    [void]$sp.Children.Add($bLoad)
    [void]$sp.Children.Add((New-AT3Note ("Change a weapon that already exists - one of the game's own, or one you built - " +
        "in place. It keeps its hash, so every character carrying it changes too: give a rifle a bigger clip and every " +
        "character armed with it, in the regions you choose, gets the bigger clip.")))

    $w.Tag = $null
    [void]$bNew.Add_Click({ $w.Tag = "new"; $w.DialogResult = $true; $w.Close() }.GetNewClosure())
    [void]$bLoad.Add_Click({ $w.Tag = "edit"; $w.DialogResult = $true; $w.Close() }.GetNewClosure())
    $w.Content = $sp
    $r = $w.ShowDialog()
    if ($r -ne $true) { return }
    if ($w.Tag -eq "edit") {
        $pick = Show-AT3WeaponLibraryPicker
        if ($pick) { Show-AT3WeaponCreatorForm -EditTarget $pick }
    } else {
        Show-AT3WeaponCreatorForm
    }
}

# ===========================================================================
# WEAPON LIBRARY PICKER  (Weapon Studio > Edit Existing)
#
# Every weapon the model knows - the game's own and this project's - with what
# it fires and who carries it, because editing a weapon in place changes every
# one of those carriers.
# ===========================================================================
function Show-AT3WeaponLibraryPicker {
    $model = Get-AT3CharacterModel
    if ($model -and -not $model.PSObject.Properties["weapons"]) {
        [void](Update-AT3CharacterModel)
        $model = Get-AT3CharacterModel
    }
    if (-not $model -or -not $model.PSObject.Properties["weapons"]) {
        Show-AT3Notice -Title "Weapon Library" -Icon "Warning" -Text "CharacterModel.json could not be built. See at3_debug.log."
        return $null
    }
    $rows = New-Object System.Collections.ArrayList
    foreach ($x in @($model.weapons | Sort-Object @{ Expression = { $_.name } })) {
        $cb = @(@($x.carried_by) + @($x.carried_by_custom) | Where-Object { $_ })
        [void]$rows.Add([pscustomobject]@{
            Name = [string]$x.name; Hash = [string]$x.hash; Type = [string]$x.type
            Projectile = [string]$x.projectile; CarriedBy = ($cb -join ", ")
            Origin = [string]$x.origin; Regions = (@($x.regions) -join ","); Rec = $x
            Search = ([string]$x.name + " " + [string]$x.hash + " " + [string]$x.type + " " + [string]$x.projectile + " " +
                      [string]$x.origin + " " + ($cb -join " ")).ToLowerInvariant() })
    }
    $note = ("Every weapon in the game's files - {0} of them, the game's own and the ones you built. Pick one to edit it IN " +
        "PLACE: it keeps its hash, so every character carrying it, in the regions you save to, changes too. Search matches " +
        "every word you type, in the name, hash, type, projectile, origin or carrier.") -f $rows.Count
    return (Show-AT3SearchPicker -Title "Weapon Library" -Note $note -Items $rows -OkText "Edit this weapon" `
        -Noun "weapons" -Width 1080 -Columns @(
            @{ H = "Weapon";     B = "Name";       W = 0 },
            @{ H = "Hash";       B = "Hash";       W = 80 },
            @{ H = "Type";       B = "Type";       W = 90 },
            @{ H = "Fires";      B = "Projectile"; W = 150 },
            @{ H = "Carried by"; B = "CarriedBy";  W = 230 },
            @{ H = "Origin";     B = "Origin";     W = 60 },
            @{ H = "Regions";    B = "Regions";    W = 120 }))
}

function Show-AT3WeaponCreatorForm {
    # -EditTarget (a Show-AT3WeaponLibraryPicker row) opens the form ON an
    # existing weapon: type and record preselected and locked, and Save writes
    # the changed fields back into that weapon in place (edit_weapon.py).
    param($EditTarget)
    $editing = [bool]$EditTarget
    $w = New-AT3Panel -Title $(if ($editing) { "Weapon Editor - " + [string]$EditTarget.Name } else { "Weapon Creator" }) `
        -Width 900 -Height 720 -Accent "plum"
    $conv = New-Object System.Windows.Media.BrushConverter

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 12

    $status = New-Object System.Windows.Controls.TextBlock
    $status.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $status.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $status.FontSize = 11
    $status.Margin = New-Object System.Windows.Thickness 0,10,0,0
    $status.Foreground = $conv.ConvertFromString("#C8BB9B")
    [void][System.Windows.Controls.DockPanel]::SetDock($status, "Bottom")
    [void]$root.Children.Add($status)

    $model = Get-AT3CharacterModel
    # A CharacterModel.json written before the Weapon Creator existed has no
    # weapon list, and nothing in the game data changed to make it look stale.
    if ($model -and -not $model.PSObject.Properties["weapons"]) {
        [void](Update-AT3CharacterModel)
        $model = Get-AT3CharacterModel
    }
    $allWeapons = @()
    if ($model -and $model.PSObject.Properties["weapons"]) { $allWeapons = @($model.weapons) }
    $weapons = $allWeapons
    $assets = $null
    if ($model -and $model.PSObject.Properties["weapon_assets"]) { $assets = $model.weapon_assets }
    if (-not $model) {
        $status.Text = "CharacterModel.json could not be built. See at3_debug.log."
    }

    $top = New-Object System.Windows.Controls.StackPanel
    $top.Orientation = "Horizontal"
    $top.Margin = New-Object System.Windows.Thickness 0,0,0,10
    [void][System.Windows.Controls.DockPanel]::SetDock($top, "Top")
    $bClear = New-Object System.Windows.Controls.Button
    $bClear.Content = $(if ($editing) { "Reset" } else { "Clear All" })
    $bClear.Height = 26
    $bClear.MinWidth = 120
    $bClear.FontSize = 12
    [void]$top.Children.Add($bClear)
    [void]$root.Children.Add($top)
    $tabs = New-Object System.Windows.Controls.TabControl

    # One row per numeric field, registered by the weapon_fields name it writes.
    $numRows = [ordered]@{}
    $addNum = {
        param($panel, [string]$field, [string]$label, [string]$tip)
        $r = New-AT3Field -Label $label -Value "" -Default ""
        $r.Row.ToolTip = $tip
        $numRows[$field] = $r
        [void]$panel.Children.Add($r.Row)
    }

    # =======================================================================
    # BASE
    # =======================================================================
    $bs = New-Object System.Windows.Controls.StackPanel
    [void]$bs.Children.Add((New-AT3Note ("Every weapon starts as a copy of an existing one. Choose its type, then the " +
        "weapon to clone: every other tab loads that weapon's real values, and Build writes a NEW weapon under its own " +
        "hash. The original, and every character carrying it, stay exactly as they were.")))
    [void]$bs.Children.Add((New-AT3Header "---- BASE WEAPON ----" -Accent "plum"))
    $rType = New-AT3ComboRow -Label "Weapon type" -ComboWidth 320
    $rBase = New-AT3ComboRow -Label "Clone from" -ComboWidth 580
    [void]$bs.Children.Add($rType.Row)
    [void]$bs.Children.Add($rBase.Row)
    $baseInfo = New-Object System.Windows.Controls.TextBlock
    $baseInfo.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $baseInfo.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $baseInfo.FontSize = 11
    $baseInfo.Margin = New-Object System.Windows.Thickness 190,2,0,10
    $baseInfo.Foreground = $conv.ConvertFromString("#8A7A5C")
    [void]$bs.Children.Add($baseInfo)
    $slotText = "The type is a word stored inside the record, and it decides which character slot can hold the weapon."
    if ($model -and $model.PSObject.Properties["weapon_slots"]) {
        $slotText += (" Shipped characters carry " + (@($model.weapon_slots.melee) -join ", ") + " in the MELEE slot and " +
                      (@($model.weapon_slots.ranged) -join ", ") + " in the RANGED slot. A Turret fits neither.")
    }
    [void]$bs.Children.Add((New-AT3Note $slotText))
    [void]$bs.Children.Add((New-AT3Header "---- TYPE WRITTEN ----" -Accent "plum"))
    $rClass = New-AT3ComboRow -Label "Type" -ComboWidth 320
    [void]$bs.Children.Add($rClass.Row)
    [void]$bs.Children.Add((New-AT3Note ("m_weaponType. One conversion is proven in game, so it is the only one offered: a " +
        "Turret retyped to Firearm can be carried in a ranged slot, and fires at the turret's own rate with its own " +
        "projectiles (tested 2026-09-07, BoatTurret on a wolvark shooter). Nothing carries a Turret otherwise, so this is " +
        "what makes the eight turret weapons usable at all. It does not make anything fire without a navmesh.")))

    $byType = @{}
    foreach ($x in $weapons) {
        $t = [string]$x.type
        if (-not $byType.ContainsKey($t)) { $byType[$t] = @{ n = 0; slot = $x.slot } }
        $byType[$t].n++
    }
    foreach ($t in @($byType.Keys | Sort-Object @{ Expression = { -$byType[$_].n } }, @{ Expression = { $_ } })) {
        $slotTag = switch ([string]$byType[$t].slot) { "melee" { "melee slot" } "ranged" { "ranged slot" } default { "no character slot" } }
        [void]$rType.Combo.Items.Add([pscustomobject]@{
            Display = ("{0}   ({1} weapon(s), {2})" -f $t, $byType[$t].n, $slotTag); Key = $t })
    }

    # =======================================================================
    # PROJECTILE & EFFECTS
    # =======================================================================
    $fx = New-Object System.Windows.Controls.StackPanel
    [void]$fx.Children.Add((New-AT3Note ("What the weapon throws, and what happens where it lands. These live in the weapon's " +
        "EFFECT record, not in the weapon itself - and effect records are shared (11 of 59 vanilla ones serve more than one " +
        $(if ($editing) {
            "weapon). When you save a change here, the effect record is edited in place only where nothing else uses it; " +
            "where other weapons share it, this weapon gets its own copy and theirs stay exactly as they were."
        } else {
            "weapon) - so changing anything on this tab gives the new weapon an effect record of its own."
        }))))
    [void]$fx.Children.Add((New-AT3Header "---- PROJECTILE ----" -Accent "plum"))
    $rProj = New-AT3ComboRow -Label "Projectile mesh" -ComboWidth 580
    [void]$fx.Children.Add($rProj.Row)
    [void]$fx.Children.Add((New-AT3Note ("The mesh that flies from the muzzle to the target. Melee weapons carry none. " +
        "Listed first: every mesh a shipped weapon fires. 'Choose other Geometry...' at the bottom opens every named mesh in " +
        "the game - any of them can be written here, but how they render in flight is untested. A mesh from another region " +
        "is ported with its textures.")))
    [void]$fx.Children.Add((New-AT3Header "---- IMPACT ----" -Accent "plum"))
    $rSnd = New-AT3ComboRow -Label "Impact sounds" -ComboWidth 580
    [void]$fx.Children.Add($rSnd.Row)
    [void]$fx.Children.Add((New-AT3Note ("Two cue names: ricochet, then hit or stick. The cues live in the global audio banks, " +
        "so any sound set works in every region and nothing is ported for it.")))
    $rMix = New-AT3ComboRow -Label "Impact effects" -ComboWidth 580
    [void]$fx.Children.Add($rMix.Row)
    [void]$fx.Children.Add((New-AT3Note ("Up to three effect-set NAMES - ricochet, stick, damage. The engine appends the surface " +
        "that was hit (flesh, metal, rock, snow, water, wood) and loads that record by name. No record points at those by " +
        "hash, so Build ports every surface variant explicitly. 'weapon_surface' is the global set most weapons use.")))
    [void]$fx.Children.Add((New-AT3Header "---- EVERYTHING ELSE ----" -Accent "plum"))
    $rFrom = New-AT3ComboRow -Label "Other effects from" -ComboWidth 580
    [void]$fx.Children.Add($rFrom.Row)
    [void]$fx.Children.Add((New-AT3Note ("The rest of the effect record - muzzle, trail and in-flight particles, about thirty " +
        "slots - is not mapped slot by slot. Choosing a weapon here copies ALL of those from it at once, while the " +
        "projectile, sounds and impact above stay as shown. Leave it on (keep the base's) to change nothing.")))

    $fillAssets = {
        param($cmb, $list)
        [void]$cmb.Items.Add([pscustomobject]@{ Display = "(none)"; Key = ""; Label = "(none)"; Regions = @(); Global = $true })
        foreach ($a in @($list)) {
            $where = if ($a.global) { "global" } elseif (@($a.regions).Count) { "in " + (@($a.regions) -join ",") } else { "nowhere" }
            [void]$cmb.Items.Add([pscustomobject]@{
                Display = ("{0,-48} used by {1,2}   {2}" -f $a.label, $a.used_by, $where)
                Key = $a.hash; Label = $a.label; Regions = @($a.regions); Global = [bool]$a.global })
        }
    }
    if ($assets) {
        & $fillAssets $rProj.Combo $assets.projectiles
        & $fillAssets $rSnd.Combo $assets.impact_sounds
        & $fillAssets $rMix.Combo $assets.impact_effects
    }
    # Always the LAST entry. It is a command, never a value - see the handler.
    [void]$rProj.Combo.Items.Add([pscustomobject]@{ Display = "Choose other Geometry..."; Key = "OTHER"; Label = ""; Regions = @(); Global = $true })
    [void]$rFrom.Combo.Items.Add([pscustomobject]@{ Display = "(keep the base's)"; Key = ""; Rec = $null })
    foreach ($x in @($allWeapons | Where-Object { $_.effect } | Sort-Object @{ Expression = { $_.name } })) {
        [void]$rFrom.Combo.Items.Add([pscustomobject]@{
            Display = ("{0}   [{1}{2}]" -f $x.name, $x.type, $(if ($x.projectile) { " - " + $x.projectile } else { "" }))
            Key = $x.hash; Rec = $x })
    }

    # =======================================================================
    # FIRING
    # =======================================================================
    $fr = New-Object System.Windows.Controls.StackPanel
    [void]$fr.Children.Add((New-AT3Note ("How the weapon aims and what its projectile does in flight, settled by bisection and " +
        "observation (WEAPON_DIALS.md). These are NOT independent dials: range, arc angle, arc distance and arc time form one " +
        "firing solution - 'fire at this angle so the shot covers this distance in this time' - and changing one alone can " +
        "leave the engine an inconsistent shot that appears to do nothing. Copy a whole solution from a weapon that already " +
        "flies the way you want, then adjust.")))
    $rCopy = New-AT3ComboRow -Label "Copy firing values from" -ComboWidth 580
    [void]$fr.Children.Add($rCopy.Row)
    foreach ($x in @($allWeapons | Sort-Object @{ Expression = { $_.name } })) {
        if (-not $x.values) { continue }
        [void]$rCopy.Combo.Items.Add([pscustomobject]@{
            Display = ("{0}   [{1}{2}]" -f $x.name, $x.type, $(if ($x.projectile) { " - " + $x.projectile } else { "" }))
            Key = $x.hash; Rec = $x })
    }
    [void]$fr.Children.Add((New-AT3Header "---- FIRING SOLUTION ----" -Accent "plum"))
    & $addNum $fr "m_range" "Range" "m_range  +16, float. The distance at which the AI is WILLING to fire - not how far the shot goes. Clubs 1 to 3; most rifles 100."
    & $addNum $fr "m_arcAngle" "Arc angle (degrees)" "m_arcAngle  +20, float. Launch elevation: 0 fires flat, the outlaw mortar's 35 lobs. 400 wrapped round to 40 in testing."
    & $addNum $fr "m_arcDist" "Arc distance" "m_arcDist  +24, float. The distance the shot is SOLVED for. With mortar physics 90 landed a football field long and 50 on target. Not bounded by range."
    & $addNum $fr "m_arcTime" "Arc time (seconds)" "m_arcTime  +28, float. The flight time the solution assumes. 12 over an arc distance of 50 gave a shell moving at walking pace."
    [void]$fr.Children.Add((New-AT3Header "---- PROJECTILE FLIGHT ----" -Accent "plum"))
    & $addNum $fr "m_speed" "Projectile speed" "m_speed  +46, float. Projectile velocity."
    & $addNum $fr "m_gravity" "Projectile gravity" "m_gravity  +50, float. Near 0 flies level indefinitely (cruise missiles); about 27 on mortar shells; 49.6 on McGee's fast primary."
    & $addNum $fr "m_pitchClamp" "Pitch clamp (degrees)" "m_pitchClamp  +72, float. Vertical aim limit: 80 on every high-elevation weapon, 45 on direct fire."
    & $addNum $fr "m_maxLeadVel" "Max lead velocity" "m_maxLeadVel  +76, float. Caps how far the AI leads a moving target: 100 direct fire, 10 slow lobbed shells."
    & $addNum $fr "homing_228" "Homing angle" "+228, float - no engine name located; identified in play. -1 is off, 90 a slight correction (outlaw mortar), 360 turns on a dime (Packrat, Fatty)."
    [void]$fr.Children.Add((New-AT3Note ("Past vanilla ranges these degrade rather than scale: speed 150 at arc angle 88 gave a " +
        "LOWER, slower shell than the vanilla mortar. Clubs carry the same fields; only range has been observed doing " +
        "anything on one.")))

    # =======================================================================
    # CLIP & RELOAD
    #
    # Located from the AT3 Official preset, whose Weapons block has written
    # clipCapacity / fireRate / reloadTime / accuracyWidth / missTime all along
    # (its Off = descriptor offset + the 20-byte record header). The
    # neighbours are named by the engine's reflection order - the SWSE schema
    # lists each class in REVERSE file order - and are marked untested.
    # =======================================================================
    $cr = New-Object System.Windows.Controls.StackPanel
    [void]$cr.Children.Add((New-AT3Note ("How much the weapon holds, how fast it fires and how long it takes to reload. " +
        "Clip capacity, fire rate, reload time, accuracy width and miss time are the fields the AT3 Official preset has " +
        "always written into weapons. The others sit beside them in the engine's own field order and are untested.")))
    [void]$cr.Children.Add((New-AT3Header "---- CLIP ----" -Accent "plum"))
    & $addNum $cr "m_clipCapacity" "Clip capacity" "m_clipCapacity  +174, int. Shots before a reload. -1 = never reloads (every club); rifles 3; flamethrower 45; machine-gun nest 15; catapults 9999."
    & $addNum $cr "m_clipCapacityMin" "Clip capacity, minimum" "m_clipCapacityMin  +170, int (engine field order - untested). 1 on almost everything; where higher the clip looks random between the two - machine-gun nest 10..15, boat turret 15..25."
    & $addNum $cr "m_totalCapacity" "Total ammo" "m_totalCapacity  +178, int (engine field order - untested). -1 = unlimited on 76 of 78 weapons; one McGee rifle 8000, the rocketship 4."
    [void]$cr.Children.Add((New-AT3Header "---- TIMING ----" -Accent "plum"))
    & $addNum $cr "m_fireRate" "Fire rate" "m_fireRate  tail+0, float. Written by the AT3 Official preset. 0 on most weapons; 10 on arrows and the boat turret; 1000 on one McGee missile."
    $chkTextkeys = New-AT3Check -Text "Fire timed by the animation (textkeys)" -Checked $true `
        -Tip "m_fireFromTextkeys  tail+4, byte (engine field order - untested). On for all but three weapons: the flamethrower, one McGee rifle and the minecart turret."
    [void]$cr.Children.Add($chkTextkeys)
    [void]$cr.Children.Add((New-AT3CheckNote ("Most weapons fire when their animation says so, which may be why fire rate is 0 on " +
        "most of them. How the two interact is untested - if a fire-rate change seems to do nothing, try it with this unticked.")))
    & $addNum $cr "m_reloadTime" "Reload time (seconds)" "m_reloadTime  tail+5, float. Written by the AT3 Official preset. Sniper 2, mortar 3, rifles 1-2, gloktigi 5, clubs 0."
    & $addNum $cr "m_reloadTimeMax" "Reload time, maximum" "m_reloadTimeMax  tail+9, float (engine field order - untested). 0 on most; machine-gun nest 1..3 and boat turret 3..4 suggest a random reload between the two."
    [void]$cr.Children.Add((New-AT3Header "---- AIM ----" -Accent "plum"))
    & $addNum $cr "m_accuracyWidth" "Accuracy width" "m_accuracyWidth  float, after the spawn-pref string. Written by the AT3 Official preset. 0 on the snipers, 0.8 on the machine-gun nest."
    & $addNum $cr "m_missTime" "Miss time" "m_missTime  float, after accuracy width. Written by the AT3 Official preset."
    & $addNum $cr "m_minDistance" "Minimum distance" "m_minDistance  tail+25, float (engine field order - untested). 15 on the mortar, cannon and catapults - lobbed weapons that should not fire point-blank - and 5 on most rifles."

    # =======================================================================
    # DAMAGE
    # =======================================================================
    $dm = New-Object System.Windows.Controls.StackPanel
    [void]$dm.Children.Add((New-AT3Note ("What a hit does to its VICTIM. A weapon's fields govern what happens to the thing it " +
        "hits, never to the character carrying it - the wielder's own recovery lives on the character record.")))
    [void]$dm.Children.Add((New-AT3Header "---- DAMAGE ----" -Accent "plum"))
    & $addNum $dm "m_damage" "Damage" "m_damage  +93, float. Matched on several clubs. Most rifles ship 0.4 here, which has not been tested on a firearm."
    & $addNum $dm "potent_089" "+89  (unnamed - scales damage)" "+89, float. Meaning unknown - see the note below."
    & $addNum $dm "m_stamina" "Stamina damage" "m_stamina  +103, float (likely). Non-zero on exactly one retail weapon, Boilz Booty's gun."
    [void]$dm.Children.Add((New-AT3Note ("+89 is the only weapon field confirmed by a swapped two-way control. On a club with " +
        "damage held at 45, +89 = 10 took nearly half the player's health and +89 = 120 did almost nothing - HIGHER MEANS " +
        "LESS DAMAGE - and the effect followed the value when the two weapons were swapped. What it is remains open. " +
        "10 of 23 clubs set it equal to damage, so treat the two as a pair.")))
    [void]$dm.Children.Add((New-AT3Header "---- IMPACT FORCE ----" -Accent "plum"))
    & $addNum $dm "m_maxKnockSpeed" "Knockback impulse" "m_maxKnockSpeed  +144, float. Looten Duke 20. At 0 a weapon hurts without knocking down - the suicide bomber's 200-damage charge."
    & $addNum $dm "m_bounceParameter" "Bounce" "m_bounceParameter  +255, float. 0.25 normal; Looten Duke and McGee 0.85; the fuzzle-trap deaths 0.9."

    # =======================================================================
    # EXPERIMENTAL
    # =======================================================================
    $ex = New-Object System.Windows.Controls.StackPanel
    [void]$ex.Children.Add((New-AT3Note ("Real, locatable floats on every weapon, each with a test history and no established " +
        "meaning. They are written exactly like every other field - finding out what they do is the point. Change ONE, " +
        "launch, and write down what happened: a single observation is not a result.")))
    [void]$ex.Children.Add((New-AT3Header "---- UNMAPPED ----" -Accent "plum"))
    & $addNum $ex "unk_111" "+111" "+111, float. -1 or 1."
    [void]$ex.Children.Add((New-AT3Note ("+111: a clean binary - -1 on direct-fire guns, 1.0 on lobbed and area weapons " +
        "(catapults, acid spit, a mortar, the fuzzle-trap deaths). No effect on a club, which is exactly what a projectile " +
        "property would look like. The best candidate here for a firearm test.")))
    & $addNum $ex "unk_107" "+107" "+107, float. 5.0 on most weapons; Elboze 1, Castaraider 2, Duke's and Lefty's guns 3."
    [void]$ex.Children.Add((New-AT3Note "+107: no effect on a club at 1.0 against 5.0. Never tested on a firearm."))
    & $addNum $ex "unk_152" "+152" "+152, float. 0 on nearly everything."
    [void]$ex.Children.Add((New-AT3Note ("+152: 12 on Sekto's deathray alone - the weapon that fires a burst of small shots " +
        "before its beam. 1.0 and 1.0052 on two clubs. No effect on a club at 0 against 12.")))
    [void]$ex.Children.Add((New-AT3Header "---- EXPLOSION (named by engine field order) ----" -Accent "plum"))
    [void]$ex.Children.Add((New-AT3Note ("These four sit directly before knockback (+144, confirmed) in the engine's own field " +
        "order, and the values fit: area of effect is non-zero on exactly the exploding weapons - mortar 6, cannon and suicide " +
        "bomber 10, Packrat 5, McGee 7 and 10, catapults 10, wolvark grenadier 5 - and 0 on every rifle and club. Untested in " +
        "game. They, not the projectile mesh, are what would make a weapon explode on impact.")))
    & $addNum $ex "m_areaOfEffect" "Area of effect (blast radius)" "m_areaOfEffect  +135, float (engine field order - untested)."
    & $addNum $ex "m_explosionSpeed" "Explosion speed" "m_explosionSpeed  +127, float (engine field order - untested). 10 on mortar, cannon, bomber and Packrat; 15 on catapults."
    & $addNum $ex "m_explosionDuration" "Explosion duration" "m_explosionDuration  +123, float (engine field order - untested). 0.5 on nearly every weapon."
    & $addNum $ex "m_explosionFriendAffectMultiplier" "Explosion: effect on allies" "m_explosionFriendAffectMultiplier  +131, float (engine field order - untested). 0 everywhere except the wolvark grenadier (1)."
    [void]$ex.Children.Add((New-AT3Header "---- UNMAPPED, CONTINUED ----" -Accent "plum"))
    & $addNum $ex "unk_216" "+216" "+216, float. 1.0 or 1.8."
    [void]$ex.Children.Add((New-AT3Note ("+216: 1.8 on JoMomma's hatchet, the throwing knife, one catapult and McGee's " +
        "missiles; 1.0 elsewhere. No correlation found with speed, gravity, arc or homing.")))

    # =======================================================================
    # RESIDENCY
    # =======================================================================
    $rs = New-Object System.Windows.Controls.StackPanel
    [void]$rs.Children.Add((New-AT3Note ("Where this weapon will exist. A character can only carry a weapon that is resident " +
        "in its own region, so build it into every region you mean to use it in.")))
    [void]$rs.Children.Add((New-AT3Header "---- TARGET REGIONS ----" -Accent "plum"))
    $regionChecks = [ordered]@{}
    $regionWrap = New-Object System.Windows.Controls.WrapPanel
    $regionWrap.Margin = New-Object System.Windows.Thickness 0,0,0,8
    if ($model) {
        foreach ($r in $model.regions) {
            $c = New-AT3Check -Text $r.label -Checked $false -Tip ("region key: " + $r.key)
            $c.Width = 210
            $c.Margin = New-Object System.Windows.Thickness 0,0,0,4
            $c.Tag = $r.key
            $regionChecks[$r.key] = $c
            [void]$regionWrap.Children.Add($c)
        }
    }
    [void]$rs.Children.Add($regionWrap)
    [void]$rs.Children.Add((New-AT3Header "---- PORT MANIFEST ----" -Accent "plum"))
    $manifest = New-Object System.Windows.Controls.TextBlock
    $manifest.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $manifest.FontSize = 11
    $manifest.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $manifest.Foreground = $conv.ConvertFromString("#C8BB9B")
    [void]$rs.Children.Add($manifest)
    [void]$rs.Children.Add((New-AT3Header "---- BUILD WEAPON ----" -Accent "plum"))
    $btnBuild = New-Object System.Windows.Controls.Button
    $btnBuild.Content = "Build weapon"
    $btnBuild.Height = 32
    $btnBuild.MinWidth = 240
    $btnBuild.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $btnBuild.Margin = New-Object System.Windows.Thickness 0,2,0,6
    $btnBuild.IsEnabled = $false
    [void]$rs.Children.Add($btnBuild)
    $buildWhy = New-Object System.Windows.Controls.TextBlock
    $buildWhy.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $buildWhy.FontSize = 11
    $buildWhy.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $buildWhy.Foreground = $conv.ConvertFromString("#8A7A5C")
    [void]$rs.Children.Add($buildWhy)
    [void]$rs.Children.Add((New-AT3Note ("One button, one weapon. Build ports what the weapon needs into each target region - " +
        "its effect record, projectile mesh and textures, particle prefs and every per-surface impact record - adds the new " +
        "weapon under a hash derived from the name you give (plus its own effect record if anything on Projectile & Effects " +
        "changed), verifies the blockmap the game actually reads, and registers the name. It does not arm any character: " +
        "choose the weapon in one of the Character Creator's weapon slots.")))
    [void]$rs.Children.Add((New-AT3Note ("Each build backs up the target region's bundle and blockmap first and restores both " +
        "on any failure.")))

    # =======================================================================
    # FIELD WIRING - the Character Creator's pattern, see its header.
    # =======================================================================
    $fieldCtl = [ordered]@{}
    foreach ($k in $numRows.Keys) { $fieldCtl[$k] = New-AT3FieldEntry -Kind "text" -Ctl $numRows[$k] -Fields @($k) }
    foreach ($spec in @(@("fx_projectile", $rProj), @("fx_impactSounds", $rSnd), @("fx_impactEffects", $rMix),
                        @("m_weaponType", $rClass))) {
        $fieldCtl[$spec[0]] = New-AT3FieldEntry -Kind "combo" -Ctl $spec[1] -Fields @($spec[0])
    }
    $fieldCtl["m_fireFromTextkeys"] = New-AT3FieldEntry -Kind "check" -Ctl $chkTextkeys -Fields @("m_fireFromTextkeys")
    $firingFields = @("m_range", "m_arcAngle", "m_arcDist", "m_arcTime", "m_speed", "m_gravity",
                      "m_pitchClamp", "m_maxLeadVel", "homing_228")

    $loadBase = {
        param($b)
        $has = [bool]($b -and $b.Rec -and $b.Rec.values)
        foreach ($key in @($fieldCtl.Keys)) {
            $e = $fieldCtl[$key]
            $f0 = @($e.Fields)[0]
            if (-not $has) {
                Set-AT3FieldValue -Entry $e -Value $null
                Set-AT3FieldEnabled -Entry $e -On $false -Why "choose a base weapon first - Base > Weapon type, then Clone from"
                continue
            }
            $vp = $b.Rec.values.PSObject.Properties[$f0]
            $wp = if ($b.Rec.unwritable) { $b.Rec.unwritable.PSObject.Properties[$f0] } else { $null }
            Set-AT3FieldValue -Entry $e -Value $(if ($vp) { $vp.Value } else { $null })
            Set-AT3FieldEnabled -Entry $e -On (-not $wp) -Why $(if ($wp) { [string]$wp.Value } else { "" })
        }
        $rFrom.Combo.SelectedIndex = $(if ($has) { 0 } else { -1 })
        $rFrom.Row.IsEnabled = $has
        $rCopy.Combo.SelectedIndex = -1
        $rCopy.Row.IsEnabled = $has
        if ($has) {
            $status.Text = ("Loaded {0} ({1}) - every field shows its real values; the ones you change are written when you build." -f $b.Rec.name, $b.Rec.hash)
        }
    }.GetNewClosure()

    $collectEdits = {
        param($b)
        $edits = [ordered]@{}
        if (-not ($b -and $b.Rec -and $b.Rec.values)) { return $edits }
        foreach ($key in @($fieldCtl.Keys)) {
            $e = $fieldCtl[$key]
            $f0 = @($e.Fields)[0]
            if ($b.Rec.unwritable -and $b.Rec.unwritable.PSObject.Properties[$f0]) { continue }
            if ($e.Kind -eq "combo" -and $null -eq $e.Ctl.Combo.SelectedItem) { continue }
            $vp = $b.Rec.values.PSObject.Properties[$f0]
            $baseVal = if ($vp) { $vp.Value } else { $null }
            $cur = Get-AT3FieldValue -Entry $e
            if (-not (Test-AT3FieldSame -A $cur -B $baseVal)) {
                foreach ($f in @($e.Fields)) { $edits[$f] = $cur }
            }
        }
        return $edits
    }.GetNewClosure()

    # Recomputed wherever needed, never stashed in $script: variables - see the
    # Character Creator's build handler for the bug that caused.
    $buildInputs = {
        $b = $rBase.Combo.SelectedItem
        $want = @()
        foreach ($k in $regionChecks.Keys) { if ($regionChecks[$k].IsChecked) { $want += $k } }
        $src = $null
        if ($b) {
            foreach ($r in @($b.Rec.regions)) { if ($r -match '^[0-9]' -and $want -notcontains $r) { $src = $r; break } }
            if (-not $src) { foreach ($r in @($b.Rec.regions)) { if ($r -match '^[0-9]') { $src = $r; break } } }
        }
        return @{ Base = $b; Source = $src; Targets = $want }
    }.GetNewClosure()

    $updateManifest = {
        $b = $rBase.Combo.SelectedItem
        $want = @()
        foreach ($k in $regionChecks.Keys) { if ($regionChecks[$k].IsChecked) { $want += $k } }
        if (-not $b) { $manifest.Text = "No base weapon - choose one on the Base tab."; return }
        if (-not $want.Count) { $manifest.Text = $(if ($editing) { "No region ticked to save in." } else { "No target region selected." }); return }
        $rows = @()
        $from = $rFrom.Combo.SelectedItem
        if ($from -and $from.Key -and $from.Rec) {
            $rows += [pscustomobject]@{ what = "effects from"; name = $from.Rec.name; regions = @($from.Rec.effect_regions); glob = $false }
        } elseif ($b.Rec.effect) {
            $rows += [pscustomobject]@{ what = "effect record"; name = $b.Rec.effect; regions = @($b.Rec.effect_regions); glob = $false }
        }
        foreach ($pair in @(@("projectile", $rProj), @("impact effects", $rMix))) {
            $it = $pair[1].Combo.SelectedItem
            if ($it -and $it.Key) {
                $rows += [pscustomobject]@{ what = $pair[0]; name = $it.Label; regions = @($it.Regions); glob = [bool]$it.Global }
            }
        }
        $lines = @($(if ($editing) { "editing " + $b.Rec.name + " in place" } else { "new weapon cloned from " + $b.Rec.name }))
        $need = 0
        foreach ($tgt in $want) {
            $lines += ("region " + $tgt + ":")
            foreach ($r in $rows) {
                $have = $r.glob -or (@($r.regions) -contains $tgt)
                if (-not $have) { $need++ }
                $nm = [string]$r.name
                if ($nm.Length -gt 44) { $nm = $nm.Substring(0, 44) }
                $lines += ("   {0}  {1,-15} {2,-44} {3}" -f $(if ($have) { "resident" } else { "PORT    " }), $r.what, $nm,
                           $(if ($r.glob) { "(global)" } elseif (@($r.regions).Count) { "(in " + (@($r.regions) -join ",") + ")" } else { "(nowhere)" }))
            }
        }
        $lines += ""
        if ($need) {
            $lines += ("{0} item(s) will be ported, each with its textures, particle prefs and per-surface impact records. Build prints the exact record list." -f $need)
        } else {
            $lines += "Everything this weapon uses is already resident in the chosen region(s). Build prints the exact record list."
        }
        $manifest.Text = ($lines -join [Environment]::NewLine)
    }.GetNewClosure()

    $validate = {
        $in = & $buildInputs
        $miss = @()
        if ($editing) {
            if (-not $in.Base) { $miss += "the weapon being edited is not loaded" }
            if (-not @($in.Targets).Count) { $miss += "Residency: at least one region to save the changes in" }
            if ($miss.Count) {
                $btnBuild.IsEnabled = $false
                $buildWhy.Text = "Cannot save yet - still needed:" + [Environment]::NewLine +
                                 (($miss | ForEach-Object { "   - " + $_ }) -join [Environment]::NewLine)
            } else {
                $btnBuild.IsEnabled = $true
                $buildWhy.Text = "Ready: save the changed fields into " + $in.Base.Rec.name + " (" + $in.Base.Rec.hash + ") in region(s) " +
                                 (@($in.Targets) -join ", ") + ". Every character carrying it there changes too."
            }
            return
        }
        if (-not $in.Base) { $miss += "Base: a weapon to clone from" }
        if (-not @($in.Targets).Count) { $miss += "Residency: at least one target region" }
        if ($in.Base -and -not $in.Source) { $miss += "this weapon lives only in a workspace - no numbered source region to copy from" }
        if ($miss.Count) {
            $btnBuild.IsEnabled = $false
            $buildWhy.Text = "Cannot build yet - still needed:" + [Environment]::NewLine +
                             (($miss | ForEach-Object { "   - " + $_ }) -join [Environment]::NewLine)
        } else {
            $btnBuild.IsEnabled = $true
            $buildWhy.Text = "Ready: build a new weapon cloned from " + $in.Base.Rec.name + " (source region " + $in.Source +
                             ") into " + (@($in.Targets) -join ", ") + "."
        }
    }.GetNewClosure()

    [void]$rType.Combo.Add_SelectionChanged({
        $t = $rType.Combo.SelectedItem
        $rBase.Combo.Items.Clear()
        if (-not $t) { return }
        foreach ($x in @($weapons | Where-Object { [string]$_.type -eq [string]$t.Key } |
                Sort-Object @{ Expression = { if ($_.origin -eq "stock") { 0 } else { 1 } } }, @{ Expression = { $_.name } })) {
            [void]$rBase.Combo.Items.Add([pscustomobject]@{
                Display = ("{0}  {1}{2}  (in {3}){4}" -f $x.hash, $x.name,
                           $(if ($x.projectile) { "  fires " + $x.projectile } else { "" }),
                           $(if (@($x.regions).Count) { @($x.regions) -join "," } else { "nowhere" }),
                           $(if ($x.origin -ne "stock") { "  [" + $x.origin + "]" } else { "" }))
                Rec = $x })
        }
        if ($rBase.Combo.Items.Count -ge 1) { $rBase.Combo.SelectedIndex = 0 }
    }.GetNewClosure())

    [void]$rBase.Combo.Add_SelectionChanged({
        $b = $rBase.Combo.SelectedItem
        # The type list is per base: its own type, plus Firearm for a Turret.
        # Built BEFORE $loadBase so the base's value has an item to select.
        $rClass.Combo.Items.Clear()
        if ($b) {
            $x = $b.Rec
            [void]$rClass.Combo.Items.Add([pscustomobject]@{ Display = [string]$x.type; Key = [string]$x.type })
            if ([string]$x.type -eq "Turret") {
                [void]$rClass.Combo.Items.Add([pscustomobject]@{ Display = "Firearm  (converted - a character can carry it)"; Key = "Firearm" })
            }
            $lines = @(("{0}   type {1}   {2}" -f $x.hash, $x.type, $x.origin))
            $lines += $(if ($x.projectile) { "fires    " + $x.projectile } else { "fires    nothing (no projectile mesh)" })
            $cb = @($x.carried_by)
            $cc = @($x.carried_by_custom)
            if ($cb.Count) { $lines += ("carried  by " + ($cb -join ", ")) } else { $lines += "carried  by no shipped character" }
            if ($cc.Count) { $lines += ("         and by your " + ($cc -join ", ")) }
            $lines += ("lives in " + $(if (@($x.regions).Count) { @($x.regions) -join ", " } else { "no numbered region" }))
            $baseInfo.Text = ($lines -join [Environment]::NewLine)
        } else {
            $baseInfo.Text = ""
        }
        & $loadBase $b
        & $updateManifest
        & $validate
    }.GetNewClosure())

    [void]$rCopy.Combo.Add_SelectionChanged({
        $c = $rCopy.Combo.SelectedItem
        if (-not $c) { return }
        $n = 0
        foreach ($f in $firingFields) {
            $e = $fieldCtl[$f]
            if (-not $e.Ctl.Row.IsEnabled) { continue }
            $vp = $c.Rec.values.PSObject.Properties[$f]
            if ($vp -and $null -ne $vp.Value) {
                # Text only - Box.Tag keeps the BASE value, so each field's reset
                # button still goes back to the weapon being cloned.
                $e.Ctl.Box.Text = ([double]$vp.Value).ToString("G7", [System.Globalization.CultureInfo]::InvariantCulture)
                $n++
            }
        }
        $status.Text = ("Copied {0} firing value(s) from {1}. Each field's reset button still returns the base's own value." -f $n, $c.Rec.name)
    }.GetNewClosure())

    # "Choose other Geometry..." opens the full geometry list. A pick becomes a
    # real entry just above the command, so it can be re-selected later; a
    # cancel puts the previous selection back. The command itself never stays
    # selected, so it can never reach the edits file.
    $projState = @{ Last = $null; Busy = $false }
    [void]$rProj.Combo.Add_SelectionChanged({
        if ($projState.Busy) { return }
        $sel = $rProj.Combo.SelectedItem
        if (-not $sel -or [string]$sel.Key -ne "OTHER") { $projState.Last = $sel; return }
        $projState.Busy = $true
        try {
            $g = Show-AT3GeometryPicker -Purpose "projectile"
            if ($g) {
                $item = $null
                foreach ($it in $rProj.Combo.Items) { if ([string]$it.Key -eq [string]$g.Hash) { $item = $it; break } }
                if (-not $item) {
                    $gw = if ($g.Global) { "global" } elseif (@($g.Regions).Count) { "in " + (@($g.Regions) -join ",") } else { "nowhere" }
                    $item = [pscustomobject]@{
                        Display = ("{0,-48} other geometry   {1}" -f $g.Name, $gw)
                        Key = [string]$g.Hash; Label = [string]$g.Name; Regions = @($g.Regions); Global = [bool]$g.Global }
                    $rProj.Combo.Items.Insert($rProj.Combo.Items.Count - 1, $item)
                }
                $rProj.Combo.SelectedItem = $item
                $projState.Last = $item
                $status.Text = ("Projectile set to " + $g.Name + " - untested as a projectile; it is ported with its textures when you build.")
            } else {
                $rProj.Combo.SelectedItem = $projState.Last
            }
        } finally { $projState.Busy = $false }
        & $updateManifest
    }.GetNewClosure())
    foreach ($cmbRow in @($rProj, $rMix, $rFrom)) {
        [void]$cmbRow.Combo.Add_SelectionChanged({ & $updateManifest }.GetNewClosure())
    }
    foreach ($k in $regionChecks.Keys) {
        [void]$regionChecks[$k].Add_Checked({   & $updateManifest; & $validate }.GetNewClosure())
        [void]$regionChecks[$k].Add_Unchecked({ & $updateManifest; & $validate }.GetNewClosure())
    }

    [void]$btnBuild.Add_Click({
        $in = & $buildInputs
        $b = $in.Base; $src = $in.Source; $targets = @($in.Targets)
        if ($editing) {
            if (-not $b -or -not $targets.Count) { return }
            $edits = & $collectEdits $b
            $from = $rFrom.Combo.SelectedItem
            if ($from -and $from.Key) { $edits["effect_from"] = [string]$from.Key }
            if (-not $edits.Count) {
                Show-AT3Notice -Title "Save Weapon" -Text ("Nothing to save - every field still matches " + $b.Rec.name + ".")
                return
            }
            $editLines = @($edits.Keys | ForEach-Object {
                $_ + " = " + $(if ($null -eq $edits[$_] -or [string]$edits[$_] -eq "") { "(none)" } else { [string]$edits[$_] }) })
            $carriers = @(@($b.Rec.carried_by) + @($b.Rec.carried_by_custom) | Where-Object { $_ })
            $msg = ("Save {0} change(s) to '{1}' ({2}) in region(s) {3}?" -f $edits.Count, $b.Rec.name, $b.Rec.hash, ($targets -join ", ")) +
                [Environment]::NewLine + [Environment]::NewLine +
                "This edits the EXISTING weapon, so every character carrying it in those regions changes too" +
                $(if ($carriers.Count) { " (" + ($carriers -join ", ") + ")" } else { "" }) + ". A projectile or impact change " +
                "edits its effect record in place where nothing else uses it; where other weapons share it, this weapon gets " +
                "its own copy. Each region's bundle and blockmap are backed up first and restored if anything fails." +
                [Environment]::NewLine + [Environment]::NewLine + (@($editLines | Select-Object -First 14) -join [Environment]::NewLine) +
                $(if ($editLines.Count -gt 14) { [Environment]::NewLine + ("...and {0} more" -f ($editLines.Count - 14)) } else { "" })
            if (-not (Confirm-AT3Choice -Title "Save Weapon" -Text $msg)) { $buildWhy.Text = "Save cancelled - nothing was written."; return }
            $argv = @((Join-Path $ModToolsDir "edit_weapon.py"), $b.Rec.hash)
            foreach ($t in $targets) { $argv += @("--to", $t) }
            $editsPath = Join-Path ([System.IO.Path]::GetTempPath()) ("at3_wedits_" + [guid]::NewGuid().ToString("N") + ".json")
            [System.IO.File]::WriteAllText($editsPath, ($edits | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding $false))
            $argv += @("--edits", $editsPath)
            $r = Invoke-AT3Python -Arguments $argv -Activity ("Saving " + $b.Rec.name)
            Remove-Item -LiteralPath $editsPath -ErrorAction SilentlyContinue
            $txt = [string]$r.Output
            Write-AT3Log ("weapon edit '" + $b.Rec.name + "' " + $b.Rec.hash + " edits [" + ($editLines -join "; ") + "] ok=" + $r.Ok + " :: " + ($txt -replace "`r?`n", " | "))
            $manifest.Text = $txt
            $done = @([regex]::Matches($txt, "(EDITED|UNCHANGED) [0-9A-F]{8} in region (\S+)") | ForEach-Object { $_.Groups[2].Value })
            $problem = @($txt -split "`r?`n" | Where-Object { $_ -match "REFUSED|FAILED" })
            if ($done.Count) {
                [void](Update-AT3Index)
                [void](Update-AT3Catalogue)
                [void](Update-AT3CharacterModel)
                # Compare against the SAVED values from now on, so a second save
                # only sends what changed after this one.
                $fresh = Get-AT3CharacterModel
                if ($fresh -and $fresh.PSObject.Properties["weapons"]) {
                    foreach ($x in @($fresh.weapons)) { if ([string]$x.hash -eq [string]$b.Rec.hash) { $b.Rec = $x } }
                    & $loadBase $b
                    & $updateManifest
                }
            }
            if ($done.Count -eq $targets.Count -and -not $problem.Count) {
                $buildWhy.Text = "Saved " + $b.Rec.name + " in region(s) " + ($done -join ", ") + "."
                Show-AT3Notice -Title "Save Weapon" -Text ("'" + $b.Rec.name + "' was saved in region(s): " + ($done -join ", ") +
                    [Environment]::NewLine + [Environment]::NewLine + "Every character carrying it there uses the new values. To undo one region: " +
                    "python ModTools\edit_weapon.py --revert " + $b.Rec.hash + " --to <region>")
            } else {
                $buildWhy.Text = "Save did not complete in every region - see the manifest box for the reason."
                Show-AT3Notice -Title "Save Weapon" -Icon "Warning" -Text (((@($done | ForEach-Object { "saved: region " + $_ }) + $problem) -join [Environment]::NewLine) +
                    [Environment]::NewLine + [Environment]::NewLine + "Any region that failed was restored from its backup.")
            }
            return
        }
        if (-not $b -or -not $src -or -not $targets.Count) {
            [void][System.Windows.MessageBox]::Show(
                ("Nothing to build." + [Environment]::NewLine +
                 "base: " + $(if ($b) { $b.Rec.name } else { "(none)" }) + [Environment]::NewLine +
                 "source region: " + $(if ($src) { $src } else { "(none)" }) + [Environment]::NewLine +
                 "targets: " + $(if ($targets.Count) { $targets -join ", " } else { "(none)" })),
                "Build Weapon", "OK", "Warning")
            return
        }
        $edits = & $collectEdits $b
        $from = $rFrom.Combo.SelectedItem
        if ($from -and $from.Key) { $edits["effect_from"] = [string]$from.Key }
        $editLines = @($edits.Keys | ForEach-Object {
            $_ + " = " + $(if ($null -eq $edits[$_] -or [string]$edits[$_] -eq "") { "(none)" } else { [string]$edits[$_] }) })
        $name = Show-AT3BuildDialog -Kind "weapon" -Regions $targets -BaseName $b.Rec.name -Edits $editLines
        if (-not $name) { $buildWhy.Text = "Build cancelled - nothing was written."; return }
        $argv = @((Join-Path $ModToolsDir "build_weapon.py"), $b.Rec.hash, "--from", $src,
                  "--name", $name, "--donor-name", ([string]$b.Rec.name -replace '"', ''))
        foreach ($t in $targets) { $argv += @("--to", $t) }
        $editsPath = Join-Path ([System.IO.Path]::GetTempPath()) ("at3_wedits_" + [guid]::NewGuid().ToString("N") + ".json")
        $editsJson = if ($edits.Count) { $edits | ConvertTo-Json -Depth 3 } else { "{}" }
        [System.IO.File]::WriteAllText($editsPath, $editsJson, (New-Object System.Text.UTF8Encoding $false))
        $argv += @("--edits", $editsPath)
        $r = Invoke-AT3Python -Arguments $argv -Activity ("Building " + $name)
        Remove-Item -LiteralPath $editsPath -ErrorAction SilentlyContinue
        $txt = [string]$r.Output
        Write-AT3Log ("weapon build '" + $name + "' from " + $b.Rec.hash + " edits [" + ($editLines -join "; ") + "] ok=" + $r.Ok + " :: " + ($txt -replace "`r?`n", " | "))
        $manifest.Text = $txt
        $built = @([regex]::Matches($txt, "BUILT ([0-9A-F]{8}) into region (\S+)") | ForEach-Object { $_.Groups[2].Value + " (" + $_.Groups[1].Value + ")" })
        if ($built.Count) {
            [void](Update-AT3Index)
            [void](Update-AT3Catalogue)
            [void](Update-AT3CharacterModel)
        }
        $problem = @($txt -split "`r?`n" | Where-Object { $_ -match "REFUSED|FAILED" })
        if ($built.Count -and -not $problem.Count) {
            $buildWhy.Text = "Built '" + $name + "' into " + ($built -join ", ") + "."
            [void][System.Windows.MessageBox]::Show(
                ("'" + $name + "' was built into region(s): " + ($built -join ", ") + [Environment]::NewLine + [Environment]::NewLine +
                 "It is now offered in the Character Creator's weapon slots (Anatomy tab). To see it in game, build a character " +
                 "carrying it and place that character with Map Editor > Spawns Editor."),
                "Build Weapon", "OK", "Information")
        } else {
            $buildWhy.Text = "Build did not complete - see the manifest box above for the reason."
            [void][System.Windows.MessageBox]::Show(
                ((@($built | ForEach-Object { "built: " + $_ }) + $problem) -join [Environment]::NewLine) +
                 [Environment]::NewLine + [Environment]::NewLine + "Any region that failed was restored from its backup.",
                "Build Weapon", "OK", "Warning")
        }
    }.GetNewClosure())

    [void]$bClear.Add_Click({
        if ($editing) {
            & $loadBase $rBase.Combo.SelectedItem
            & $updateManifest
            & $validate
            $status.Text = "Reset - every field is back to the weapon's saved values."
            return
        }
        $rType.Combo.SelectedIndex = -1
        $rBase.Combo.Items.Clear()
        foreach ($k in $regionChecks.Keys) { $regionChecks[$k].IsChecked = $false }
        $status.Text = "Cleared. Choose a weapon type, then the weapon to clone - every field loads that weapon's real values."
    }.GetNewClosure())

    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Base" -Content $bs))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Projectile & Effects" -Content $fx))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Firing" -Content $fr))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Clip & Reload" -Content $cr))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Damage" -Content $dm))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Residency" -Content $rs))
    [void]$tabs.Items.Add((New-AT3CreatorTab -Header "Experimental" -Content $ex))
    [void]$root.Children.Add($tabs)

    & $loadBase $null
    & $updateManifest
    & $validate
    if (-not $status.Text) {
        $status.Text = ("{0} weapon(s) - {1}. Choose a base: every field loads that weapon's real values, and Build writes the ones you change." `
            -f $weapons.Count, $script:CharModelNote)
    }

    if ($editing) {
        # Open ON the weapon: type and record picked exactly as a user would
        # pick them, then locked - an edit changes fields, not which weapon it is.
        foreach ($it in $rType.Combo.Items) { if ([string]$it.Key -eq [string]$EditTarget.Rec.type) { $rType.Combo.SelectedItem = $it } }
        foreach ($it in $rBase.Combo.Items) { if ([string]$it.Rec.hash -eq [string]$EditTarget.Hash) { $rBase.Combo.SelectedItem = $it } }
        $lockTip = "Editing an existing weapon - its type and record are fixed. Use Create New to make a different one."
        foreach ($lr in @($rType, $rBase)) {
            $lr.Combo.IsEnabled = $false
            [System.Windows.Controls.ToolTipService]::SetShowOnDisabled($lr.Combo, $true)
            $lr.Combo.ToolTip = $lockTip
        }
        # Only numbered regions can be edited in place, and only where the
        # weapon already lives - anything else is disabled with the reason.
        $held = @($EditTarget.Rec.regions)
        foreach ($k in @($regionChecks.Keys)) {
            if ($k -match '^[0-9]' -and $held -contains $k) {
                $regionChecks[$k].IsChecked = $true
            } else {
                $regionChecks[$k].IsEnabled = $false
                [System.Windows.Controls.ToolTipService]::SetShowOnDisabled($regionChecks[$k], $true)
                $regionChecks[$k].ToolTip = $(if ($k -match '^[0-9]') { "This weapon does not exist in " + $k + "." } else { $k + " is not a numbered region - only those can be edited in place." })
            }
        }
        $btnBuild.Content = "Save changes to weapon"
        $editNote = ("EDITING " + [string]$EditTarget.Name + " (" + [string]$EditTarget.Hash + "). Save writes the fields you change " +
            "back into this weapon in each ticked region - it keeps its hash, so every character carrying it there changes too. " +
            "A newly chosen projectile or impact set is ported into the region first. Regions this weapon is not in cannot be ticked.")
        [void]$bs.Children.Insert(0, (New-AT3Note $editNote))
        [void]$rs.Children.Insert(0, (New-AT3Note $editNote))
        $status.Text = ("Editing " + [string]$EditTarget.Name + " (" + [string]$EditTarget.Hash + ") - every field shows its current values; the ones you change are saved in place.")
        & $updateManifest
        & $validate
    }

    $w.Content = $root
    [void]$w.ShowDialog()
}


# ===========================================================================
# PROP EDITOR  (Map Editor - blue)
#
# Left  : region picker, then the placements for that region.
# Right : the library of objects this region can actually place.
#
# WHY THE LIBRARY IS WHAT IT IS
#
# A placement is made by CLONING a record already in the region and rewriting
# its transform, so the library is exactly "every distinct object this region
# already contains that carries a standard transform". Region_01 has 385
# distinct object keys but only 288 have a clonable donor - the rest are a
# different record shape with no transform and would silently skip on apply.
#
# Retail data names almost none of them: geometry is referenced by hash and
# only 87 .geo path strings survive anywhere in the install, none of which are
# region_01 props. PropNames.csv maps key -> friendly name and is meant to be
# filled in over time; anything unnamed is listed by its key.
#
# The Zones column is INFORMATION, not a restriction. It reports the zones that
# natively load the object's geometry; reach can be extended by injecting the
# object into other zone bundles, so placements outside it are allowed and
# merely flagged.
# ===========================================================================

$script:PropRegion = $null
$script:PropTable  = $null

$RegionNamesPath = Join-Path $AT3Dir "RegionNames.csv"

# id -> common name. Editable in RegionNames.csv; an id with no entry falls
# back to "Region <id>" so a region can never vanish from the picker.
function Get-AT3RegionNames {
    $out = @{}
    if (Test-Path $RegionNamesPath) {
        foreach ($r in @(Import-Csv -LiteralPath $RegionNamesPath)) {
            $id = [string]$r.Id
            if ($id) { $out[$id] = [string]$r.Name }
        }
    }
    return $out
}

function Get-AT3Regions {
    $out = @()
    $names = Get-AT3RegionNames
    $b = Join-Path $GameRoot "data\bundles"
    if (-not (Test-Path $b)) { return $out }
    foreach ($d in @(Get-ChildItem -LiteralPath $b -Directory -ErrorAction SilentlyContinue | Sort-Object Name)) {
        $id = $null
        if ($d.Name -match '^region_(.+)$') { $id = $Matches[1] }
        elseif ($d.Name -eq "utility") { $id = "utility" }   # the utility room
        if (-not $id) { continue }
        $nm = $names[$id]
        if (-not $nm) { $nm = "Region $id" }
        $out += [pscustomobject]@{ Id = $id; Display = $nm }
    }
    return $out
}

function Get-AT3PropLibrary {
    param($Region)
    $p = Join-Path $RegionDataDir "proplib_$Region.csv"
    $rows = @()
    if (-not (Test-Path $p)) { return $rows }
    # Bundles AT3 has promoted to `normal:` are resident for the whole level, so
    # anything inside one reaches every zone regardless of its native zonedep.
    $promoted = @{}
    $lp = Join-Path $RegionDataDir "promoted_$Region.csv"
    if (Test-Path $lp) {
        foreach ($r in @(Import-Csv -LiteralPath $lp)) { $promoted[[string]$r.Bundle] = $true }
    }
    foreach ($r in @(Import-Csv -LiteralPath $p)) {
        $name = [string]$r.Name
        if (-not $name) { $name = "Object " + [string]$r.Key }
        $zones = [string]$r.Zones
        # After consolidation every object reaches every zone, so "reach" no
        # longer tells the lighting variants of one asset apart. BakedZones is
        # where the variant's lighting was baked, which is the thing worth
        # choosing between: pick the variant baked for a similarly lit area.
        $baked = [string]$r.BakedZones
        $bakedText = if ($baked -eq "*") { "all" }
                     elseif (-not $baked -or $baked -eq "?") { "unknown" }
                     else { ($baked -replace ";", ", ") }
        $isPromoted = $false
        foreach ($b in ([string]$r.Bundle).Split(";")) {
            if ($b -and $promoted.ContainsKey($b.Trim())) { $isPromoted = $true }
        }
        $reach = if ($zones -eq "*") { "every zone" }
                 elseif ($zones -eq "?" -or -not $zones) { "unknown" }
                 else { "zones " + ($zones -replace ";", ", ") }
        if ($isPromoted) {
            $native = @(([string]$zones).Split(";") | Where-Object { $_ }).Count
            $reach = "every zone  <+" + (79 - $native) + ">"
        }
        $rows += [pscustomobject]@{
            Key = [string]$r.Key
            Name = $name
            Asset = [string]$r.Asset
            Count = [int]$r.Count
            Reach = $reach
            Baked = $bakedText
            Search = ($name + " " + [string]$r.Asset + " " + [string]$r.Key).ToLower()
        }
    }
    return $rows
}

function Save-AT3PropName {
    param([string]$Key, [string]$Name)
    # Names live in PropNames.csv so a user label survives regenerating the
    # library - prop_library.py reads this file and lets it win over the name
    # derived from the asset filename.
    $p = Join-Path $AT3Dir "PropNames.csv"
    $rows = @()
    if (Test-Path $p) { $rows = @(Import-Csv -LiteralPath $p) }
    $hit = $false
    foreach ($r in $rows) {
        if (([string]$r.Key).ToUpper() -eq $Key.ToUpper()) { $r.Name = $Name; $hit = $true }
    }
    if (-not $hit) { $rows += [pscustomobject]@{ Key = $Key.ToUpper(); Name = $Name } }
    $rows | Select-Object Key, Name | Export-Csv -LiteralPath $p -NoTypeInformation -Encoding utf8
}

function Read-AT3PropRows {
    param($Region)
    $t = New-Object System.Data.DataTable
    # Zone and Tint must exist as columns or Save-AT3PropRows throws reading
    # them. Zone is not shown in the grid - it is resolved by place_props and
    # only carried through so an edit cannot discard it.
    foreach ($c in @("Prop","Key","Position","Yaw","Pitch","Roll","Scale","Tint","Zone")) { [void]$t.Columns.Add($c, [string]) }
    $csv = Get-AT3PropCsv $Region
    $names = @{}
    foreach ($l in (Get-AT3PropLibrary -Region $Region)) { $names[$l.Key] = $l.Name }
    if (Test-Path $csv) {
        foreach ($r in @(Import-Csv -LiteralPath $csv)) {
            $row = $t.NewRow()
            $key = [string]$r.Prop
            $row["Key"] = $key
            $row["Prop"] = $(if ($names.ContainsKey($key)) { $names[$key] } else { $key })
            $row["Position"] = ("{0}  {1}  {2}" -f $r.X, $r.Y, $r.Z)
            $row["Yaw"] = [string]$r.Yaw
            $row["Pitch"] = [string]$r.Pitch
            $row["Roll"] = [string]$r.Roll
            $row["Scale"] = [string]$r.Scale
            $row["Tint"] = [string]$r.Tint
            $row["Zone"] = [string]$r.Zone
            $t.Rows.Add($row)
        }
    }
    $t.AcceptChanges()
    return ,$t
}

function Save-AT3PropRows {
    param($Region, $Table)
    if (-not (Test-Path $PropDir)) { [void](New-Item -ItemType Directory -Force -Path $PropDir) }
    $out = @()
    foreach ($r in $Table.Rows) {
        if ($r.RowState -eq [System.Data.DataRowState]::Deleted) { continue }
        $key = [string]$r["Key"]
        if (-not $key) { continue }
        # One Position cell holding "X Y Z" so a line can be pasted straight
        # out of positions.txt; split on any run of whitespace or commas.
        $parts = @(([string]$r["Position"]).Trim() -split '[\s,]+' | Where-Object { $_ -ne "" })
        if ($parts.Count -lt 3) { continue }
        $out += [pscustomobject]@{
            Prop = $key
            X = $parts[0]; Y = $parts[1]; Z = $parts[2]
            Yaw = $(if ([string]$r["Yaw"]) { [string]$r["Yaw"] } else { "0" })
            Pitch = $(if ([string]$r["Pitch"]) { [string]$r["Pitch"] } else { "0" })
            Roll = $(if ([string]$r["Roll"]) { [string]$r["Roll"] } else { "0" })
            # ZONE MUST SURVIVE THE ROUND TRIP.
            #
            # This column was not written at all, so every save through the
            # editor silently discarded it. Zone is the field that decides
            # whether an object is CULLED - a record whose zone does not match
            # its position never renders and leaves no collision either, which
            # is indistinguishable from the editor simply not working. Without
            # it place_props falls back to polling the twelve nearest records,
            # which returns the wrong answer wherever those neighbours are not
            # ordinary world geometry.
            # Uniform scale at +73. Blank means "inherit the donor's", which is
            # how a 4.372x Wolvark gun stays 4.372x when cloned. Per-axis scale
            # does not exist in this format - the 3x3 at +25 is a pure rotation
            # in all 22,962 of the game's placed records.
            Scale = $(if ([string]$r["Scale"]) { [string]$r["Scale"] } else { "" })
            Zone = $(if ([string]$r["Zone"]) { [string]$r["Zone"] } else { "" })
        }
    }
    $csv = Get-AT3PropCsv $Region
    # Never let a save quietly destroy placements. If the table is empty but the
    # file is not, something failed to load rather than the user deleting every
    # row - keep a copy either way. This exact case wiped a region's placements
    # once, when the editor opened before $PropDir existed and saved 0 rows.
    if ((Test-Path $csv) -and $out.Count -eq 0) {
        $existing = @(Import-Csv -LiteralPath $csv -ErrorAction SilentlyContinue).Count
        if ($existing -gt 0) { Copy-Item -LiteralPath $csv -Destination "$csv.bak" -Force -ErrorAction SilentlyContinue }
    }
    if ($out.Count -eq 0) {
        Set-Content -LiteralPath $csv -Value "Prop,X,Y,Z,Yaw,Pitch,Roll,Scale,Tint,Zone" -Encoding utf8
    } else {
        $out | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding utf8
    }
    return $out.Count
}

# ---------------------------------------------------------------------------
# Ambience Config - fog per area, plus sky / water / lighting per region
# ---------------------------------------------------------------------------
# Two generated data files back this panel, both produced from the .lvl itself
# so nothing here re-derives offsets:
#
#   env_<region>.csv        one row per AREA - fog colour and distances. A
#                           region holds one LevelPrefs per named area, blended
#                           over lerpTime. Buzzardton has 34, Last Legs 5,
#                           Gizzard Gulch / Wolvark Docks / Sekto Springs 2
#                           each, the rest 1. 48 in total.
#   envregion_<region>.csv  42 region-level fields in four groups. SkyParams and
#                           the tail exist ONLY in the region default (set 0).
#
# WHAT ACTUALLY WORKS: fog. Verified in game. Sky, water and lighting decode and
# write correctly at the byte level but have never produced a visible change -
# see ModTools\ENVIRONMENT_HANDOFF.md section 1. The panel says so on the
# tables rather than quietly implying they do something.

function Get-AT3EnvFogTable {
    param($Region)
    $t = New-Object System.Data.DataTable
    foreach ($c in @("Area","RGB","A","Start","End","SetIndex",
                     "VanRGB","VanA","VanStart","VanEnd")) {
        [void]$t.Columns.Add($c, [string])
    }
    $p = Join-Path $RegionDataDir "env_$Region.csv"
    if (Test-Path $p) {
        foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
            $rgb = "{0}, {1}, {2}" -f $r.FogR, $r.FogG, $r.FogB
            $row = $t.NewRow()
            $nm = [string]$r.Area
            if (-not $nm) { $nm = "(region default)" }
            $row["Area"] = $nm
            $row["RGB"] = $rgb
            $row["A"] = [string]$r.FogA
            $row["Start"] = [string]$r.FogStart
            $row["End"] = [string]$r.FogEnd
            $row["SetIndex"] = [string]$r.SetIndex
            $row["VanRGB"] = $rgb
            $row["VanA"] = [string]$r.FogA
            $row["VanStart"] = [string]$r.FogStart
            $row["VanEnd"] = [string]$r.FogEnd
            $t.Rows.Add($row)
        }
    }
    $t.AcceptChanges()
    return ,$t
}

function Get-AT3EnvGroupTable {
    param($Region, $Group)
    $t = New-Object System.Data.DataTable
    foreach ($c in @("Param","RGB","A","Field","Kind","RgbOn","AOn","VanRGB","VanA")) {
        [void]$t.Columns.Add($c, [string])
    }
    $p = Join-Path $RegionDataDir "envregion_$Region.csv"
    if (-not (Test-Path $p)) { $t.AcceptChanges(); return ,$t }
    foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
        if ([string]$r.Group -ne $Group) { continue }
        $kind = [string]$r.Kind
        $van  = [string]$r.Vanilla
        $rgb = ""
        $a = ""
        $rgbOn = "0"
        $aOn = "0"
        if ($kind -eq "c") {
            # ColorF is R,G,B,A - split so alpha is edited on its own.
            $parts = @($van -split ",")
            if ($parts.Count -ge 4) {
                $rgb = "{0}, {1}, {2}" -f $parts[0].Trim(), $parts[1].Trim(), $parts[2].Trim()
                $a = $parts[3].Trim()
            } else {
                $rgb = $van
            }
            $rgbOn = "1"
            $aOn = "1"
        } elseif ($kind -eq "v2" -or $kind -eq "h") {
            # A (u, v) pair or a texture hash - one value, no alpha.
            $rgb = $van
            $rgbOn = "1"
        } else {
            # A plain scalar has no colour at all. It goes in A and the RGB cell
            # is disabled - this is the "only have an A" case.
            $a = $van
            $aOn = "1"
        }
        $row = $t.NewRow()
        $row["Param"] = [string]$r.Label
        $row["RGB"] = $rgb
        $row["A"] = $a
        $row["Field"] = [string]$r.Field
        $row["Kind"] = $kind
        $row["RgbOn"] = $rgbOn
        $row["AOn"] = $aOn
        $row["VanRGB"] = $rgb
        $row["VanA"] = $a
        $t.Rows.Add($row)
    }
    $t.AcceptChanges()
    return ,$t
}

# A cell that does not apply to its row is disabled and dimmed rather than left
# editable but meaningless. Bound to the row's RgbOn / AOn flag.
function New-AT3EnvCellStyle {
    param([string]$Flag)
    $conv = New-Object System.Windows.Media.BrushConverter
    $st = New-Object System.Windows.Style([System.Windows.Controls.DataGridCell])
    $dt = New-Object System.Windows.DataTrigger
    $dt.Binding = New-Object System.Windows.Data.Binding $Flag
    $dt.Value = "0"
    [void]$dt.Setters.Add((New-Object System.Windows.Setter(
        [System.Windows.UIElement]::IsEnabledProperty, $false)))
    [void]$dt.Setters.Add((New-Object System.Windows.Setter(
        [System.Windows.Controls.Control]::ForegroundProperty, $conv.ConvertFromString("#5A4B3A"))))
    [void]$dt.Setters.Add((New-Object System.Windows.Setter(
        [System.Windows.Controls.Control]::BackgroundProperty, $conv.ConvertFromString("#151010"))))
    [void]$st.Triggers.Add($dt)
    return $st
}

function New-AT3EnvGrid {
    param($Table, [switch]$Fog, [string]$FirstHeader = "Parameter")
    $conv = New-Object System.Windows.Media.BrushConverter
    $g = New-Object System.Windows.Controls.DataGrid
    $g.AutoGenerateColumns = $false
    $g.CanUserAddRows = $false
    $g.CanUserDeleteRows = $false
    $g.CanUserSortColumns = $false
    $g.HeadersVisibility = "Column"
    $g.GridLinesVisibility = "Horizontal"
    $g.Background    = $conv.ConvertFromString("#120D0A")
    $g.RowBackground = $conv.ConvertFromString("#1B1410")
    $g.Foreground    = $conv.ConvertFromString("#E8D9B5")
    $g.BorderBrush   = $conv.ConvertFromString("#2A3145")
    $g.HorizontalScrollBarVisibility = "Disabled"
    $g.MaxHeight = 260

    $firstBind = "Param"
    if ($Fog) { $firstBind = "Area" }
    $c = New-Object System.Windows.Controls.DataGridTextColumn
    $c.Header = $FirstHeader
    $c.IsReadOnly = $true
    $c.Binding = New-Object System.Windows.Data.Binding $firstBind
    $c.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.Controls.DataGridLengthUnitType]::Star)
    $c.MinWidth = 150
    [void]$g.Columns.Add($c)

    $specs = @(
        @{ H = "RGB"; B = "RGB"; W = 130; Flag = "RgbOn" }
        @{ H = "A";   B = "A";   W = 60;  Flag = "AOn" }
    )
    if ($Fog) {
        $specs += @{ H = "Fog Start Distance"; B = "Start"; W = 120; Flag = "" }
        $specs += @{ H = "Fog End Distance";   B = "End";   W = 120; Flag = "" }
    }
    foreach ($spec in $specs) {
        $col = New-Object System.Windows.Controls.DataGridTextColumn
        $col.Header = $spec.H
        $b = New-Object System.Windows.Data.Binding $spec.B
        $b.Mode = [System.Windows.Data.BindingMode]::TwoWay
        $b.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
        $col.Binding = $b
        $col.Width = New-Object System.Windows.Controls.DataGridLength $spec.W
        if ($spec.Flag -and -not $Fog) {
            $col.CellStyle = New-AT3EnvCellStyle -Flag $spec.Flag
        }
        [void]$g.Columns.Add($col)
    }

    $revert = New-Object System.Windows.Controls.DataGridTemplateColumn
    $revert.Header = ""
    $revert.Width = New-Object System.Windows.Controls.DataGridLength 40
    $revert.CellTemplate = [Windows.Markup.XamlReader]::Parse(
        '<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">' +
        '<Button Content="&#x21A9;" Width="24" Height="20" Padding="0" FontSize="12" ' +
        'ToolTip="Reset this row to its vanilla value" ' +
        'Background="#243040" Foreground="#BFD4E8" BorderBrush="#3E5A7A"/></DataTemplate>')
    [void]$g.Columns.Add($revert)
    Set-AT3GridEditStyle -Grid $g

    $isFog = [bool]$Fog
    [void]$g.AddHandler(
        [System.Windows.Controls.Button]::ClickEvent,
        [System.Windows.RoutedEventHandler]{
            param($sender, $e)
            try {
                $b = $e.OriginalSource
                if (-not ($b -is [System.Windows.Controls.Button])) { return }
                if ([string]$b.Content -ne [string][char]0x21A9) { return }
                $view = $b.DataContext
                if (-not ($view -is [System.Data.DataRowView])) { return }
                $view.Row["RGB"] = [string]$view.Row["VanRGB"]
                $view.Row["A"]   = [string]$view.Row["VanA"]
                if ($isFog) {
                    $view.Row["Start"] = [string]$view.Row["VanStart"]
                    $view.Row["End"]   = [string]$view.Row["VanEnd"]
                }
            } catch { }
        }.GetNewClosure())

    $g.ItemsSource = $Table.DefaultView
    return $g
}

# Tables stay alive per region for the life of the session, so switching the
# region dropdown and switching back does not throw away pending edits.
$script:AmbienceTables = @{}

$script:AmbienceGroups = @(
    @{ Key = "Water"; Group = "Water & Surface";
       Header = "---- WATER & SURFACE PARAMETERS ----";
       Note = "" }
    @{ Key = "Sky";   Group = "Sky";
       Header = "---- SKY PARAMETERS ----";
       Note = "" }
    @{ Key = "Clouds"; Group = "Clouds";
       Header = "---- CLOUDS ----";
       Note = "Three skybox layers, each with tiling, (u, v) scroll speed and parallax depth. Layer 2 is the fast one; layer 3 points at a blank texture and is effectively off. This is cloud MOTION - the shadow they cast is under Lighting & Shadows." }
    @{ Key = "Light"; Group = "Lighting & Shadows";
       Header = "---- LIGHTING & SHADOWS ----";
       Note = "Cloud shadow speed/tiling move the shadow across the ground - separate fields from the clouds themselves." }
    @{ Key = "Tex";   Group = "Textures & Cubemaps (experimental)";
       Header = "---- TEXTURES & CUBEMAPS (EXPERIMENTAL) ----";
       Note = "These are asset-path hashes, not numbers. Editable, but how the renderer consumes them is not understood." }
)

function Get-AT3AmbienceTables {
    param($Region)
    if ($script:AmbienceTables.ContainsKey($Region)) { return $script:AmbienceTables[$Region] }
    $set = @{ Fog = (Get-AT3EnvFogTable -Region $Region) }
    foreach ($g in $script:AmbienceGroups) {
        $set[$g.Key] = (Get-AT3EnvGroupTable -Region $Region -Group $g.Group)
    }
    # Current values come from the LIVE level, not the vanilla CSVs - so the
    # window shows what the game has, and putting a value back to vanilla is a
    # real change that gets written. $set.Live keeps what was read, so a field
    # that is modded on disk is rewritten even if left untouched here.
    $set.Live = @{}
    $r = Invoke-AT3Python -Arguments @((Join-Path $ModToolsDir "read_env.py"), $Region)
    if ($r.Ok) {
        foreach ($x in @(([string]$r.Output) | ConvertFrom-Csv)) {
            if ($x.Field) { $set.Live[[string]$x.Field + "|" + [string]$x.SetIndex] = [string]$x.Value }
        }
    }
    foreach ($row in $set.Fog.Rows) {
        $i = [string]$row["SetIndex"]
        $c = $set.Live["fogColor|" + $i]
        if ($c) {
            $parts = @($c -split ",")
            if ($parts.Count -ge 4) {
                $row["RGB"] = "{0}, {1}, {2}" -f $parts[0].Trim(), $parts[1].Trim(), $parts[2].Trim()
                $row["A"] = $parts[3].Trim()
            }
        }
        if ($set.Live.ContainsKey("fogStart|" + $i)) { $row["Start"] = $set.Live["fogStart|" + $i] }
        if ($set.Live.ContainsKey("fogEnd|" + $i))   { $row["End"]   = $set.Live["fogEnd|" + $i] }
    }
    foreach ($g in $script:AmbienceGroups) {
        foreach ($row in $set[$g.Key].Rows) {
            $v = $set.Live[[string]$row["Field"] + "|0"]
            if ($null -eq $v) { continue }
            $kind = [string]$row["Kind"]
            if ($kind -eq "c") {
                $parts = @($v -split ",")
                if ($parts.Count -ge 4) {
                    $row["RGB"] = "{0}, {1}, {2}" -f $parts[0].Trim(), $parts[1].Trim(), $parts[2].Trim()
                    $row["A"] = $parts[3].Trim()
                }
            } elseif ($kind -eq "v2" -or $kind -eq "h") {
                $row["RGB"] = $v
            } else {
                $row["A"] = $v
            }
        }
    }
    foreach ($t in @($set.Fog) + @($script:AmbienceGroups | ForEach-Object { $set[$_.Key] })) { $t.AcceptChanges() }
    $script:AmbienceTables[$Region] = $set
    return $set
}

function Show-AT3AmbienceConfig {
    $w = New-AT3Panel -Title "Ambience Config" -Width 1040 -Height 800 -Accent "blue"

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 14
    $w.Content = $root

    $bar = New-Object System.Windows.Controls.DockPanel
    [void][System.Windows.Controls.DockPanel]::SetDock($bar, "Top")
    [void]$root.Children.Add($bar)

    $rl = New-Object System.Windows.Controls.TextBlock
    $rl.Text = "Region"
    $rl.Width = 55
    $rl.VerticalAlignment = "Center"
    $rl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $rl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    [void]$bar.Children.Add($rl)

    $cmb = New-Object System.Windows.Controls.ComboBox
    $cmb.Height = 24
    $cmb.Width = 260
    $cmb.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $cmb.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $cmb.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $cmb.DisplayMemberPath = "Display"
    # Only regions with generated environment data. The utility room is a real
    # region but no env_<id>.csv is built for it, and an empty panel reads as a
    # broken one.
    foreach ($r in (Get-AT3Regions)) {
        if (Test-Path (Join-Path $RegionDataDir ("env_" + $r.Id + ".csv"))) { [void]$cmb.Items.Add($r) }
    }
    [void]$bar.Children.Add($cmb)

    $sv = New-Object System.Windows.Controls.ScrollViewer
    $sv.VerticalScrollBarVisibility = "Auto"
    $sv.Margin = New-Object System.Windows.Thickness 0,10,0,0
    $sp = New-Object System.Windows.Controls.StackPanel
    $sv.Content = $sp
    [void]$root.Children.Add($sv)

    $groups = $script:AmbienceGroups
    $build = {
        param($regionCode)
        $sp.Children.Clear()
        $set = Get-AT3AmbienceTables -Region $regionCode

        [void]$sp.Children.Add((New-AT3Header "---- FOG (PER AREA) ----" -Accent "blue"))
        $n = 0
        try { $n = $set.Fog.Rows.Count } catch { }
        [void]$sp.Children.Add((New-AT3Note "$n area(s) in this region. Fog is the one group confirmed to change the game visibly."))
        [void]$sp.Children.Add((New-AT3EnvGrid -Table $set.Fog -Fog -FirstHeader "Area"))

        foreach ($g in $groups) {
            [void]$sp.Children.Add((New-AT3Header $g.Header -Accent "blue"))
            if ($g.Note) { [void]$sp.Children.Add((New-AT3Note $g.Note)) }
            [void]$sp.Children.Add((New-AT3EnvGrid -Table $set[$g.Key] -FirstHeader "Parameter"))
        }

    }.GetNewClosure()

    [void]$cmb.Add_SelectionChanged({
        try {
            $sel = $cmb.SelectedItem
            if ($sel) { & $build ([string]$sel.Id) }
        } catch { }
    }.GetNewClosure())

    # Grids edit $script:AmbienceTables in place, so CANCEL restores copies
    # taken now; regions first opened in this window are dropped again.
    $before = @{}
    foreach ($k in @($script:AmbienceTables.Keys)) {
        $copy = @{}
        foreach ($tk in @($script:AmbienceTables[$k].Keys)) { $v = $script:AmbienceTables[$k][$tk]; $copy[$tk] = $(if ($v -is [System.Data.DataTable]) { $v.Copy() } else { $v }) }
        $before[$k] = $copy
    }
    $cfm = Add-AT3ConfirmBar -Window $w
    if ($cmb.Items.Count -gt 0) { $cmb.SelectedIndex = 0 }
    [void]$w.ShowDialog()
    if ($cfm.Ok) { Invoke-AT3Apply; return }
    foreach ($k in @($script:AmbienceTables.Keys)) {
        if ($before.ContainsKey($k)) { $script:AmbienceTables[$k] = $before[$k] }
        else { [void]$script:AmbienceTables.Remove($k) }
    }
}

# Harvest every region's tables into apply_env rows. Only values that actually
# differ from vanilla are emitted, so an untouched panel writes nothing at all.
function Get-AT3AmbienceEdits {
    param($Region)
    $out = @()
    if (-not $script:AmbienceTables.ContainsKey($Region)) { return $out }
    $set = $script:AmbienceTables[$Region]
    $live = $(if ($set.Live) { $set.Live } else { @{} })
    # True when the level on disk holds a non-vanilla value for this field -
    # it must be written even if the user left the row alone (a spawn reset
    # restores an older level file) or set it back to vanilla (the undo).
    $dirty = { param($key, $van) $live.ContainsKey($key) -and ($live[$key] -ne $van) }

    foreach ($r in $set.Fog.Rows) {
        $idx = [string]$r["SetIndex"]
        $rgb = ([string]$r["RGB"]).Trim()
        $a   = ([string]$r["A"]).Trim()
        if ($rgb -ne ([string]$r["VanRGB"]).Trim() -or $a -ne ([string]$r["VanA"]).Trim() -or
            (& $dirty ("fogColor|" + $idx) (([string]$r["VanRGB"]).Trim() + ", " + ([string]$r["VanA"]).Trim()))) {
            $out += [pscustomobject]@{ Field = "fogColor"; SetIndex = $idx; Value = "$rgb, $a" }
        }
        if (([string]$r["Start"]).Trim() -ne ([string]$r["VanStart"]).Trim() -or
            (& $dirty ("fogStart|" + $idx) ([string]$r["VanStart"]).Trim())) {
            $out += [pscustomobject]@{ Field = "fogStart"; SetIndex = $idx; Value = ([string]$r["Start"]).Trim() }
        }
        if (([string]$r["End"]).Trim() -ne ([string]$r["VanEnd"]).Trim() -or
            (& $dirty ("fogEnd|" + $idx) ([string]$r["VanEnd"]).Trim())) {
            $out += [pscustomobject]@{ Field = "fogEnd"; SetIndex = $idx; Value = ([string]$r["End"]).Trim() }
        }
    }

    foreach ($g in $script:AmbienceGroups) {
        $t = $set[$g.Key]
        if (-not $t) { continue }
        foreach ($r in $t.Rows) {
            $rgb = ([string]$r["RGB"]).Trim()
            $a   = ([string]$r["A"]).Trim()
            $vr  = ([string]$r["VanRGB"]).Trim()
            $va  = ([string]$r["VanA"]).Trim()
            $kind = [string]$r["Kind"]
            $vanStr = $(if ($kind -eq "c") { "$vr, $va" } elseif ($kind -eq "v2" -or $kind -eq "h") { $vr } else { $va })
            if ($rgb -eq $vr -and $a -eq $va -and -not (& $dirty ([string]$r["Field"] + "|0") $vanStr)) { continue }
            $val = $a
            if ($kind -eq "c") { $val = "$rgb, $a" }
            elseif ($kind -eq "v2" -or $kind -eq "h") { $val = $rgb }
            if (-not $val) { continue }
            # Everything outside fog lives only in the region default, set 0.
            $out += [pscustomobject]@{ Field = [string]$r["Field"]; SetIndex = "0"; Value = $val }
        }
    }
    return $out
}

function Set-AT3AmbienceAll {
    $envScript = Join-Path $ModToolsDir "apply_env.py"
    if (-not (Test-Path $envScript)) { return "" }
    $msgs = @()
    foreach ($code in @($script:AmbienceTables.Keys)) {
        $rows = @(Get-AT3AmbienceEdits -Region $code)
        if ($rows.Count -eq 0) { continue }
        $tmp = Join-Path $RegionDataDir "env_edits_$code.csv"
        $rows | Select-Object Field, SetIndex, Value |
            Export-Csv -LiteralPath $tmp -NoTypeInformation -Encoding utf8
        $res = Invoke-AT3Python -Arguments @($envScript, $code, "--csv", $tmp)
        if (-not $res.Ok) { $msgs += "Ambience[$code]: FAILED - $($res.Output)"; continue }
        $bad = @([string[]]($res.Output -split "`r?`n") | Where-Object { $_ -match "refused|unknown field|out of range" })
        if ($bad.Count -gt 0) {
            $msgs += "Ambience[$code]: $($rows.Count) edit(s), $($bad.Count) refused:"
            foreach ($bl in $bad) { $msgs += "   " + $bl.Trim() }
        } else {
            $msgs += "Ambience[$code]: $($rows.Count) field(s) applied."
        }
    }
    if ($msgs.Count -eq 0) { return "Ambience: unchanged (vanilla)." }
    return ($msgs -join "  ")
}

# ---------------------------------------------------------------------------
# Character Studio - the character LIBRARY, matching v1's NPC CONFIG
# ---------------------------------------------------------------------------
# A read-only catalogue of the characters the game defines, not a spawn editor.
# Two views, exactly as v1 had them:
#
#   All Regions   GlobalCatalogue.csv  - 67 characters, with the regions each
#                                        appears in
#   one region    catalogue_<id>.csv   - the characters that region uses, with
#                                        the spawn slots each hash occupies
#
# Below it, the custom character hashes we have created ourselves. These are not
# in any vanilla catalogue because they do not exist in a clean install - the
# hash IS game_hash of the character's prefs path, so a new character means a
# new path and a new hash.

function Get-AT3CharacterRows {
    param($Region)
    Use-AT3Catalogue
    $t = New-Object System.Data.DataTable
    foreach ($c in @("Hash","Name","HP","Faction","Spawns","Where")) {
        [void]$t.Columns.Add($c, [string])
    }
    if ($Region -eq "*") {
        $p = Join-Path $RegionDataDir "GlobalCatalogue.csv"
        $col = "Regions"
    } else {
        $p = Join-Path $RegionDataDir "catalogue_$Region.csv"
        $col = "Slots"
    }
    if (Test-Path $p) {
        foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
            $row = $t.NewRow()
            $row["Hash"] = ([string]$r.Hash).ToUpper()
            $row["Name"] = [string]$r.Name
            $row["HP"] = [string]$r.HP
            $row["Faction"] = [string]$r.Faction
            $row["Spawns"] = [string]$r.Spawns
            $row["Where"] = [string]$r.$col
            $t.Rows.Add($row)
        }
    }
    $t.AcceptChanges()
    return ,$t
}

function Get-AT3CustomHashRows {
    # A custom character exists in ONE region - the records that define it were
    # added to that region's bundles. Showing it under every region implied it
    # was available everywhere, which it is not.
    param($Region)
    $t = New-Object System.Data.DataTable
    foreach ($c in @("Name","Hash","Region","ClonedFrom","Notes")) { [void]$t.Columns.Add($c, [string]) }
    $p = Join-Path $AT3Dir "CustomHashes.csv"
    if (Test-Path $p) {
        foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
            if ($Region -ne "*" -and ([string]$r.Region) -ne $Region) { continue }
            $row = $t.NewRow()
            $row["Name"] = [string]$r.Name
            $row["Hash"] = ([string]$r.Hash).ToUpper()
            $row["Region"] = [string]$r.Region
            $row["ClonedFrom"] = [string]$r.ClonedFrom
            $row["Notes"] = [string]$r.Notes
            $t.Rows.Add($row)
        }
    }
    $t.AcceptChanges()
    return ,$t
}

function New-AT3CharacterGrid {
    param($Table, $Cols)
    $conv = New-Object System.Windows.Media.BrushConverter
    $g = New-Object System.Windows.Controls.DataGrid
    $g.AutoGenerateColumns = $false
    $g.CanUserAddRows = $false
    $g.CanUserDeleteRows = $false
    $g.CanUserSortColumns = $true
    $g.IsReadOnly = $true
    $g.HeadersVisibility = "Column"
    $g.GridLinesVisibility = "Horizontal"
    $g.Background    = $conv.ConvertFromString("#120D0A")
    $g.RowBackground = $conv.ConvertFromString("#1B1410")
    $g.Foreground    = $conv.ConvertFromString("#E8D9B5")
    $g.BorderBrush   = $conv.ConvertFromString("#4A3524")
    $g.HorizontalScrollBarVisibility = "Disabled"
    $g.MaxHeight = 340
    foreach ($col in $Cols) {
        $c = New-Object System.Windows.Controls.DataGridTextColumn
        $c.Header = $col.Header
        $c.Binding = New-Object System.Windows.Data.Binding($col.Bind)
        if ($col.Width -eq 0) {
            $c.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.Controls.DataGridLengthUnitType]::Star)
        } else {
            $c.Width = New-Object System.Windows.Controls.DataGridLength($col.Width)
        }
        [void]$g.Columns.Add($c)
    }
    $g.ItemsSource = $Table.DefaultView
    return $g
}

function Show-AT3CharacterStudio {
    Use-AT3Catalogue
    $w = New-AT3Panel -Title "Character Catalogue" -Width 1000 -Height 760

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 14
    $w.Content = $root

    $bar = New-Object System.Windows.Controls.DockPanel
    [void][System.Windows.Controls.DockPanel]::SetDock($bar, "Top")
    [void]$root.Children.Add($bar)

    $rl = New-Object System.Windows.Controls.TextBlock
    $rl.Text = "Region"
    $rl.Width = 55
    $rl.VerticalAlignment = "Center"
    $rl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $rl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    [void]$bar.Children.Add($rl)

    $cmb = New-Object System.Windows.Controls.ComboBox
    $cmb.Height = 24
    $cmb.Width = 260
    $cmb.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $cmb.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $cmb.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $cmb.DisplayMemberPath = "Display"
    # "*" is the global view - every character with the regions it appears in.
    [void]$cmb.Items.Add([pscustomobject]@{ Id = "*"; Display = "All Regions" })
    foreach ($r in (Get-AT3Regions)) {
        if (Test-Path (Join-Path $RegionDataDir ("catalogue_" + $r.Id + ".csv"))) {
            [void]$cmb.Items.Add($r)
        }
    }
    [void]$bar.Children.Add($cmb)

    $sv = New-Object System.Windows.Controls.ScrollViewer
    $sv.VerticalScrollBarVisibility = "Auto"
    $sv.Margin = New-Object System.Windows.Thickness 0,10,0,0
    $sp = New-Object System.Windows.Controls.StackPanel
    $sv.Content = $sp
    [void]$root.Children.Add($sv)

    # Shared with the handlers $build creates: a GetNewClosure block cannot see
    # a variable assigned after it was made, so $build reaches itself (for the
    # refresh after a delete) through this hashtable.
    $studio = @{ Build = $null; Region = "*" }
    $build = {
        param($id)
        # A LOCAL copy for the Delete handler below: its GetNewClosure captures
        # only the locals of this invocation, and $studio lives one scope up in
        # $build's own closure module - there it would read as $null.
        $shared = $studio
        $shared.Region = $id
        $sp.Children.Clear()

        $tbl = Get-AT3CharacterRows -Region $id
        $n = 0
        try { $n = $tbl.Rows.Count } catch { }
        if ($id -eq "*") {
            $cols = @(
                @{ Header = "Hash";    Bind = "Hash";    Width = 90 }
                @{ Header = "Name";    Bind = "Name";    Width = 0 }
                @{ Header = "HP";      Bind = "HP";      Width = 75 }
                @{ Header = "Faction"; Bind = "Faction"; Width = 80 }
                @{ Header = "Spawns";  Bind = "Spawns";  Width = 70 }
                @{ Header = "Appears In"; Bind = "Where"; Width = 300 }
            )
            $note = "$n character(s) across the whole game."
        } else {
            $cols = @(
                @{ Header = "Hash";    Bind = "Hash";    Width = 90 }
                @{ Header = "Name";    Bind = "Name";    Width = 190 }
                @{ Header = "HP";      Bind = "HP";      Width = 75 }
                @{ Header = "Faction"; Bind = "Faction"; Width = 75 }
                @{ Header = "Spawns";  Bind = "Spawns";  Width = 65 }
                @{ Header = "Slots";   Bind = "Where";   Width = 0 }
            )
            $note = "$n character(s) used in this region."
        }
        [void]$sp.Children.Add((New-AT3Header "---- CHARACTER LIBRARY ----"))
        [void]$sp.Children.Add((New-AT3Note $note))
        [void]$sp.Children.Add((New-AT3CharacterGrid -Table $tbl -Cols $cols))

        $ct = Get-AT3CustomHashRows -Region $id
        $cn = 0
        try { $cn = $ct.Rows.Count } catch { }
        [void]$sp.Children.Add((New-AT3Header "---- CUSTOM HASHES ----"))
        [void]$sp.Children.Add((New-AT3Note "$cn custom character(s) in this region. A character's hash IS game_hash of its prefs path, so the name stem is not cosmetic - changing it changes the hash."))
        $cg = New-AT3CharacterGrid -Table $ct -Cols @(
            @{ Header = "Name";        Bind = "Name";       Width = 190 }
            @{ Header = "Hash";        Bind = "Hash";       Width = 90 }
            @{ Header = "Region";      Bind = "Region";     Width = 60 }
            @{ Header = "Cloned From"; Bind = "ClonedFrom"; Width = 200 }
            @{ Header = "Notes";       Bind = "Notes";      Width = 0 }
        )
        [void]$sp.Children.Add($cg)
        $del = New-Object System.Windows.Controls.Button
        $del.Content = "Delete selected custom hash"
        $del.Height = 28
        $del.MinWidth = 230
        $del.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
        $del.Margin = New-Object System.Windows.Thickness 0,8,0,4
        $del.IsEnabled = $false
        [void]$sp.Children.Add($del)
        [void]$sp.Children.Add((New-AT3Note ("Deleting takes the record out of its region's bundle and removes the library entry. " +
            "It is refused while anything still uses it - a placed or queued spawn, or a character carrying the weapon - so " +
            "remove those first. Meshes and textures its build copied in are left alone. The bundle, blockmap and " +
            "CustomHashes.csv are backed up first; python ModTools\delete_custom.py --revert <HASH> puts them back.")))
        [void]$cg.Add_SelectionChanged({ $del.IsEnabled = ($null -ne $cg.SelectedItem) }.GetNewClosure())
        [void]$del.Add_Click({
            $row = $cg.SelectedItem
            if (-not $row) { return }
            $nm = [string]$row["Name"]
            $hx = [string]$row["Hash"]
            $msg = ("Delete '{0}' ({1})?" -f $nm, $hx) + [Environment]::NewLine + [Environment]::NewLine +
                "Its record is taken out of the region's bundle and its library entry removed. This is refused if anything " +
                "still uses it - a placed or queued spawn, or a character carrying the weapon." +
                [Environment]::NewLine + [Environment]::NewLine + "The bundle, blockmap and CustomHashes.csv are backed up first."
            if (-not (Confirm-AT3Choice -Title "Delete Custom Hash" -Text $msg)) { return }
            $res = Invoke-AT3Python -Arguments @((Join-Path $ModToolsDir "delete_custom.py"), $hx) -Activity ("Deleting " + $nm)
            $txt = [string]$res.Output
            Write-AT3Log ("delete custom '" + $nm + "' " + $hx + " ok=" + $res.Ok + " :: " + ($txt -replace "`r?`n", " | "))
            $problem = @($txt -split "`r?`n" | Where-Object { $_ -match "REFUSED|FAILED" })
            if ($txt -match "REMOVED library entry" -and -not $problem.Count) {
                [void](Update-AT3Index)
                [void](Update-AT3Catalogue)
                [void](Update-AT3CharacterModel)
                Show-AT3Notice -Title "Delete Custom Hash" -Text ("'" + $nm + "' was deleted." + [Environment]::NewLine + [Environment]::NewLine +
                    ((@($txt -split "`r?`n" | Where-Object { $_ -match "DELETED|REMOVED" }) | ForEach-Object { $_.Trim() }) -join [Environment]::NewLine))
                & $shared.Build $shared.Region
            } else {
                Show-AT3Notice -Title "Delete Custom Hash" -Icon "Warning" -Text ("'" + $nm + "' was NOT deleted." + [Environment]::NewLine + [Environment]::NewLine +
                    (($problem | ForEach-Object { $_.Trim() }) -join [Environment]::NewLine))
            }
        }.GetNewClosure())
    }.GetNewClosure()
    $studio.Build = $build

    [void]$cmb.Add_SelectionChanged({
        try {
            $sel = $cmb.SelectedItem
            if ($sel) { & $build ([string]$sel.Id) }
        } catch { }
    }.GetNewClosure())

    $foot = New-Object System.Windows.Controls.TextBlock
    $foot.Text = "New characters are built, and existing ones edited, in CREATOR > CHARACTER CREATOR."
    $foot.TextWrapping = "Wrap"
    $foot.Margin = New-Object System.Windows.Thickness 0,12,0,0
    $foot.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $foot.FontStyle = [System.Windows.FontStyles]::Italic
    $foot.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#B99A63")
    [void][System.Windows.Controls.DockPanel]::SetDock($foot, "Bottom")
    [void]$root.Children.Insert(1, $foot)

    if ($cmb.Items.Count -gt 0) { $cmb.SelectedIndex = 0 }
    [void]$w.ShowDialog()
}

function Show-AT3PropEditor {
    $w = New-AT3Panel -Title "Prop Editor" -Width 1000 -Height 640 -Accent "blue"

    $grid = New-Object System.Windows.Controls.Grid
    $grid.Margin = New-Object System.Windows.Thickness 14
    foreach ($width in @(1, 1)) {
        $cd = New-Object System.Windows.Controls.ColumnDefinition
        $cd.Width = New-Object System.Windows.GridLength($width, [System.Windows.GridUnitType]::Star)
        [void]$grid.ColumnDefinitions.Add($cd)
    }
    $w.Content = $grid

    # ---------------- left: region + placements ----------------
    $left = New-Object System.Windows.Controls.DockPanel
    $left.Margin = New-Object System.Windows.Thickness 0,0,8,0
    [void]$grid.Children.Add($left)
    [System.Windows.Controls.Grid]::SetColumn($left, 0)

    $regionBar = New-Object System.Windows.Controls.DockPanel
    [void][System.Windows.Controls.DockPanel]::SetDock($regionBar, "Top")
    [void]$left.Children.Add($regionBar)

    $rl = New-Object System.Windows.Controls.TextBlock
    $rl.Text = "Region"
    $rl.Width = 55
    $rl.VerticalAlignment = "Center"
    $rl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $rl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    [void]$regionBar.Children.Add($rl)

    $cmb = New-Object System.Windows.Controls.ComboBox
    $cmb.Height = 24
    $cmb.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $cmb.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $cmb.DisplayMemberPath = "Display"
    foreach ($r in (Get-AT3Regions)) { [void]$cmb.Items.Add($r) }
    [void]$regionBar.Children.Add($cmb)

    $hdr = New-AT3Header "---- PLACEMENTS ----" -Accent "blue"
    [void][System.Windows.Controls.DockPanel]::SetDock($hdr, "Top")
    [void]$left.Children.Add($hdr)

    $pg = New-Object System.Windows.Controls.DataGrid
    $pg.AutoGenerateColumns = $false
    $pg.CanUserAddRows = $false
    $pg.CanUserDeleteRows = $false
    $pg.CanUserSortColumns = $false
    $pg.HeadersVisibility = "Column"
    $pg.GridLinesVisibility = "Horizontal"
    $pg.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#120D0A")
    $pg.RowBackground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#1B1410")
    $pg.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    $pg.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A3145")

    # Remove button FIRST so it sits at the far left, where it is reachable
    # without scrolling a wide row.
    $del = New-Object System.Windows.Controls.DataGridTemplateColumn
    $del.Header = ""
    $del.Width = New-Object System.Windows.Controls.DataGridLength 34
    $del.CellTemplate = [Windows.Markup.XamlReader]::Parse(
        '<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">' +
        '<Button Content="&#x2716;" Width="26" Height="20" Padding="0" FontSize="12" ToolTip="Remove this placement" ' +
        'Background="#4A2A22" Foreground="#E8C9A0" BorderBrush="#8A5A3B"/></DataTemplate>')
    [void]$pg.Columns.Add($del)

    $cName = New-Object System.Windows.Controls.DataGridTextColumn
    $cName.Header = "Prop"
    $cName.IsReadOnly = $true
    $cName.Binding = New-Object System.Windows.Data.Binding "Prop"
    $cName.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.GridUnitType]::Star)
    $cName.MinWidth = 120
    [void]$pg.Columns.Add($cName)

    # Debris Tint is BGRA and the header says so, because the order is not what
    # anyone expects: red is 0000FF, not FF0000. It colours the fragments and
    # drops an object produces, never its mesh - see ModTools notes.
    foreach ($spec in @(
        @{ H = "Position (X Y Z)"; B = "Position"; W = 140 }
        @{ H = "Yaw";   B = "Yaw";   W = 46 }
        @{ H = "Pitch"; B = "Pitch"; W = 46 }
        @{ H = "Roll";  B = "Roll";  W = 46 }
        @{ H = "Scale"; B = "Scale"; W = 58 }
        @{ H = "Debris Tint (BGRA)"; B = "Tint"; W = 120 }
    )) {
        $c = New-Object System.Windows.Controls.DataGridTextColumn
        $c.Header = $spec.H
        $b = New-Object System.Windows.Data.Binding $spec.B
        $b.Mode = [System.Windows.Data.BindingMode]::TwoWay
        $b.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
        $c.Binding = $b
        $c.Width = New-Object System.Windows.Controls.DataGridLength $spec.W
        [void]$pg.Columns.Add($c)
    }
    Set-AT3GridEditStyle -Grid $pg

    [void]$pg.AddHandler(
        [System.Windows.Controls.Button]::ClickEvent,
        [System.Windows.RoutedEventHandler]{
            param($sender, $e)
            try {
                $b = $e.OriginalSource
                if (-not ($b -is [System.Windows.Controls.Button])) { return }
                if ([string]$b.Content -ne [string][char]0x2716) { return }
                $view = $b.DataContext
                if ($view -is [System.Data.DataRowView]) { $view.Row.Delete() }
            } catch { }
        }.GetNewClosure())
    [void]$left.Children.Add($pg)

    # ---------------- right: searchable library ----------------
    $right = New-Object System.Windows.Controls.DockPanel
    $right.Margin = New-Object System.Windows.Thickness 8,0,0,0
    [void]$grid.Children.Add($right)
    [System.Windows.Controls.Grid]::SetColumn($right, 1)

    $searchBar = New-Object System.Windows.Controls.DockPanel
    [void][System.Windows.Controls.DockPanel]::SetDock($searchBar, "Top")
    [void]$right.Children.Add($searchBar)
    $sl = New-Object System.Windows.Controls.TextBlock
    $sl.Text = "Search"
    $sl.Width = 55
    $sl.VerticalAlignment = "Center"
    $sl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $sl.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    [void]$searchBar.Children.Add($sl)
    $search = New-Object System.Windows.Controls.TextBox
    $search.Height = 24
    $search.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A1F16")
    $search.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#F2E4C4")
    $search.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#5A6E9C")
    [void]$searchBar.Children.Add($search)

    $lhdr = New-AT3Header "---- OBJECT LIBRARY ----" -Accent "blue"
    [void][System.Windows.Controls.DockPanel]::SetDock($lhdr, "Top")
    [void]$right.Children.Add($lhdr)

    $addBtn = New-Object System.Windows.Controls.Button
    $addBtn.Content = "Add selected object to placements"
    $addBtn.Height = 28
    $addBtn.Margin = New-Object System.Windows.Thickness 0,8,0,0
    [void][System.Windows.Controls.DockPanel]::SetDock($addBtn, "Bottom")
    $portBtn = New-Object System.Windows.Controls.Button
    $portBtn.Content = "Port geometry from another region..."
    $portBtn.Height = 28
    $portBtn.Margin = New-Object System.Windows.Thickness 0,6,0,0
    $portBtn.ToolTip = "Copy a mesh from any region into this one so it appears in the Object Library. Written to the game at once."
    [void][System.Windows.Controls.DockPanel]::SetDock($portBtn, "Bottom")
    [void]$right.Children.Add($portBtn)
    [void]$right.Children.Add($addBtn)

    $lib = New-Object System.Windows.Controls.DataGrid
    $lib.AutoGenerateColumns = $false
    $lib.CanUserAddRows = $false
    $lib.IsReadOnly = $false
    $lib.HeadersVisibility = "Column"
    $lib.GridLinesVisibility = "Horizontal"
    $lib.Background = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#120D0A")
    $lib.RowBackground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#1B1410")
    $lib.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    $lib.BorderBrush = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#2A3145")
    $lib.VerticalScrollBarVisibility = "Visible"
    foreach ($spec in @(
        @{ H = "Object"; B = "Name";  W = 0;   RO = $false }
        @{ H = "Asset";  B = "Asset"; W = 150; RO = $true }
        @{ H = "In use"; B = "Count"; W = 55;  RO = $true }
        # "Placeable in" is gone. It answered a question that no longer exists:
        # anything can be placed anywhere now. A prop whose geometry the target
        # zone cannot reach is imported into tgl by ensure_asset, with its home
        # bundle's non-mesh records so it arrives lit. Showing a zone list would
        # only imply a restriction that is not there.
        @{ H = "Baked for zones"; B = "Baked"; W = 130; RO = $true }
    )) {
        $c = New-Object System.Windows.Controls.DataGridTextColumn
        $c.Header = $spec.H
        $c.IsReadOnly = $spec.RO
        $bnd = New-Object System.Windows.Data.Binding $spec.B
        if (-not $spec.RO) { $bnd.Mode = [System.Windows.Data.BindingMode]::TwoWay }
        $c.Binding = $bnd
        if ($spec.W -eq 0) {
            $c.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.GridUnitType]::Star)
        } else {
            $c.Width = New-Object System.Windows.Controls.DataGridLength $spec.W
        }
        [void]$lib.Columns.Add($c)
    }
    Set-AT3GridEditStyle -Grid $lib
    [void]$lib.Add_CellEditEnding({
        param($sender, $e)
        try {
            if ([string]$e.Column.Header -ne "Object") { return }
            $item = $e.Row.Item
            $txt = $e.EditingElement.Text
            if ($null -eq $item -or -not $txt) { return }
            Save-AT3PropName -Key ([string]$item.Key) -Name ([string]$txt)
        } catch { }
    })
    [void]$right.Children.Add($lib)

    # ---------------- behaviour ----------------
    # State lives in this hashtable, NOT in $script: variables. These handlers
    # are GetNewClosure scriptblocks, and a $script: assignment inside one goes
    # to the closure's own module rather than the script - the write is lost.
    # $state is captured by reference, so mutating it works.
    $state = @{ Region = $null; Lib = @(); Table = $null }

    $loadRegion = {
        param($region)
        if (-not $region) { return }
        if ($state.Region -and $state.Table) { [void](Save-AT3PropRows -Region $state.Region -Table $state.Table) }
        $state.Region = $region
        $state.Table = Read-AT3PropRows -Region $region
        $pg.ItemsSource = $state.Table.DefaultView
        $state.Lib = @(Get-AT3PropLibrary -Region $region)
        $lib.ItemsSource = $state.Lib
        $search.Text = ""
    }.GetNewClosure()

    [void]$cmb.Add_SelectionChanged({
        try {
            $sel = $cmb.SelectedItem
            if ($sel) { & $loadRegion ([string]$sel.Id) }
        } catch { }
    }.GetNewClosure())

    [void]$search.Add_TextChanged({
        try {
            $q = $search.Text.Trim().ToLower()
            if (-not $q) { $lib.ItemsSource = $state.Lib; return }
            $lib.ItemsSource = @($state.Lib | Where-Object { $_.Search.Contains($q) })
        } catch { }
    }.GetNewClosure())

    # PORT GEOMETRY. Writes the mesh into this region's tgl immediately - it is
    # an asset import, not a placement, so it does not wait for Confirm and
    # Cancel does not undo it (port_prop_geo.py --revert does). The library is
    # re-read afterwards and the new row selected.
    [void]$portBtn.Add_Click({
        try {
            if (-not $state.Region) { return }
            $g = Show-AT3GeometryPicker -Purpose "prop"
            if (-not $g) { return }
            if (@($state.Lib | Where-Object { $_.Key -eq $g.Hash }).Count) {
                Show-AT3Notice -Title "Port Geometry" -Text ("'" + $g.Name + "' is already in this region's Object Library.")
                return
            }
            $msg = ("Port '" + $g.Name + "' (" + $g.Hash + ") into region " + $state.Region + "?" + [Environment]::NewLine +
                    [Environment]::NewLine + "This writes to the game now, independent of Confirm/Cancel. Undo with:" +
                    [Environment]::NewLine + "python ModTools\port_prop_geo.py --revert " + $g.Hash + " --to " + $state.Region)
            if (-not (Confirm-AT3Choice -Title "Port Geometry" -Text $msg)) { return }
            $r = Invoke-AT3Python -Arguments @((Join-Path $ModToolsDir "port_prop_geo.py"), $state.Region, $g.Hash) `
                -Activity ("Porting " + $g.Name)
            $txt = [string]$r.Output
            Write-AT3Log ("port prop geo " + $g.Hash + " -> " + $state.Region + " :: " + ($txt -replace "`r?`n", " | "))
            if ($txt -match "PORTED|ALREADY") {
                [void](Update-AT3Index)
                $state.Lib = @(Get-AT3PropLibrary -Region $state.Region)
                $search.Text = ""
                $lib.ItemsSource = $state.Lib
                $hit = @($state.Lib | Where-Object { $_.Key -eq $g.Hash })
                if ($hit.Count) { $lib.SelectedItem = $hit[0]; $lib.ScrollIntoView($hit[0]) }
                $warn = $(if ($txt -match "NO kind-3") { [Environment]::NewLine + [Environment]::NewLine +
                    "Its source bundle has no lightmap, so placements of it may render very bright." } else { "" })
                Show-AT3Notice -Title "Port Geometry" -Text ("'" + $g.Name + "' is now in this region's Object Library." + $warn)
            } else {
                $why = @($txt -split "`r?`n" | Where-Object { $_ -match "REFUSED|FAILED" }) -join [Environment]::NewLine
                Show-AT3Notice -Title "Port Geometry" -Icon "Warning" -Text ("Port did not complete." + [Environment]::NewLine +
                    $(if ($why) { $why } else { $txt }))
            }
        } catch { Show-AT3Notice -Title "Port Geometry" -Icon "Warning" -Text ("Port failed: " + $_.Exception.Message) }
    }.GetNewClosure())

    [void]$addBtn.Add_Click({
        try {
            $sel = $lib.SelectedItem
            if (-not $sel) { return }
            if (-not $state.Table) { return }
            $row = $state.Table.NewRow()
            $row["Prop"] = $sel.Name
            $row["Key"] = $sel.Key
            $row["Position"] = "0  0  0"
            $row["Yaw"] = "0"; $row["Pitch"] = "0"; $row["Roll"] = "0"
            $state.Table.Rows.Add($row)
        } catch { }
    }.GetNewClosure())

    [void]$w.Add_Closed({
        try {
            [void]$pg.CommitEdit([System.Windows.Controls.DataGridEditingUnit]::Row, $true)
            if ($state.Region -and $state.Table) { [void](Save-AT3PropRows -Region $state.Region -Table $state.Table) }
        } catch { }
    }.GetNewClosure())

    $script:PropState = $state
    if ($cmb.Items.Count -gt 0) {
        $want = $cmb.Items | Where-Object { $_.Id -eq "01" } | Select-Object -First 1
        $cmb.SelectedItem = $(if ($want) { $want } else { $cmb.Items[0] })
    }

    $cfm = Add-AT3ConfirmBar -Window $w
    $snap = Save-AT3EditorSnapshot
    [void]$w.ShowDialog()
    # The editor saves its CSVs as it goes (region switches, close); CANCEL
    # puts every one of them back as it was when the window opened.
    if ($cfm.Ok) { Invoke-AT3Apply } else { Restore-AT3EditorSnapshot -Snap $snap }
}

# ---------------------------------------------------------------------------
# Spawns Editor
# ---------------------------------------------------------------------------
# The region's spawn list, in spawn order - the same `Slot` numbering every
# ModTools script uses, so a row here and a row in spawns_<region>.csv are the
# same thing.
#
# The grid shows VANILLA, read from RegionData\spawntable_<region>.csv, and the
# user's changes live in spawns_<region>.csv as a DIFF. That is what makes the
# revert arrow meaningful: there is always an untouched baseline to go back to.
# The baseline is written by `python ModTools\spawn_catalog.py --build`, which
# also adds each spawn's zone, area, trigger group, script and jobs, and the
# job spots in spawnjobs_<region>.csv. Its first nine columns are unchanged, so
# saved diffs stay keyed to the same slots.
#
# Only CHANGED fields are written. apply_spawns treats every field of an `edit`
# as optional and leaves blanks alone, which matters for the 24 spawns across
# the game whose rotation is not a pure Z turn - writing a yaw back would
# flatten their tilt, so an untouched Yaw cell writes nothing at all.

# LIVE. The user's level is already modded and keeps changing, so the catalogue
# describes the lm_level_NN.lvl the game loads, not the .spawnsbak base - only
# the baseline columns that saved edits are keyed to come from the base. It is
# cached against every file it reads, so calling this on every region switch
# costs one python start when nothing changed.
function Update-AT3SpawnCatalogue {
    param([string]$Region)
    $s = Join-Path $ModToolsDir "spawn_catalog.py"
    if (-not (Test-Path $s)) { return $false }
    $argv = @($s, "--build")
    if ($Region) { $argv += @("--region", $Region) }
    $r = Invoke-AT3Python -Arguments $argv -Activity "Reading the live level's spawns"
    return [bool]$r.Ok
}

# Key -> the job spots (spawnjobs_<region>.csv rows) restricted to that spawn.
# Keys are a base slot ("12"), or "L" + a live index ("L14") for a spawn with no
# base slot. A job names the spawn it serves by the spawn's tag; the spawn never
# names the job, which is why this is keyed from the job side.
function Get-AT3SpawnJobs {
    param($Region)
    $map = @{}
    $p = Join-Path $RegionDataDir "spawnjobs_$Region.csv"
    if (-not (Test-Path $p)) { return $map }
    foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
        $keys = @()
        foreach ($s in @(([string]$r.GuySlot).Split([char]32, [System.StringSplitOptions]::RemoveEmptyEntries))) { $keys += $s }
        foreach ($s in @(([string]$r.GuyLive).Split([char]32, [System.StringSplitOptions]::RemoveEmptyEntries))) { $keys += ("L" + $s) }
        foreach ($k in $keys) {
            if (-not $map.ContainsKey($k)) { $map[$k] = New-Object System.Collections.ArrayList }
            [void]$map[$k].Add($r)
        }
    }
    return $map
}

# Every spawn in the LIVE level, in live order, each with its Origin.
function Get-AT3SpawnLive {
    param($Region)
    $p = Join-Path $RegionDataDir "spawnlive_$Region.csv"
    if (-not (Test-Path $p)) { return @() }
    return @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)
}

function ConvertTo-AT3ScriptShort {
    param([string]$Name, [string]$Hash)
    if ($Name.StartsWith("|")) { return ($Name.TrimEnd("|") -split '\|')[-1] }
    if ($Name) { return (($Name -split '[\\/]')[-1] -replace '\.foo$', '') }
    if ($Hash) { return "script $Hash" }
    return ""
}

# The read-only organising cells, from a catalogue row that describes a spawn AS
# IT STANDS IN THE LIVE LEVEL (spawntable_ for a base slot, spawnlive_ for any
# other). They are not touched by retyping, moving or deleting in the grid, so
# a row keeps its place until Apply Changes rewrites the level and the next
# catalogue refresh re-reads it. $Pad breaks ties within a group.
function Set-AT3SpawnDescribeCells {
    param($Row, $Src, [string]$Pad)
    $area = [string]$Src.Area
    if (-not $area) {
        # an old spawntable without the catalogue columns
        foreach ($k in @("Location", "ZoneLabel", "GroupLabel", "ScriptShort", "JobsLabel")) { $Row[$k] = "(catalogue not built)" }
        foreach ($k in @("SortLoc", "SortGroup", "SortScript", "SortJob")) { $Row[$k] = $Pad }
        return
    }
    $zn = 0
    [void][int]::TryParse([string]$Src.Zone, [ref]$zn)
    $Row["Location"] = $area
    $Row["ZoneLabel"] = ("zone {0}  {1}" -f $zn, [string]$Src.ZoneName).Trim()
    $Row["GroupHash"] = [string]$Src.Group
    $Row["GroupName"] = [string]$Src.GroupName
    $Row["GroupSize"] = [string]$Src.GroupSize
    if ([string]$Src.GroupName) { $Row["GroupLabel"] = [string]$Src.GroupName }
    elseif ([string]$Src.Group) { $Row["GroupLabel"] = "group " + [string]$Src.Group }
    else { $Row["GroupLabel"] = "(no group)" }
    $Row["ScriptName"] = [string]$Src.ScriptName
    $Row["ScriptKind"] = [string]$Src.ScriptKind
    $short = ConvertTo-AT3ScriptShort -Name ([string]$Src.ScriptName) -Hash ([string]$Src.Script)
    if ($short) { $Row["ScriptShort"] = $short } else { $Row["ScriptShort"] = "(no script)" }
    if ([string]$Src.JobScripts) { $Row["JobsLabel"] = [string]$Src.JobScripts } else { $Row["JobsLabel"] = "(no jobs)" }
    $Row["SortLoc"] = "{0}|{1:D3}|{2}" -f $area, $zn, $Pad
    $Row["SortGroup"] = $(if ([string]$Src.Group) { "0|" + $Row["GroupLabel"] + "|" + $Pad } else { "1|" + $Pad })
    $Row["SortScript"] = $(if ($short) { "0|" + $short + "|" + $Pad } else { "1|" + $Pad })
    $Row["SortJob"] = $(if ([string]$Src.JobScripts) { "0|" + [string]$Src.JobScripts + "|" + $Pad } else { "1|" + $Pad })
}

function Set-AT3SpawnLiveCells {
    param($Row, [string]$State, [string]$Hash, [string]$Name, [string]$Index)
    $Row["LiveState"] = $State
    $Row["LiveHash"] = $Hash
    $Row["LiveName"] = $Name
    $Row["LiveIndex"] = $Index
}

# A vanilla slot.
function Set-AT3SpawnCatalogueCells {
    param($Row, $Base)
    $pad = "{0:D4}" -f ([int][string]$Base.Slot)
    $Row["TagHex"] = [string]$Base.Tag
    Set-AT3SpawnLiveCells -Row $Row -State ([string]$Base.LiveState) -Hash ([string]$Base.LiveHash) -Name ([string]$Base.LiveName) -Index ([string]$Base.LiveIndex)
    Set-AT3SpawnDescribeCells -Row $Row -Src $Base -Pad $pad
    $Row["SortSlot"] = $pad
}

# An added spawn. Once Apply Changes has put it in the level, $Live is its
# spawnlive_ row and it sorts into its real area, zone and group. Before that
# there is nothing to read: apply_spawns picks its zone from the records around
# its position and severs its script, so it gets placeholders and sorts last.
# DataView sorts strings culture-aware, where "~" ranks BEFORE letters; a run
# of z's is what reliably lands after every area name and slot number.
function Set-AT3SpawnNewCells {
    param($Row, [int]$Index, $Live)
    $last = "zzzzzz|0|{0:D4}" -f $Index
    if ($Live) {
        $Row["TagHex"] = [string]$Live.Tag
        Set-AT3SpawnLiveCells -Row $Row -State ([string]$Live.Origin) -Hash ([string]$Live.Hash) -Name ([string]$Live.Name) -Index ([string]$Live.Live)
        Set-AT3SpawnDescribeCells -Row $Row -Src $Live -Pad ("L{0:D4}" -f [int][string]$Live.Live)
    } else {
        $Row["TagHex"] = ""
        Set-AT3SpawnLiveCells -Row $Row -State "not in the live level yet - it is written on Confirm" -Hash "" -Name "" -Index ""
        $Row["Location"] = "(added spawns)"
        $Row["ZoneLabel"] = "zone set on Confirm"
        $Row["GroupLabel"] = "(no group)"
        $Row["ScriptShort"] = "(no script)"
        $Row["JobsLabel"] = "(no jobs)"
        foreach ($c in @("SortLoc", "SortGroup", "SortScript", "SortJob")) { $Row[$c] = $last }
    }
    $Row["SortSlot"] = $last
}

# A spawn in the live level that no row of the Spawns Editor accounts for - put
# there by a preset, another tool, or a clone. It is shown so the list matches
# the game, and it is read-only: there is no slot or add row to save an edit to.
function Set-AT3SpawnOutsideCells {
    param($Row, $Live)
    $li = [string]$Live.Live
    $Row["Outside"] = "1"
    $Row["Slot"] = ""
    $Row["Tag"] = [string]$Live.Tag
    $Row["TagHex"] = [string]$Live.Tag
    $Row["Character"] = Format-AT3SpawnCharacter -Hash ([string]$Live.Hash) -Name ([string]$Live.Name)
    foreach ($f in @("X", "Y", "Z", "Yaw")) { $Row[$f] = [string]$Live.$f }
    $Row["Position"] = ("{0}  {1}  {2}" -f $Row["X"], $Row["Y"], $Row["Z"])
    $Row["Job"] = $(if ([string]$Live.Script) { "y" } else { "n" })
    Set-AT3SpawnLiveCells -Row $Row -State ([string]$Live.Origin) -Hash ([string]$Live.Hash) -Name ([string]$Live.Name) -Index $li
    Set-AT3SpawnDescribeCells -Row $Row -Src $Live -Pad ("L{0:D4}" -f [int]$li)
    $Row["SortSlot"] = "zzzzzz|1|{0:D4}" -f [int]$li
}

# A duplicate of a vanilla slot - a "clone" row in spawns_<region>.csv, made by
# [+] with a spawn selected. Once applied, $Live is the record Apply Changes made
# and the row is described from the level like any other. Before that it is
# described from its SOURCE, because that is what it inherits: the source's
# trigger group and script, and its job spots only while it shares the source's
# tag. It sorts directly after its source; its zone comes from its own position
# on Apply.
function Set-AT3SpawnCloneCells {
    param($Row, [int]$Index, $Live, $Source, [string]$TagMode, [string]$CloneOf)
    $after = "zzzzzz|0|c{0:D4}" -f $Index
    $srcSlot = 0
    if ([int]::TryParse($CloneOf, [ref]$srcSlot)) { $after = "{0:D4}c{1:D3}" -f $srcSlot, $Index }
    $Row["JobKey"] = ""
    if ($Live) {
        $Row["TagHex"] = [string]$Live.Tag
        Set-AT3SpawnLiveCells -Row $Row -State ([string]$Live.Origin) -Hash ([string]$Live.Hash) -Name ([string]$Live.Name) -Index ([string]$Live.Live)
        Set-AT3SpawnDescribeCells -Row $Row -Src $Live -Pad $after
    } elseif ($Source) {
        $shared = ($TagMode -ne "own")
        if ($shared) { $Row["TagHex"] = [string]$Source.Tag } else { $Row["TagHex"] = "(its own, minted on Apply)" }
        Set-AT3SpawnLiveCells -Row $Row -State ("not in the live level yet - written on Confirm as a copy of slot " + $CloneOf) -Hash "" -Name "" -Index ""
        Set-AT3SpawnDescribeCells -Row $Row -Src $Source -Pad $after
        if ($shared) {
            $Row["JobKey"] = $CloneOf
        } else {
            $Row["JobsLabel"] = "(no jobs)"
            $Row["SortJob"] = "1|" + $after
        }
    } else {
        $Row["TagHex"] = ""
        Set-AT3SpawnLiveCells -Row $Row -State ("slot " + $CloneOf + " is not in this region's spawn table") -Hash "" -Name "" -Index ""
        foreach ($k in @("Location", "ZoneLabel", "GroupLabel", "ScriptShort", "JobsLabel")) { $Row[$k] = "(unknown source)" }
        foreach ($c in @("SortLoc", "SortGroup", "SortScript", "SortJob")) { $Row[$c] = $after }
    }
    $Row["SortSlot"] = $after
}

function Format-AT3SpawnDetail {
    param($Row, $Jobs)
    $nl = [Environment]::NewLine
    $live = [string]$Row["LiveIndex"]
    $isClone = ([string]$Row["Kind"] -eq "clone")
    if ([string]$Row["New"] -and -not $live -and -not $isClone) {
        return ("Added spawn - not in the live level yet; it is written on Confirm." + $nl +
            "Its zone is read from the records around its position then." + $nl +
            "It is cloned from the region's safe donor with the script severed, so it belongs to no trigger group, runs no script and has no job spots: it is present from level start.")
    }
    $slot = [string]$Row["Slot"]
    $src = [string]$Row["CloneOf"]
    if ([string]$Row["Outside"]) { $head = "Live spawn $live (no Spawns Editor row)" }
    elseif ($isClone -and $live) { $head = "Duplicate of slot $src (live $live)" }
    elseif ($isClone) { $head = "Duplicate of slot $src" }
    elseif ([string]$Row["New"]) { $head = "Added spawn (live $live)" }
    else { $head = "Slot $slot" }
    $t = "{0}   {1}   spawn tag {2}" -f $head, [string]$Row["Character"], [string]$Row["TagHex"]
    if ([string]$Row["Del"]) { $t += "   (marked for deletion)" }
    $t += $nl + "In game    " + [string]$Row["LiveState"]
    if ($isClone) {
        if ([string]$Row["TagMode"] -eq "own") {
            $t += $nl + "Copies     slot $src's trigger group and script. It has its own tag, so none of slot $src's job spots name it, and a script that names slot $src's tag still acts on slot $src."
        } else {
            $t += $nl + "Copies     slot $src's trigger group, script and tag, so slot $src's job spots name it too. Shared tags are untested in game: a region_02a clone once took over its source's cutscene role. Set Clone Tag to 'own' to compare."
        }
    }
    $lh = [string]$Row["LiveHash"]
    $shown = ConvertTo-AT3SpawnHash -Display ([string]$Row["Character"])
    if ($lh -and $shown -and ($lh -ne $shown)) {
        $t += "  - the live level currently has " + [string]$Row["LiveName"] + " (" + $lh + ") here"
    }
    if ([string]$Row["Outside"]) {
        $t += $nl + "           Read-only: nothing in the Spawns Editor's list made it, so the editor cannot change or remove it."
    }
    $t += $nl + "Location   " + [string]$Row["Location"] + "  >  " + [string]$Row["ZoneLabel"]
    if ([string]$Row["GroupHash"]) {
        $gl = [string]$Row["GroupName"]
        if (-not $gl) { $gl = "(name not shipped)" }
        $t += $nl + ("Trigger    group {0} [{1}], shared by {2} spawn(s) in this region. A script releases or hides the whole group by name (MoveOutOfPurgatoryGroup and friends)." -f $gl, [string]$Row["GroupHash"], [string]$Row["GroupSize"])
    } else {
        $t += $nl + "Trigger    no group. A script can still move this spawn by its own tag."
    }
    if ([string]$Row["ScriptName"]) {
        $kind = [string]$Row["ScriptKind"]
        $t += $nl + "Script     " + [string]$Row["ScriptName"] + "  (" + $kind + ")"
    } else {
        $t += $nl + "Script     none attached"
    }
    $list = $null
    $jk = $(if ($slot) { $slot } else { "L" + $live })
    # a duplicate not yet applied borrows its source's job spots while it shares the tag
    if ($isClone -and -not $live) { $jk = [string]$Row["JobKey"] }
    if ($jk -and $Jobs -and $Jobs.ContainsKey($jk)) { $list = $Jobs[$jk] }
    if ($list -and $list.Count -gt 0) {
        $t += $nl + "Jobs       " + $list.Count + " job spot(s) restricted to this spawn:"
        foreach ($j in $list) {
            $short = ConvertTo-AT3ScriptShort -Name ([string]$j.ScriptName) -Hash ([string]$j.Script)
            $jn = [string]$j.Name
            if (-not $jn) { $jn = [string]$j.Job }
            $pts = @(([string]$j.Points) -split '\|' | Where-Object { $_ -and ($_ -notmatch '^point\d+$') })
            $ptxt = ""
            if ($pts.Count -gt 0) {
                $ptxt = "   points: " + (($pts | Select-Object -First 3) -join ", ")
                if ($pts.Count -gt 3) { $ptxt += " (+" + ($pts.Count - 3) + " more)" }
            }
            $t += $nl + ("  - {0}   job {1}   zone {2} {3}{4}" -f $short, $jn, [string]$j.Zone, [string]$j.ZoneName, $ptxt)
        }
    } else {
        $t += $nl + "Jobs       none restricted to this spawn. Spots that name only a character type are listed in spawnjobs_<region>.csv."
    }
    return $t
}

# Hash -> the name the Character dropdown shows, from the region's live catalogue
# (at3catalogue.py). The grid's Character cells MUST be built from this same
# lookup: a DataGridComboBoxColumn only displays a value that is one of its
# items, string for string. The cells used to take the spawntable's
# hand-assigned names (clakker_clerk) while the dropdown took the regenerated
# catalogue's (Townsfolk (745 bytes, ...)), so 148 of region_01's 149 cells
# showed nothing at all.
function Get-AT3SpawnCharacterNames {
    param($Region)
    Use-AT3Catalogue
    $map = @{}
    $p = Join-Path $RegionDataDir "catalogue_$Region.csv"
    if (-not (Test-Path $p)) { return $map }
    foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
        $h = ([string]$r.Hash).ToUpper()
        if ($h) { $map[$h] = [string]$r.Name }
    }
    return $map
}

function Get-AT3SpawnCharacters {
    param($Region)
    $names = Get-AT3SpawnCharacterNames -Region $Region
    $out = @()
    foreach ($h in $names.Keys) { $out += (Format-AT3SpawnCharacter -Hash $h -Name $names[$h]) }
    return @($out | Sort-Object)
}

function ConvertTo-AT3SpawnHash {
    param([string]$Display)
    if ($Display -match '\(([0-9A-Fa-f]{8})\)\s*$') { return $Matches[1].ToUpper() }
    return ""
}

function Get-AT3SpawnBaseline {
    param($Region)
    $map = @{}
    $p = Join-Path $RegionDataDir "spawntable_$Region.csv"
    if (-not (Test-Path $p)) { return $map }
    foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
        $map[[string]$r.Slot] = $r
    }
    return $map
}

function Format-AT3SpawnCharacter {
    param($Hash, $Name)
    $h = ([string]$Hash).ToUpper()
    if ([string]$Name) { return ("{0} ({1})" -f [string]$Name, $h) }
    return ("({0})" -f $h)
}

function Get-AT3SpawnRows {
    param($Region)
    $t = New-Object System.Data.DataTable
    # New marks a spawn that does not exist in vanilla. Donor and TagMode are not
    # shown - they carry apply_spawns' own columns across a save so a hand-edited
    # CSV is not flattened by opening the editor. Everything from TagHex on is
    # read-only catalogue data that organises the grid and is never saved.
    foreach ($c in @("Slot", "Tag", "Character", "X", "Y", "Z", "Position", "Yaw", "Job", "Del", "New", "Donor", "TagMode",
                     "TagHex", "Location", "ZoneLabel", "GroupHash", "GroupName", "GroupSize", "GroupLabel",
                     "ScriptName", "ScriptKind", "ScriptShort", "JobsLabel",
                     "SortLoc", "SortGroup", "SortScript", "SortJob", "SortSlot",
                     "Outside", "LiveState", "LiveHash", "LiveName", "LiveIndex", "Kind", "CloneOf", "JobKey")) {
        [void]$t.Columns.Add($c, [string])
    }
    $base = Get-AT3SpawnBaseline -Region $Region
    # The same names as the Character dropdown, or the cell displays nothing
    # (see Get-AT3SpawnCharacterNames). The spawntable's own names only fill
    # hashes the catalogue does not list.
    $names = @{}
    foreach ($k in $base.Keys) { $names[(([string]$base[$k].Hash).ToUpper())] = [string]$base[$k].Name }
    $catNames = Get-AT3SpawnCharacterNames -Region $Region
    foreach ($h in $catNames.Keys) { $names[$h] = $catNames[$h] }
    $edits = @{}
    $dels = @{}
    $adds = @()
    $clones = @()
    $p = Join-Path $PropDir "spawns_$Region.csv"
    if (Test-Path $p) {
        foreach ($r in @(Import-Csv -LiteralPath $p -ErrorAction SilentlyContinue)) {
            $act = ([string]$r.Action).Trim().ToLower()
            if ($act -eq "add") { $adds += $r; continue }
            # Duplicates of a slot ([+] with a spawn selected), kept in file
            # order - the index the catalogue's EditorClone column refers to.
            # These used to fall through and be dropped by the next save.
            if ($act -eq "clone") { $clones += $r; continue }
            $slot = ([string]$r.Slot).Trim()
            if (-not $slot) { continue }
            if ($act -eq "edit") { $edits[$slot] = $r }
            elseif ($act -eq "delete") { $dels[$slot] = $true }
        }
    }
    foreach ($slot in @($base.Keys | Sort-Object { [int]$_ })) {
        $b = $base[$slot]
        $row = $t.NewRow()
        $row["Slot"] = $slot
        Set-AT3SpawnCatalogueCells -Row $row -Base $b
        if ($dels.ContainsKey($slot)) {
            $row["Tag"] = ""; $row["Character"] = ""; $row["X"] = ""
            $row["Y"] = ""; $row["Z"] = ""; $row["Yaw"] = ""; $row["Job"] = ""
            $row["Position"] = ""
            $row["Del"] = "1"
            $t.Rows.Add($row)
            continue
        }
        $e = $null
        if ($edits.ContainsKey($slot)) { $e = $edits[$slot] }
        $hash = ([string]$b.Hash).ToUpper()
        if ($e -and ([string]$e.Hash)) { $hash = ([string]$e.Hash).ToUpper() }
        $nm = ""
        if ($names.ContainsKey($hash)) { $nm = $names[$hash] }
        $row["Tag"] = [string]$b.Tag
        $row["Character"] = Format-AT3SpawnCharacter -Hash $hash -Name $nm
        foreach ($f in @("X", "Y", "Z", "Yaw")) {
            $v = [string]$b.$f
            if ($e -and ([string]$e.$f)) { $v = [string]$e.$f }
            $row[$f] = $v
        }
        $row["Position"] = ("{0}  {1}  {2}" -f $row["X"], $row["Y"], $row["Z"])
        $row["Job"] = [string]$b.Job
        $row["Del"] = ""
        $row["New"] = ""
        $t.Rows.Add($row)
    }
    # Added spawns after the vanilla list, in the order they were created. The
    # catalogue pairs each with the live record Apply Changes made from it
    # (EditorAdd = its index among the add rows), so an applied add is described
    # from the level like any other spawn.
    $live = @(Get-AT3SpawnLive -Region $Region)
    $liveAdd = @{}
    foreach ($l in $live) {
        if ([string]$l.EditorAdd -ne "") { $liveAdd[[string]$l.EditorAdd] = $l }
    }
    $addIndex = 0
    foreach ($a in $adds) {
        $row = $t.NewRow()
        $lv = $null
        if ($liveAdd.ContainsKey([string]$addIndex)) { $lv = $liveAdd[[string]$addIndex] }
        Set-AT3SpawnNewCells -Row $row -Index $addIndex -Live $lv
        $addIndex++
        $hash = ([string]$a.Hash).ToUpper()
        $anm = ""
        if ($names.ContainsKey($hash)) { $anm = $names[$hash] }
        # a custom character has no baseline name; the live catalogue has one
        if (-not $anm -and $lv -and ([string]$lv.Hash -eq $hash)) { $anm = [string]$lv.Name }
        $row["Slot"] = ""
        $row["Tag"] = "(new)"
        $row["Character"] = Format-AT3SpawnCharacter -Hash $hash -Name $anm
        foreach ($f in @("X", "Y", "Z", "Yaw")) { $row[$f] = [string]$a.$f }
        $row["Position"] = ("{0}  {1}  {2}" -f $row["X"], $row["Y"], $row["Z"])
        # An add always gets a null job - apply_spawns severs it so the clone
        # cannot inherit its donor's scripted role.
        $row["Job"] = "n"
        $row["Del"] = ""
        $row["New"] = "1"
        $row["Donor"] = [string]$a.Donor
        $row["TagMode"] = [string]$a.Tag
        $t.Rows.Add($row)
    }
    # Duplicates, after the adds. Once applied, a clone row's live record
    # (EditorClone = its index among the clone rows) describes it; until then it
    # is described from its source slot. apply_spawns copies the source's BASE
    # record, so the copy is the base character unless the row names a Hash.
    $liveClone = @{}
    foreach ($l in $live) {
        if ([string]$l.EditorClone -ne "") { $liveClone[[string]$l.EditorClone] = $l }
    }
    $cloneIndex = 0
    foreach ($cr in $clones) {
        $row = $t.NewRow()
        $src = ([string]$cr.Slot).Trim()
        $srcBase = $null
        if ($base.ContainsKey($src)) { $srcBase = $base[$src] }
        $lv = $null
        if ($liveClone.ContainsKey([string]$cloneIndex)) { $lv = $liveClone[[string]$cloneIndex] }
        $mode = ([string]$cr.Tag).Trim().ToLower()
        if ($mode -ne "own") { $mode = "shared" }
        $hash = ([string]$cr.Hash).Trim().ToUpper()
        if (-not $hash -and $srcBase) { $hash = ([string]$srcBase.Hash).ToUpper() }
        $cnm = ""
        if ($names.ContainsKey($hash)) { $cnm = $names[$hash] }
        if (-not $cnm -and $lv -and ([string]$lv.Hash -eq $hash)) { $cnm = [string]$lv.Name }
        $row["Slot"] = ""
        $row["Tag"] = "(copy)"
        $row["Character"] = Format-AT3SpawnCharacter -Hash $hash -Name $cnm
        foreach ($f in @("X", "Y", "Z", "Yaw")) { $row[$f] = ([string]$cr.$f).Trim() }
        # a blank Yaw means "the source's rotation" - show what that is
        if (-not [string]$row["Yaw"] -and $srcBase) { $row["Yaw"] = [string]$srcBase.Yaw }
        $row["Position"] = ("{0}  {1}  {2}" -f $row["X"], $row["Y"], $row["Z"])
        $row["Job"] = $(if ($srcBase) { [string]$srcBase.Job } else { "" })
        $row["Del"] = ""
        $row["New"] = "1"
        $row["Kind"] = "clone"
        $row["CloneOf"] = $src
        $row["TagMode"] = $mode
        $row["Donor"] = ""
        Set-AT3SpawnCloneCells -Row $row -Index $cloneIndex -Live $lv -Source $srcBase -TagMode $mode -CloneOf $src
        $t.Rows.Add($row)
        $cloneIndex++
    }

    # Spawns in the live level that neither a slot, an add row nor a clone row
    # accounts for - a preset, another tool. Shown so the list is the game as it
    # is, read-only because there is nothing to save an edit against.
    foreach ($l in $live) {
        if ([string]$l.Slot -ne "" -or [string]$l.EditorAdd -ne "" -or [string]$l.EditorClone -ne "") { continue }
        $row = $t.NewRow()
        Set-AT3SpawnOutsideCells -Row $row -Live $l
        $t.Rows.Add($row)
    }
    $t.AcceptChanges()
    return ,$t
}

function Save-AT3SpawnRows {
    param($Region, $Table, $Baseline)
    if (-not (Test-Path $PropDir)) { [void](New-Item -ItemType Directory -Force -Path $PropDir) }
    $p = Join-Path $PropDir "spawns_$Region.csv"

    # Added spawns are rows in the grid now (New = 1), so they are written from
    # the table like everything else rather than being copied back out of the
    # old file.
    $out = @()
    $newRows = @()
    foreach ($r in $Table.Rows) {
        if ($r.RowState -eq [System.Data.DataRowState]::Deleted) { continue }
        # One Position cell holding "X Y Z", matching the prop editor, so a line
        # from writepos pastes straight in. Split on any run of whitespace or
        # commas and fan the values back out to the X/Y/Z that the rest of this
        # function - and apply_spawns' CSV - still expect.
        $pp = @(([string]$r["Position"]).Trim() -split '[\s,]+' | Where-Object { $_ -ne "" })
        if ($pp.Count -ge 3) { $r["X"] = $pp[0]; $r["Y"] = $pp[1]; $r["Z"] = $pp[2] }
        if ([string]$r["New"]) {
            # A new spawn that was X-ed out simply ceases to exist - there is no
            # vanilla state for it to fall back to.
            if ([string]$r["Del"]) { continue }
            $h = ConvertTo-AT3SpawnHash -Display ([string]$r["Character"])
            if ([string]$r["Kind"] -eq "clone") {
                # A duplicate of a slot. Hash is written only when it retypes the
                # copy - blank means "the source slot's own character", which is
                # what apply_spawns copies.
                $src = [string]$r["CloneOf"]
                if (-not $src) { continue }
                $hv = ""
                if ($h -and $Baseline.ContainsKey($src) -and ($h -ne ([string]$Baseline[$src].Hash).ToUpper())) { $hv = $h }
                $mode = ([string]$r["TagMode"]).Trim().ToLower()
                if ($mode -ne "own") { $mode = "shared" }
                # Yaw only when it differs from the source's: a blank keeps the
                # source's exact rotation, and writing a yaw back would flatten
                # the tilt of the spawns whose rotation is not a pure Z turn.
                $yv = ([string]$r["Yaw"]).Trim()
                $ya = 0.0
                $yb = 0.0
                if ($yv -and $Baseline.ContainsKey($src) -and [double]::TryParse($yv, [ref]$ya) -and
                    [double]::TryParse(([string]$Baseline[$src].Yaw), [ref]$yb) -and ([math]::Abs($ya - $yb) -lt 0.005)) { $yv = "" }
                $newRows += [pscustomobject]@{
                    Action = "clone"; Slot = $src; Hash = $hv
                    X = ([string]$r["X"]).Trim(); Y = ([string]$r["Y"]).Trim()
                    Z = ([string]$r["Z"]).Trim(); Yaw = $yv
                    Donor = ""; Tag = $mode
                }
                continue
            }
            if (-not $h) { continue }
            $newRows += [pscustomobject]@{
                Action = "add"; Slot = ""; Hash = $h
                X = ([string]$r["X"]).Trim(); Y = ([string]$r["Y"]).Trim()
                Z = ([string]$r["Z"]).Trim(); Yaw = ([string]$r["Yaw"]).Trim()
                Donor = ([string]$r["Donor"]).Trim(); Tag = ([string]$r["TagMode"]).Trim()
            }
            continue
        }
        $slot = [string]$r["Slot"]
        if (-not $slot) { continue }
        if (-not $Baseline.ContainsKey($slot)) { continue }
        $b = $Baseline[$slot]
        if ([string]$r["Del"]) {
            $out += [pscustomobject]@{
                Action = "delete"; Slot = $slot; Hash = ""
                X = ""; Y = ""; Z = ""; Yaw = ""; Donor = ""; Tag = ""
            }
            continue
        }
        $hash = ConvertTo-AT3SpawnHash -Display ([string]$r["Character"])
        $hv = ""
        if ($hash -and ($hash -ne (([string]$b.Hash).ToUpper()))) { $hv = $hash }
        $vals = @{}
        foreach ($f in @("X", "Y", "Z", "Yaw")) {
            $vals[$f] = ""
            $cur = ([string]$r[$f]).Trim()
            if (-not $cur) { continue }
            $a = 0.0
            $bv = 0.0
            $okA = [double]::TryParse($cur, [ref]$a)
            $okB = [double]::TryParse(([string]$b.$f), [ref]$bv)
            if (-not $okA) { continue }
            if ($okB -and ([math]::Abs($a - $bv) -lt 0.005)) { continue }
            $vals[$f] = $cur
        }
        $any = $hv -or $vals["X"] -or $vals["Y"] -or $vals["Z"] -or $vals["Yaw"]
        if (-not $any) { continue }
        $out += [pscustomobject]@{
            Action = "edit"; Slot = $slot; Hash = $hv
            X = $vals["X"]; Y = $vals["Y"]; Z = $vals["Z"]; Yaw = $vals["Yaw"]
            Donor = ""; Tag = ""
        }
    }
    foreach ($k in $newRows) { $out += $k }
    if ($out.Count -eq 0) {
        Set-Content -LiteralPath $p -Encoding UTF8 -Value "Action,Slot,Hash,X,Y,Z,Yaw,Donor,Tag"
    } else {
        $out | Export-Csv -LiteralPath $p -NoTypeInformation -Encoding UTF8
    }
    return $out.Count
}

# ---------------------------------------------------------------------------
# Spawn Randomizer  (Spawns Editor -> SPECIAL TOOLS)
# ---------------------------------------------------------------------------
# Two independent sets, which is the whole idea:
#
#   Randomizer Roster   what a spawn may be turned INTO
#   Randomize Into      which spawns are eligible to BE changed
#
# The work is done by ModTools\randomize_spawns.py at Apply Changes, after the
# spawn stage, by overwriting the character hash of records that already exist.
# It never inserts or removes one, so re-applying re-rolls from a clean base
# rather than compounding.

$RandomizerConfigPath = Join-Path $AT3Dir "RandomizerConfig.csv"

$script:AT3RandomizerKeys = @(
    "Enabled",
    "RosterHostiles", "RosterFriendlies", "RosterBosses", "RosterDeathray", "RosterTiny",
    "IntoHostile", "IntoFriendly", "IntoBosses", "IntoProgression",
    "Seed"
)

function Get-AT3RandomizerConfig {
    $cfg = @{
        Enabled = "0"
        RosterHostiles = "1"; RosterFriendlies = "0"; RosterBosses = "0"
        IntoHostile = "1"; IntoFriendly = "0"; IntoBosses = "0"; IntoProgression = "0"
        Seed = ""
    }
    if (Test-Path $RandomizerConfigPath) {
        foreach ($r in @(Import-Csv -LiteralPath $RandomizerConfigPath -ErrorAction SilentlyContinue)) {
            $k = ([string]$r.Key).Trim()
            if ($cfg.ContainsKey($k)) { $cfg[$k] = ([string]$r.Value).Trim() }
        }
    }
    return $cfg
}

function Save-AT3RandomizerConfig {
    param($Config)
    $out = @()
    foreach ($k in $script:AT3RandomizerKeys) {
        $v = ""
        if ($Config.ContainsKey($k)) { $v = [string]$Config[$k] }
        $out += [pscustomobject]@{ Key = $k; Value = $v }
    }
    $out | Export-Csv -LiteralPath $RandomizerConfigPath -NoTypeInformation -Encoding UTF8
}

function New-AT3Check {
    param([string]$Text, [string]$Tip, [bool]$Checked)
    $c = New-Object System.Windows.Controls.CheckBox
    $c.Content = $Text
    $c.IsChecked = $Checked
    $c.Margin = New-Object System.Windows.Thickness 0,0,0,9
    $c.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $c.FontSize = 12
    $c.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#E8D9B5")
    if ($Tip) { $c.ToolTip = $Tip }
    return $c
}

# Sits directly beneath a checkbox, indented under its label, for warnings that
# belong on the face of the window rather than hidden in a tooltip.
function New-AT3CheckNote {
    param([string]$Text)
    $t = New-Object System.Windows.Controls.TextBlock
    $t.Text = $Text
    $t.TextWrapping = "Wrap"
    $t.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $t.FontStyle = [System.Windows.FontStyles]::Italic
    $t.FontSize = 10.5
    $t.Foreground = (New-Object System.Windows.Media.BrushConverter).ConvertFromString("#A88F63")
    $t.Margin = New-Object System.Windows.Thickness 22,-4,0,10
    return $t
}

function Show-AT3SpawnRandomizer {
    $conv = New-Object System.Windows.Media.BrushConverter
    $cfg = Get-AT3RandomizerConfig
    $isOn = { param($v) return (@("1", "true", "yes", "y", "on") -contains ([string]$v).ToLower()) }

    $w = New-AT3Panel -Title "Spawn Randomizer" -Width 780 -Height 520 -Accent "blue"
    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 16
    $w.Content = $root

    $disc = New-Object System.Windows.Controls.TextBlock
    $disc.Text = "The spawn randomizer will randomly replace enabled spawn instances across the game. Experimental"
    $disc.TextWrapping = "Wrap"
    $disc.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $disc.FontSize = 12
    $disc.Foreground = $conv.ConvertFromString("#D98A6A")
    $disc.Margin = New-Object System.Windows.Thickness 0,0,0,14
    [void][System.Windows.Controls.DockPanel]::SetDock($disc, "Top")
    [void]$root.Children.Add($disc)

    $topRow = New-Object System.Windows.Controls.StackPanel
    $topRow.Orientation = "Horizontal"
    $topRow.Margin = New-Object System.Windows.Thickness 0,0,0,16
    [void][System.Windows.Controls.DockPanel]::SetDock($topRow, "Top")
    [void]$root.Children.Add($topRow)

    $enable = New-AT3Check -Text "Enable Randomizer" -Checked (& $isOn $cfg.Enabled) `
        -Tip "When off, Confirm leaves every spawn exactly as the Spawns Editor left it."
    $enable.FontSize = 13
    $enable.FontWeight = [System.Windows.FontWeights]::Bold
    $enable.Margin = New-Object System.Windows.Thickness 0,0,26,0
    $enable.VerticalAlignment = "Center"
    [void]$topRow.Children.Add($enable)

    # SEED. Same seed + same settings = the same world, every time, so a run can
    # be handed to another player. Leave it blank to roll something new on each
    # Apply Changes - one is still generated and reported in the feedback panel,
    # so a roll you liked can be written down afterwards.
    $sLbl = New-Object System.Windows.Controls.TextBlock
    $sLbl.Text = "Seed"
    $sLbl.VerticalAlignment = "Center"
    $sLbl.Margin = New-Object System.Windows.Thickness 0,0,8,0
    $sLbl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $sLbl.FontSize = 12
    $sLbl.Foreground = $conv.ConvertFromString("#E8D9B5")
    [void]$topRow.Children.Add($sLbl)

    $seedBox = New-Object System.Windows.Controls.TextBox
    $seedBox.Width = 170
    $seedBox.Height = 22
    $seedBox.VerticalAlignment = "Center"
    $seedBox.VerticalContentAlignment = "Center"
    $seedBox.Text = [string]$cfg.Seed
    $seedBox.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $seedBox.Background = $conv.ConvertFromString("#2A1F16")
    $seedBox.Foreground = $conv.ConvertFromString("#F2E4C4")
    $seedBox.CaretBrush = $conv.ConvertFromString("#F2E4C4")
    $seedBox.BorderBrush = $conv.ConvertFromString("#4A3524")
    $seedBox.ToolTip = "Type a seed to replay someone else's run exactly - the same seed with the same settings produces the same world. Leave blank to roll a new one each time; the seed used is reported after Confirm."
    [void]$topRow.Children.Add($seedBox)

    $cols = New-Object System.Windows.Controls.Grid
    foreach ($i in @(1, 1)) {
        $cd = New-Object System.Windows.Controls.ColumnDefinition
        $cd.Width = New-Object System.Windows.GridLength($i, [System.Windows.GridUnitType]::Star)
        [void]$cols.ColumnDefinitions.Add($cd)
    }
    [void]$root.Children.Add($cols)

    # ---------------- left: what may APPEAR ----------------
    $left = New-Object System.Windows.Controls.StackPanel
    $left.Margin = New-Object System.Windows.Thickness 0,0,12,0
    [void]$cols.Children.Add($left)
    [System.Windows.Controls.Grid]::SetColumn($left, 0)
    [void]$left.Children.Add((New-AT3Header "---- RANDOMIZER ROSTER ----" -Accent "blue"))
    [void]$left.Children.Add((New-AT3Note "Which character hashes are eligible to appear in randomization. Drawn from each region's own library - a character that region does not bundle would crash the level."))

    $rHost = New-AT3Check -Text "Hostiles" -Checked (& $isOn $cfg.RosterHostiles) `
        -Tip "Enemy characters may be rolled in."
    $rFrnd = New-AT3Check -Text "Friendlies" -Checked (& $isOn $cfg.RosterFriendlies) `
        -Tip "Townsfolk and other non-hostile characters may be rolled in."
    $rBoss = New-AT3Check -Text "Bosses" -Checked (& $isOn $cfg.RosterBosses) `
        -Tip "Outlawbosses, gloktigi and armoredgloktigi, shocktanks, castaraider, and the bounty bosses (Jo Momma, Meagly McGraw, Patrack Palooka, Lefty Lugnutz, Fatty McBoomBoom, Xplosives McGee, Tiny) may be rolled in. Sekto himself is never rolled in - he is the endgame encounter and is wired to his own scripted setup."
    $rRay = New-AT3Check -Text "Sekto's Weapon" -Checked (& $isOn $cfg.RosterDeathray) `
        -Tip "Its own switch rather than part of Bosses, and it works whether or not Bosses is ticked."
    $rTiny = New-AT3Check -Text "Tiny" -Checked (& $isOn $cfg.RosterTiny) `
        -Tip "Its own switch rather than part of Bosses, and it works whether or not Bosses is ticked."
    foreach ($c in @($rHost, $rFrnd, $rBoss)) { [void]$left.Children.Add($c) }
    [void]$left.Children.Add($rRay)
    [void]$left.Children.Add((New-AT3CheckNote "Instances of Sekto's Weapon are invincible and large. Spawns may block progression."))
    [void]$left.Children.Add($rTiny)
    [void]$left.Children.Add((New-AT3CheckNote "Tiny has been known to crash the game when too many instances of him are called. If your game crashes when trying to enter Buzzardton, either uncheck this box or change your seed."))

    # ---------------- right: what may BE CHANGED ----------------
    $right = New-Object System.Windows.Controls.StackPanel
    $right.Margin = New-Object System.Windows.Thickness 12,0,0,0
    [void]$cols.Children.Add($right)
    [System.Windows.Controls.Grid]::SetColumn($right, 1)
    [void]$right.Children.Add((New-AT3Header "---- RANDOMIZE INTO: ----" -Accent "blue"))
    [void]$right.Children.Add((New-AT3Note "Which spawns are eligible to be replaced, judged by what the spawn is in VANILLA."))

    $iFrnd = New-AT3Check -Text "Randomize Friendly NPC Spawns?" -Checked (& $isOn $cfg.IntoFriendly) `
        -Tip "Enables randomization of spawns that are for non-hostile hashes in vanilla."
    $iHost = New-AT3Check -Text "Randomize Hostile NPC Spawns?" -Checked (& $isOn $cfg.IntoHostile) `
        -Tip "Enables randomization of spawns that are for hostile hashes in vanilla."
    $iBoss = New-AT3Check -Text "Randomize Boss Spawns?" -Checked (& $isOn $cfg.IntoBosses) `
        -Tip "Enables randomization for outlawbosses, gloktigi and armoredgloktigi, Sekto and his deathray, shocktanks, and the bounty bosses. NOTE: castaraider is a boss but every instance of him is progression-necessary, so his spawns follow the progression box, not this one."
    $iProg = New-AT3Check -Text "Randomize Progression-Necessary NPC Spawns?" -Checked (& $isOn $cfg.IntoProgression) `
        -Tip ("Enables randomization of the characters the game needs you to meet: Blisterz Booty (00), Vykker Doc (01), " +
              "native rebel hurt (04), native rebel leader (04, 05), clakker clerk (01, 02, 03), Sekto (06), " +
              "Sekto's deathray (06), sewer worker (02), Skycart Joe (03), clakker sleghunter (03), " +
              "clakker bargekeeper (03), castaraider (02a, 03). " +
              "These are governed only by this box - they are never touched by the friendly, hostile or boss settings.")
    $iProg.Foreground = $conv.ConvertFromString("#D98A6A")
    foreach ($c in @($iFrnd, $iHost, $iBoss, $iProg)) { [void]$right.Children.Add($c) }

    $cfm = Add-AT3ConfirmBar -Window $w
    [void]$w.Add_Closed({
        if (-not $cfm.Ok) { return }
        try {
            $save = @{
                Enabled = $(if ($enable.IsChecked) { "1" } else { "0" })
                RosterHostiles = $(if ($rHost.IsChecked) { "1" } else { "0" })
                RosterFriendlies = $(if ($rFrnd.IsChecked) { "1" } else { "0" })
                RosterBosses = $(if ($rBoss.IsChecked) { "1" } else { "0" })
                RosterDeathray = $(if ($rRay.IsChecked) { "1" } else { "0" })
                RosterTiny = $(if ($rTiny.IsChecked) { "1" } else { "0" })
                IntoFriendly = $(if ($iFrnd.IsChecked) { "1" } else { "0" })
                IntoHostile = $(if ($iHost.IsChecked) { "1" } else { "0" })
                IntoBosses = $(if ($iBoss.IsChecked) { "1" } else { "0" })
                IntoProgression = $(if ($iProg.IsChecked) { "1" } else { "0" })
                Seed = ([string]$seedBox.Text).Trim()
            }
            Save-AT3RandomizerConfig -Config $save
        } catch { }
    }.GetNewClosure())

    [void]$w.ShowDialog()
    if ($cfm.Ok) { Invoke-AT3Apply }
}

function Show-AT3SpawnsEditor {
    $w = New-AT3Panel -Title "Spawns Editor" -Width 1440 -Height 840 -Accent "blue"
    $conv = New-Object System.Windows.Media.BrushConverter

    # The Zone, Trigger Group, Script and Jobs columns come from the spawn
    # catalogue. It is cached against the level and blockmap it reads, so this
    # costs one python start when nothing changed - and it cannot be stale after
    # a character build renamed something.
    [void](Update-AT3SpawnCatalogue)

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = New-Object System.Windows.Thickness 14
    $w.Content = $root

    # ---------------- top bar: region + special tools ----------------
    $bar = New-Object System.Windows.Controls.DockPanel
    [void][System.Windows.Controls.DockPanel]::SetDock($bar, "Top")
    [void]$root.Children.Add($bar)

    $rl = New-Object System.Windows.Controls.TextBlock
    $rl.Text = "Region"
    $rl.Width = 55
    $rl.VerticalAlignment = "Center"
    $rl.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $rl.Foreground = $conv.ConvertFromString("#E8D9B5")
    [void]$bar.Children.Add($rl)

    $cmb = New-Object System.Windows.Controls.ComboBox
    $cmb.Height = 24
    $cmb.Width = 260
    $cmb.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $cmb.Background = $conv.ConvertFromString("#2A1F16")
    $cmb.Foreground = $conv.ConvertFromString("#F2E4C4")
    $cmb.DisplayMemberPath = "Display"
    # Only regions that actually have a spawn table - `utility` has no level.
    foreach ($r in (Get-AT3Regions)) {
        if (Test-Path (Join-Path $RegionDataDir ("spawntable_" + $r.Id + ".csv"))) { [void]$cmb.Items.Add($r) }
    }
    [void]$bar.Children.Add($cmb)

    # [+] DUPLICATES THE SELECTED SPAWN - a clone row that keeps its source's
    # trigger group, script and (Clone Tag "shared") tag and job spots, placed 2
    # units along X. With nothing selected it adds a new spawn as before: the
    # region's confirmed-working donor (SAFE_SLOT in apply_spawns), retyped, at
    # 0,0,0 / yaw 0 - see the note under the grid about Z.
    $addBtn = New-Object System.Windows.Controls.Button
    $addBtn.Content = [string][char]0x002B
    $addBtn.Width = 26
    $addBtn.Height = 24
    $addBtn.Margin = New-Object System.Windows.Thickness 10,0,0,0
    $addBtn.Padding = New-Object System.Windows.Thickness 0
    $addBtn.FontSize = 15
    $addBtn.FontWeight = [System.Windows.FontWeights]::Bold
    $addBtn.ToolTip = ("Duplicate the selected spawn: the copy keeps its trigger group and script, and with Clone Tag 'shared' its tag and job spots. It is placed 2 units along X - set its position before Confirm." +
        [Environment]::NewLine + "With nothing selected (Ctrl+click a row to clear the selection), adds a new spawn at 0, 0, 0.")
    $addBtn.Background = $conv.ConvertFromString("#26402A")
    $addBtn.Foreground = $conv.ConvertFromString("#CFE8C0")
    $addBtn.BorderBrush = $conv.ConvertFromString("#5E8C4A")
    [void]$bar.Children.Add($addBtn)

    $tools = New-Object System.Windows.Controls.ComboBox
    $tools.Height = 24
    $tools.Width = 190
    $tools.Margin = New-Object System.Windows.Thickness 14,0,0,0
    $tools.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $tools.Background = $conv.ConvertFromString("#2A1F16")
    $tools.Foreground = $conv.ConvertFromString("#F2E4C4")
    [void]$tools.Items.Add("SPECIAL TOOLS")
    [void]$tools.Items.Add("Spawn Randomizer")
    $tools.SelectedIndex = 0
    [void]$bar.Children.Add($tools)

    # ORGANIZE BY. Every option is a fact read from the vanilla level, so a row
    # keeps its place however its character or position is edited:
    #   Location         area file, then zone by the level's own zone name
    #   Trigger group    the group a script releases or hides as one
    #   Attached script  the script on the spawn record itself
    #   Job              what the job spots restricted to this spawn run
    $ol = New-Object System.Windows.Controls.TextBlock
    $ol.Text = "Organize by"
    $ol.VerticalAlignment = "Center"
    $ol.Margin = New-Object System.Windows.Thickness 18,0,8,0
    $ol.FontFamily = New-Object System.Windows.Media.FontFamily "Georgia"
    $ol.Foreground = $conv.ConvertFromString("#E8D9B5")
    [void]$bar.Children.Add($ol)

    $org = New-Object System.Windows.Controls.ComboBox
    $org.Height = 24
    $org.Width = 170
    $org.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Left
    $org.Background = $conv.ConvertFromString("#2A1F16")
    $org.Foreground = $conv.ConvertFromString("#F2E4C4")
    foreach ($o in @("Location", "Trigger group", "Attached script", "Job", "Spawn order")) { [void]$org.Items.Add($o) }
    $org.SelectedIndex = 0
    $org.ToolTip = "Location: area file, then zone.  Trigger group: spawns a script releases or hides together.  Attached script: the script on the spawn itself.  Job: what the job spots restricted to the spawn run."
    [void]$bar.Children.Add($org)

    $hdr = New-AT3Header "---- SPAWNS ----" -Accent "blue"
    [void][System.Windows.Controls.DockPanel]::SetDock($hdr, "Top")
    [void]$root.Children.Add($hdr)

    $note = New-AT3Note "Grouped by where each spawn stands, what releases it or what drives it - all read from the vanilla level, so a row keeps its place when you edit it. Character, position and yaw are editable; changes save as a diff and take effect on Confirm. The arrow restores a row to vanilla; on an added spawn it removes the row. A new spawn placed at floor level falls THROUGH the floor - it is created and shows on the radar, but you never see it, so give Z a few units of clearance."
    [void][System.Windows.Controls.DockPanel]::SetDock($note, "Top")
    [void]$root.Children.Add($note)

    # ---------------- details of the selected spawn ----------------
    # Docked before the grid so the grid takes whatever height is left.
    $detailHint = "Select a spawn to see where it stands, what releases it and what drives it."
    $detail = New-Object System.Windows.Controls.TextBox
    $detail.IsReadOnly = $true
    $detail.Height = 132
    $detail.Margin = New-Object System.Windows.Thickness 0,8,0,0
    $detail.TextWrapping = [System.Windows.TextWrapping]::Wrap
    $detail.VerticalScrollBarVisibility = "Auto"
    $detail.FontFamily = New-Object System.Windows.Media.FontFamily "Consolas"
    $detail.FontSize = 11.5
    $detail.Background = $conv.ConvertFromString("#120D0A")
    $detail.Foreground = $conv.ConvertFromString("#E8D9B5")
    $detail.BorderBrush = $conv.ConvertFromString("#2A3145")
    $detail.Text = $detailHint
    [void][System.Windows.Controls.DockPanel]::SetDock($detail, "Bottom")
    [void]$root.Children.Add($detail)

    # ---------------- the grid ----------------
    $g = New-Object System.Windows.Controls.DataGrid
    $g.AutoGenerateColumns = $false
    $g.CanUserAddRows = $false
    $g.CanUserDeleteRows = $false
    $g.CanUserSortColumns = $false
    $g.HeadersVisibility = "Column"
    $g.GridLinesVisibility = "Horizontal"
    $g.Background = $conv.ConvertFromString("#120D0A")
    $g.RowBackground = $conv.ConvertFromString("#1B1410")
    $g.Foreground = $conv.ConvertFromString("#E8D9B5")
    $g.BorderBrush = $conv.ConvertFromString("#2A3145")
    $g.VerticalScrollBarVisibility = "Auto"
    $g.HorizontalScrollBarVisibility = "Auto"
    $g.SelectionMode = [System.Windows.Controls.DataGridSelectionMode]::Single

    # The spawn tag moved to the details pane to make room for the zone, group,
    # script and job columns; it is still shown for the selected spawn.
    $c = New-Object System.Windows.Controls.DataGridTextColumn
    $c.Header = "Spawn"
    $c.IsReadOnly = $true
    $c.Binding = New-Object System.Windows.Data.Binding "Slot"
    $c.Width = New-Object System.Windows.Controls.DataGridLength 50
    [void]$g.Columns.Add($c)

    # Character comes from the region's OWN catalogue. A hash whose assets are
    # not bundled in this region resolves but has nothing to draw - forcing a
    # foreign type crashes the level - so the list is deliberately per-region.
    $cc = New-Object System.Windows.Controls.DataGridComboBoxColumn
    $cc.Header = "Character"
    $cc.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.GridUnitType]::Star)
    $cc.MinWidth = 200
    $bind = New-Object System.Windows.Data.Binding "Character"
    $bind.Mode = [System.Windows.Data.BindingMode]::TwoWay
    $bind.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
    $cc.SelectedItemBinding = $bind
    $es = New-Object System.Windows.Style([System.Windows.Controls.ComboBox])
    [void]$es.Setters.Add((New-Object System.Windows.Setter([System.Windows.Controls.Control]::BackgroundProperty, $conv.ConvertFromString("#2A1F16"))))
    [void]$es.Setters.Add((New-Object System.Windows.Setter([System.Windows.Controls.Control]::ForegroundProperty, $conv.ConvertFromString("#F2E4C4"))))
    $cc.EditingElementStyle = $es
    [void]$g.Columns.Add($cc)

    foreach ($spec in @(
        @{ H = "Position (X Y Z)"; B = "Position"; W = 170 }
        @{ H = "Yaw"; B = "Yaw"; W = 56 }
    )) {
        $c = New-Object System.Windows.Controls.DataGridTextColumn
        $c.Header = $spec.H
        $b2 = New-Object System.Windows.Data.Binding $spec.B
        $b2.Mode = [System.Windows.Data.BindingMode]::TwoWay
        $b2.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
        $c.Binding = $b2
        $c.Width = New-Object System.Windows.Controls.DataGridLength $spec.W
        [void]$g.Columns.Add($c)
    }

    # Read-only facts about the slot. This used to be a "Job?" y/n column, but
    # the hash it read (+92) is the spawn's attached SCRIPT; job spots are
    # separate records that name the spawn by its tag (see spawn_catalog.py).
    foreach ($spec in @(
        @{ H = "Zone"; B = "ZoneLabel"; W = 190 }
        @{ H = "Trigger Group"; B = "GroupLabel"; W = 140 }
        @{ H = "Script"; B = "ScriptShort"; W = 190 }
        @{ H = "Jobs"; B = "JobsLabel"; W = 200 }
    )) {
        $c = New-Object System.Windows.Controls.DataGridTextColumn
        $c.Header = $spec.H
        $c.IsReadOnly = $true
        $c.Binding = New-Object System.Windows.Data.Binding $spec.B
        $c.Width = New-Object System.Windows.Controls.DataGridLength $spec.W
        [void]$g.Columns.Add($c)
    }

    # CLONE TAG - editable on a duplicate row only (see BeginningEdit below).
    #   shared  the copy keeps its source's tag, so the source's job spots name it too
    #   own     a fresh tag is minted on Apply: same trigger group and script, no job spots
    $tagCol = New-Object System.Windows.Controls.DataGridComboBoxColumn
    $tagCol.Header = "Clone Tag"
    $tagCol.Width = New-Object System.Windows.Controls.DataGridLength 86
    $tagCol.ItemsSource = @("shared", "own")
    $tagBind = New-Object System.Windows.Data.Binding "TagMode"
    $tagBind.Mode = [System.Windows.Data.BindingMode]::TwoWay
    $tagBind.UpdateSourceTrigger = [System.Windows.Data.UpdateSourceTrigger]::PropertyChanged
    $tagCol.SelectedItemBinding = $tagBind
    $tagCol.EditingElementStyle = $es
    [void]$g.Columns.Add($tagCol)

    $revXaml = '<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">' +
        '<Button Content="&#x21A9;" Width="26" Height="20" Padding="0" FontSize="12" ToolTip="Restore this spawn to vanilla" ' +
        'Background="#26402A" Foreground="#CFE8C0" BorderBrush="#5E8C4A"/></DataTemplate>'
    $rev = New-Object System.Windows.Controls.DataGridTemplateColumn
    $rev.Header = ""
    $rev.Width = New-Object System.Windows.Controls.DataGridLength 34
    $rev.CellTemplate = [Windows.Markup.XamlReader]::Parse($revXaml)
    [void]$g.Columns.Add($rev)

    $delXaml = '<DataTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">' +
        '<Button Content="&#x2716;" Width="26" Height="20" Padding="0" FontSize="12" ToolTip="Delete this spawn" ' +
        'Background="#4A2A22" Foreground="#E8C9A0" BorderBrush="#8A5A3B"/></DataTemplate>'
    $del = New-Object System.Windows.Controls.DataGridTemplateColumn
    $del.Header = ""
    $del.Width = New-Object System.Windows.Controls.DataGridLength 34
    $del.CellTemplate = [Windows.Markup.XamlReader]::Parse($delXaml)
    [void]$g.Columns.Add($del)

    Set-AT3GridEditStyle -Grid $g

    # Collapsible group headers: the group's name and how many rows it holds.
    # Nested groupings (area, then zone) reuse the same style one level in.
    $gsXaml = '<GroupStyle xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">' +
        '<GroupStyle.ContainerStyle><Style TargetType="{x:Type GroupItem}"><Setter Property="Template"><Setter.Value>' +
        '<ControlTemplate TargetType="{x:Type GroupItem}">' +
        '<Expander IsExpanded="True" Background="#1F1712" BorderBrush="#2A3145" BorderThickness="0,0,0,1" Margin="0,1,0,0">' +
        '<Expander.Header><StackPanel Orientation="Horizontal">' +
        '<TextBlock Text="{Binding Name}" FontFamily="Georgia" FontWeight="Bold" Foreground="#7FA6E8"/>' +
        '<TextBlock Text="{Binding ItemCount}" Margin="10,0,0,0" FontFamily="Georgia" FontStyle="Italic" Foreground="#8A7A5C"/>' +
        '</StackPanel></Expander.Header>' +
        '<ItemsPresenter Margin="14,0,0,0"/>' +
        '</Expander></ControlTemplate></Setter.Value></Setter></Style></GroupStyle.ContainerStyle></GroupStyle>'
    try { [void]$g.GroupStyle.Add([Windows.Markup.XamlReader]::Parse($gsXaml)) } catch { }
    [void]$root.Children.Add($g)

    $state = @{ Region = $null; Table = $null; Base = @{}; Chars = @(); Jobs = @{} }

    [void]$g.AddHandler(
        [System.Windows.Controls.Button]::ClickEvent,
        [System.Windows.RoutedEventHandler]{
            param($sender, $e)
            try {
                $b = $e.OriginalSource
                if (-not ($b -is [System.Windows.Controls.Button])) { return }
                $view = $b.DataContext
                if (-not ($view -is [System.Data.DataRowView])) { return }
                $row = $view.Row
                # a live spawn no editor row made has nothing to revert or delete
                if ([string]$row["Outside"]) { return }
                $slot = [string]$row["Slot"]
                $content = [string]$b.Content
                if ($content -eq [string][char]0x2716 -or $content -eq [string][char]0x21A9) {
                    # A spawn that does not exist in vanilla has nothing to
                    # revert TO, so both buttons simply remove the row.
                    if ([string]$row["New"]) { $row.Delete(); return }
                }
                if ($content -eq [string][char]0x2716) {
                    # Blank every value but keep Slot, so the row stays
                    # identifiable and the revert arrow still has a target.
                    foreach ($f in @("Tag", "Character", "X", "Y", "Z", "Yaw", "Job")) { $row[$f] = "" }
                    $row["Del"] = "1"
                } elseif ($content -eq [string][char]0x21A9) {
                    if ($state.Base.ContainsKey($slot)) {
                        $bs = $state.Base[$slot]
                        $row["Tag"] = [string]$bs.Tag
                        # the dropdown's name for the hash, or the restored cell shows blank
                        $bn = [string]$bs.Name
                        $bh = ([string]$bs.Hash).ToUpper()
                        if ($state.Names -and $state.Names.ContainsKey($bh)) { $bn = [string]$state.Names[$bh] }
                        $row["Character"] = Format-AT3SpawnCharacter -Hash $bh -Name $bn
                        foreach ($f in @("X", "Y", "Z", "Yaw")) { $row[$f] = [string]$bs.$f }
                        $row["Job"] = [string]$bs.Job
                        $row["Del"] = ""
                    }
                } else { return }
            } catch { }
        }.GetNewClosure())

    # Sort the rows into the chosen order, then group on the same keys. Sorting
    # first is what keeps every group contiguous and puts added spawns last.
    $applyOrg = {
        try {
            if (-not $state.Table) { return }
            try { [void]$g.CommitEdit([System.Windows.Controls.DataGridEditingUnit]::Row, $true) } catch { }
            $mode = [string]$org.SelectedItem
            $sort = "SortSlot"
            $keys = @()
            if ($mode -eq "Location") { $sort = "SortLoc"; $keys = @("Location", "ZoneLabel") }
            elseif ($mode -eq "Trigger group") { $sort = "SortGroup"; $keys = @("GroupLabel") }
            elseif ($mode -eq "Attached script") { $sort = "SortScript"; $keys = @("ScriptShort") }
            elseif ($mode -eq "Job") { $sort = "SortJob"; $keys = @("JobsLabel") }
            $state.Table.DefaultView.Sort = $sort
            $view = [System.Windows.Data.CollectionViewSource]::GetDefaultView($g.ItemsSource)
            if ($view -and $view.CanGroup) {
                $view.GroupDescriptions.Clear()
                foreach ($k in $keys) {
                    [void]$view.GroupDescriptions.Add((New-Object System.Windows.Data.PropertyGroupDescription $k))
                }
            }
        } catch { }
    }.GetNewClosure()

    [void]$g.Add_SelectionChanged({
        try {
            $v = $g.SelectedItem
            if ($v -is [System.Data.DataRowView]) {
                $detail.Text = Format-AT3SpawnDetail -Row $v.Row -Jobs $state.Jobs
            }
        } catch { }
    }.GetNewClosure())

    # A live spawn that no editor row made cannot be edited: there is no slot or
    # add row to save the change against. Clone Tag means something only on a
    # duplicate row, so it is locked everywhere else.
    [void]$g.Add_BeginningEdit({
        param($sender, $e)
        try {
            $v = $e.Row.Item
            if (-not ($v -is [System.Data.DataRowView])) { return }
            if ([string]$v.Row["Outside"]) { $e.Cancel = $true; return }
            if ($e.Column -eq $tagCol -and [string]$v.Row["Kind"] -ne "clone") { $e.Cancel = $true }
        } catch { }
    }.GetNewClosure())

    $load = {
        param($id)
        try {
            if ($state.Region -and $state.Table) {
                [void]$g.CommitEdit([System.Windows.Controls.DataGridEditingUnit]::Row, $true)
                [void](Save-AT3SpawnRows -Region $state.Region -Table $state.Table -Baseline $state.Base)
            }
        } catch { }
        # Re-read the live level every time a region is shown - it changes
        # between visits (Apply Changes, presets, other tools).
        [void](Update-AT3SpawnCatalogue -Region $id)
        $state.Region = $id
        $state.Base = Get-AT3SpawnBaseline -Region $id
        $state.Names = Get-AT3SpawnCharacterNames -Region $id
        $state.Jobs = Get-AT3SpawnJobs -Region $id
        $state.Table = Get-AT3SpawnRows -Region $id
        # Switching a duplicate's Clone Tag changes what it inherits - its tag,
        # and with it the source's job spots - so its described cells and the
        # details pane follow the choice at once rather than after a reload. An
        # applied duplicate is described from the level and is left alone.
        $tbl = $state.Table
        $tbl.Add_ColumnChanged({
            param($s2, $ce)
            try {
                if ($ce.Column.ColumnName -ne "TagMode") { return }
                $cr = $ce.Row
                if ([string]$cr["Kind"] -ne "clone" -or [string]$cr["LiveIndex"]) { return }
                $ix = 0
                if ([string]$cr["SortSlot"] -match 'c(\d+)$') { $ix = [int]$Matches[1] }
                $src = [string]$cr["CloneOf"]
                $sb = $null
                if ($state.Base.ContainsKey($src)) { $sb = $state.Base[$src] }
                Set-AT3SpawnCloneCells -Row $cr -Index $ix -Live $null -Source $sb -TagMode ([string]$cr["TagMode"]) -CloneOf $src
                $sel = $g.SelectedItem
                if ($sel -is [System.Data.DataRowView] -and $sel.Row -eq $cr) {
                    $detail.Text = Format-AT3SpawnDetail -Row $cr -Jobs $state.Jobs
                }
            } catch { }
        }.GetNewClosure())
        # A cell only displays a value that is one of the dropdown's items. A
        # hash the region's catalogue does not list - a custom character built
        # elsewhere, a preset retype - would otherwise show blank, hiding the
        # very character that spawns there, so every value the grid holds joins
        # the list.
        $items = New-Object System.Collections.ArrayList
        foreach ($ch in @(Get-AT3SpawnCharacters -Region $id)) { [void]$items.Add($ch) }
        foreach ($tr in $state.Table.Rows) {
            $v = [string]$tr["Character"]
            if ($v -and -not $items.Contains($v)) { [void]$items.Add($v) }
        }
        $state.Chars = @($items | Sort-Object)
        $cc.ItemsSource = $state.Chars
        $g.ItemsSource = $state.Table.DefaultView
        $detail.Text = $detailHint
        & $applyOrg
    }.GetNewClosure()

    [void]$org.Add_SelectionChanged({
        try { & $applyOrg } catch { }
    }.GetNewClosure())

    [void]$addBtn.Add_Click({
        try {
            if (-not $state.Table) { return }
            [void]$g.CommitEdit([System.Windows.Controls.DataGridEditingUnit]::Row, $true)

            # DUPLICATE THE SELECTED SPAWN. A vanilla slot or a duplicate becomes a
            # clone row: the copy keeps its source's trigger group and script and,
            # with Clone Tag "shared" (the default), its tag and job spots too. An
            # added spawn is copied as another add. The copy lands 2 units along X
            # from its source, at the source's height and facing - move it there.
            $sel = $g.SelectedItem
            if ($sel -is [System.Data.DataRowView]) {
                $sr = $sel.Row
                if ([string]$sr["Outside"]) {
                    Show-AT3Notice -Title "Duplicate spawn" -Text ("This spawn is in the live level, but no row of the Spawns Editor made it, so there is nothing here to copy it from." + [Environment]::NewLine + [Environment]::NewLine + "Select a vanilla spawn, a duplicate or an added spawn.")
                    return
                }
                $inv = [System.Globalization.CultureInfo]::InvariantCulture
                $num = [System.Globalization.NumberStyles]::Float
                $isClone = ([string]$sr["Kind"] -eq "clone")
                $isAdd = ([string]$sr["New"] -and -not $isClone)
                $src = $(if ($isClone) { [string]$sr["CloneOf"] } else { [string]$sr["Slot"] })
                $bs = $null
                if ($src -and $state.Base.ContainsKey($src)) { $bs = $state.Base[$src] }
                if (-not $isAdd -and -not $bs) { return }
                # the Position cell holds any unsaved move; a deleted slot's cells
                # are blank, so it falls back to its vanilla values
                $xyz = @(([string]$sr["Position"]).Trim() -split '[\s,]+' | Where-Object { $_ -ne "" })
                if ($xyz.Count -lt 3 -and $bs) { $xyz = @([string]$bs.X, [string]$bs.Y, [string]$bs.Z) }
                $v = @(0.0, 0.0, 0.0)
                for ($i = 0; $i -lt 3; $i++) {
                    $d0 = 0.0
                    if ($i -lt $xyz.Count -and [double]::TryParse([string]$xyz[$i], $num, $inv, [ref]$d0)) { $v[$i] = $d0 }
                }
                $v[0] = $v[0] + 2.0
                $row = $state.Table.NewRow()
                $row["X"] = $v[0].ToString("0.##", $inv)
                $row["Y"] = $v[1].ToString("0.##", $inv)
                $row["Z"] = $v[2].ToString("0.##", $inv)
                $row["Position"] = ("{0}  {1}  {2}" -f $row["X"], $row["Y"], $row["Z"])
                $yaw = ([string]$sr["Yaw"]).Trim()
                if (-not $yaw -and $bs) { $yaw = [string]$bs.Yaw }
                $row["Yaw"] = $yaw
                $ch = [string]$sr["Character"]
                if (-not $ch -and $bs) {
                    $bh = ([string]$bs.Hash).ToUpper()
                    $bn = [string]$bs.Name
                    if ($state.Names -and $state.Names.ContainsKey($bh)) { $bn = [string]$state.Names[$bh] }
                    $ch = Format-AT3SpawnCharacter -Hash $bh -Name $bn
                }
                $row["Character"] = $ch
                $row["Slot"] = ""
                $row["Del"] = ""
                $row["New"] = "1"
                if ($isAdd) {
                    $row["Tag"] = "(new)"
                    $row["Job"] = "n"
                    $row["Donor"] = [string]$sr["Donor"]
                    $row["TagMode"] = [string]$sr["TagMode"]
                    Set-AT3SpawnNewCells -Row $row -Index (@($state.Table.Select("New = '1' AND ISNULL(Kind, '') <> 'clone'")).Count)
                } else {
                    $mode = "shared"
                    if ($isClone -and ([string]$sr["TagMode"] -eq "own")) { $mode = "own" }
                    $row["Tag"] = "(copy)"
                    $row["Job"] = [string]$bs.Job
                    $row["Kind"] = "clone"
                    $row["CloneOf"] = $src
                    $row["TagMode"] = $mode
                    $row["Donor"] = ""
                    Set-AT3SpawnCloneCells -Row $row -Index (@($state.Table.Select("Kind = 'clone'")).Count) -Live $null -Source $bs -TagMode $mode -CloneOf $src
                }
                $state.Table.Rows.Add($row)
                foreach ($dv in $state.Table.DefaultView) {
                    if ($dv.Row -eq $row) { $g.SelectedItem = $dv; $g.ScrollIntoView($dv); break }
                }
                return
            }

            # nothing selected: a new spawn of the region's first character at 0, 0, 0
            $row = $state.Table.NewRow()
            Set-AT3SpawnNewCells -Row $row -Index (@($state.Table.Select("New = '1' AND ISNULL(Kind, '') <> 'clone'")).Count)
            $row["Slot"] = ""
            $row["Tag"] = "(new)"
            # First character in this region's own library, so the cell always
            # holds something the region can actually load; change it in the row.
            $first = ""
            if ($state.Chars -and $state.Chars.Count -gt 0) { $first = [string]$state.Chars[0] }
            $row["Character"] = $first
            $row["X"] = "0"; $row["Y"] = "0"; $row["Z"] = "0"; $row["Yaw"] = "0"
            $row["Position"] = "0  0  0"
            $row["Job"] = "n"
            $row["Del"] = ""
            $row["New"] = "1"
            $row["Donor"] = ""; $row["TagMode"] = ""
            $state.Table.Rows.Add($row)
            $g.ScrollIntoView($g.Items[$g.Items.Count - 1])
        } catch { }
    }.GetNewClosure())

    [void]$cmb.Add_SelectionChanged({
        try {
            $sel = $cmb.SelectedItem
            if ($sel) { & $load ([string]$sel.Id) }
        } catch { }
    }.GetNewClosure())

    [void]$tools.Add_SelectionChanged({
        try {
            if ($tools.SelectedIndex -le 0) { return }
            $pick = [string]$tools.SelectedItem
            $tools.SelectedIndex = 0
            if ($pick -eq "Spawn Randomizer") { Show-AT3SpawnRandomizer }
            else { Show-AT3Placeholder -Name $pick }
        } catch { }
    }.GetNewClosure())

    [void]$w.Add_Closed({
        try {
            [void]$g.CommitEdit([System.Windows.Controls.DataGridEditingUnit]::Row, $true)
            if ($state.Region -and $state.Table) {
                [void](Save-AT3SpawnRows -Region $state.Region -Table $state.Table -Baseline $state.Base)
            }
        } catch { }
    }.GetNewClosure())

    $script:SpawnState = $state
    if ($cmb.Items.Count -gt 0) { $cmb.SelectedIndex = 0 }
    $cfm = Add-AT3ConfirmBar -Window $w
    $snap = Save-AT3EditorSnapshot
    [void]$w.ShowDialog()
    # The editor saves its CSVs as it goes (region switches, close); CANCEL
    # puts every one of them back as it was when the window opened.
    if ($cfm.Ok) { Invoke-AT3Apply } else { Restore-AT3EditorSnapshot -Snap $snap }
}

# ===========================================================================
# AT3 v2 - wiring
# ===========================================================================

# --- editor menus ----------------------------------------------------------
[void](New-AT3Menu -Owner $btnGameplay -Background "#26402A" -Border "#5E8C4A" `
    -Items @("Global Game Rules", "Ammotype Config", "Character Catalogue") `
    -OnPick {
        param($s, $e)
        switch ([string]$s.Tag) {
            "Global Game Rules" { Show-AT3GlobalRules }
            "Ammotype Config"   { Show-AT3AmmoConfig }
            "Character Catalogue"  { Show-AT3CharacterStudio }
            default             { Show-AT3Placeholder -Name ([string]$s.Tag) }
        }
    })

[void](New-AT3Menu -Owner $btnMap -Background "#2A3145" -Border "#5A6E9C" `
    -Items @("Ambience Config", "Prop Editor", "Spawns Editor") `
    -OnPick {
        param($s, $e)
        if ([string]$s.Tag -eq "Prop Editor") { Show-AT3PropEditor }
        elseif ([string]$s.Tag -eq "Ambience Config") { Show-AT3AmbienceConfig }
        elseif ([string]$s.Tag -eq "Spawns Editor") { Show-AT3SpawnsEditor }
        else { Show-AT3Placeholder -Name ([string]$s.Tag) }
    })

[void](New-AT3Menu -Owner $btnCreator -Background "#3A2438" -Border "#8C5E86" `
    -Items @("Character Creator", "Weapon Creator") `
    -OnPick {
        param($s, $e)
        if ([string]$s.Tag -eq "Character Creator") { Show-AT3CharacterCreator }
        else { Show-AT3WeaponCreator }
    })

# --- presets ---------------------------------------------------------------
function Show-AT3NameDialog {
    # A WIN32 DIALOG, DELIBERATELY.
    #
    # This built a WPF window and called ShowDialog(). Raised from the PRESETS
    # ContextMenu it did NOTHING AT ALL - the menu still holds mouse capture, so
    # the window never took focus, and because WPF swallows handler exceptions
    # there was no error either. Deleting a preset worked from the same menu the
    # whole time because MessageBox is a Win32 dialog; InputBox is its
    # text-entry counterpart, so the prompt now uses the same mechanism.
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic -ErrorAction Stop
        $n = [Microsoft.VisualBasic.Interaction]::InputBox("Preset name", "Save Preset", "")
        if ($null -eq $n) { return $null }
        $n = ([string]$n).Trim()
        if (-not $n) { return $null }
        return $n
    } catch {
        Write-AT3Log ("Show-AT3NameDialog failed: " + $_.Exception.Message)
        return $null
    }
}
# ===========================================================================
# PRESETS - FORMAT 3 (AT3 0.3.0)
#
# One self-contained .json. Sharing a preset is sending that one file.
#
#   Global, Ammo      as before
#   Editors           every tool's saved state: the Prop and Spawn editor CSVs,
#                     prop names, the randomizer settings, and each region's
#                     ambience values that differ from vanilla
#   PropPorts         meshes ported into a region's Object Library
#   Customs           every record AT3 built (characters, weapons, sprays) and
#                     every stock record saved in place - as PATCHES against
#                     retail records, via preset_customs.py. No Oddworld data
#                     travels; the recipient's own install supplies it.
#
# Older sections (Recipes, Weapons, Spawns, Jobs, Files, Mods, Requires,
# Description) are carried through untouched, as before.
# ===========================================================================
function Get-AT3EnvRegionIds {
    return @(Get-AT3Regions | Where-Object { Test-Path (Join-Path $RegionDataDir ("env_" + $_.Id + ".csv")) } |
             ForEach-Object { [string]$_.Id })
}

function Get-AT3PresetEditors {
    $files = [ordered]@{}
    if (Test-Path $PropDir) {
        foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter *.csv -File | Sort-Object Name)) {
            $files[$f.Name] = [System.IO.File]::ReadAllText($f.FullName)
        }
    }
    $pn = Join-Path $AT3Dir "PropNames.csv"
    $amb = [ordered]@{}
    # Fresh, from the live levels - what the game has now.
    $script:AmbienceTables = @{}
    foreach ($id in (Get-AT3EnvRegionIds)) {
        [void](Get-AT3AmbienceTables -Region $id)
        $rows = @(Get-AT3AmbienceEdits -Region $id | ForEach-Object {
            [ordered]@{ Field = [string]$_.Field; SetIndex = [string]$_.SetIndex; Value = [string]$_.Value } })
        if ($rows.Count) { $amb[$id] = $rows }
    }
    $script:AmbienceTables = @{}
    return [ordered]@{
        Files      = $files
        PropNames  = $(if (Test-Path $pn) { [System.IO.File]::ReadAllText($pn) } else { $null })
        Randomizer = $(if (Test-Path $RandomizerConfigPath) { [System.IO.File]::ReadAllText($RandomizerConfigPath) } else { $null })
        Ambience   = $amb
    }
}

function Set-AT3PresetEditors {
    param($Editors)
    if (-not $Editors) { return }
    if (-not (Test-Path $PropDir)) { [void](New-Item -ItemType Directory -Force -Path $PropDir) }
    foreach ($f in @(Get-ChildItem -LiteralPath $PropDir -Filter *.csv -File -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $f.FullName -Force
    }
    if ($Editors.Files) {
        foreach ($prop in $Editors.Files.PSObject.Properties) {
            $nm = [System.IO.Path]::GetFileName([string]$prop.Name)   # never a path out of PropDir
            if ($nm -notmatch '^[A-Za-z0-9_.-]+\.csv$') { continue }
            [System.IO.File]::WriteAllText((Join-Path $PropDir $nm), [string]$prop.Value, (New-Object System.Text.UTF8Encoding $true))
        }
    }
    $pn = Join-Path $AT3Dir "PropNames.csv"
    if ($null -ne $Editors.PropNames) { [System.IO.File]::WriteAllText($pn, [string]$Editors.PropNames, (New-Object System.Text.UTF8Encoding $true)) }
    if ($null -ne $Editors.Randomizer) {
        [System.IO.File]::WriteAllText($RandomizerConfigPath, [string]$Editors.Randomizer, (New-Object System.Text.UTF8Encoding $true))
    } elseif (Test-Path $RandomizerConfigPath) {
        Remove-Item -LiteralPath $RandomizerConfigPath -Force
    }
    # Ambience: every region back to vanilla, then the preset's values. The
    # apply stage writes whatever differs from the live level.
    $script:AmbienceTables = @{}
    foreach ($id in (Get-AT3EnvRegionIds)) {
        $set = Get-AT3AmbienceTables -Region $id
        foreach ($r in $set.Fog.Rows) { $r["RGB"] = $r["VanRGB"]; $r["A"] = $r["VanA"]; $r["Start"] = $r["VanStart"]; $r["End"] = $r["VanEnd"] }
        foreach ($g in $script:AmbienceGroups) { foreach ($r in $set[$g.Key].Rows) { $r["RGB"] = $r["VanRGB"]; $r["A"] = $r["VanA"] } }
        $want = $(if ($Editors.Ambience) { $Editors.Ambience.PSObject.Properties[$id] } else { $null })
        if (-not $want) { continue }
        foreach ($e in @($want.Value)) {
            $f = [string]$e.Field; $i = [string]$e.SetIndex; $v = [string]$e.Value
            if ($f -like "fog*") {
                $row = @($set.Fog.Rows | Where-Object { [string]$_["SetIndex"] -eq $i })[0]
                if (-not $row) { continue }
                if ($f -eq "fogColor") {
                    $parts = @($v -split ",")
                    if ($parts.Count -ge 4) {
                        $row["RGB"] = "{0}, {1}, {2}" -f $parts[0].Trim(), $parts[1].Trim(), $parts[2].Trim()
                        $row["A"] = $parts[3].Trim()
                    }
                } elseif ($f -eq "fogStart") { $row["Start"] = $v } elseif ($f -eq "fogEnd") { $row["End"] = $v }
                continue
            }
            foreach ($g in $script:AmbienceGroups) {
                foreach ($row in @($set[$g.Key].Rows | Where-Object { [string]$_["Field"] -eq $f })) {
                    $kind = [string]$row["Kind"]
                    if ($kind -eq "c") {
                        $parts = @($v -split ",")
                        if ($parts.Count -ge 4) {
                            $row["RGB"] = "{0}, {1}, {2}" -f $parts[0].Trim(), $parts[1].Trim(), $parts[2].Trim()
                            $row["A"] = $parts[3].Trim()
                        }
                    } elseif ($kind -eq "v2" -or $kind -eq "h") { $row["RGB"] = $v } else { $row["A"] = $v }
                }
            }
        }
    }
}

function Get-AT3PresetPropPorts {
    $out = @()
    foreach ($f in @(Get-ChildItem -LiteralPath $RegionDataDir -Filter "proplib_*.csv" -File -ErrorAction SilentlyContinue)) {
        $id = $f.BaseName -replace "^proplib_", ""
        foreach ($r in @(Import-Csv -LiteralPath $f.FullName)) {
            if ([string]$r.Name -like "*(ported*") { $out += [ordered]@{ Region = $id; Key = [string]$r.Key } }
        }
    }
    return $out
}

function Save-AT3PresetV2 {
    param([Parameter(Mandatory)][string]$Name, $Base = $script:LoadedPreset)
    if (-not (Test-Path $PresetsDir)) { [void](New-Item -ItemType Directory -Force -Path $PresetsDir) }
    $ammo = @()
    foreach ($n in ($script:AmmoCur.Keys | Sort-Object)) {
        $ammo += [pscustomobject]@{ Name = $n
                                    Knock = [double]$script:AmmoCur[$n].Knock
                                    KnockPlayer = [double]$script:AmmoCur[$n].KnockPlayer }
    }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("at3_capture_" + [guid]::NewGuid().ToString("N") + ".json")
    $r = Invoke-AT3Python -Arguments @((Join-Path $ModToolsDir "preset_customs.py"), "capture", $tmp) -Activity "Capturing custom characters and weapons"
    $customs = $null
    if ($r.Ok -and (Test-Path $tmp)) {
        $customs = Get-Content -LiteralPath $tmp -Raw | ConvertFrom-Json
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    } else {
        throw ("could not capture custom records: " + [string]$r.Output)
    }
    $obj = [ordered]@{
        Name       = $Name
        Format     = 3
        AT3Version = $script:AT3Version
        Global = [ordered]@{
            Health   = $script:GlobalRules.Health
            Stamina  = $script:GlobalRules.Stamina
            FireRate = $script:GlobalRules.FireRate
            Reload   = $script:GlobalRules.Reload
            Accuracy = $script:GlobalRules.Accuracy
            MissTime = $script:GlobalRules.MissTime
        }
        Ammo      = $ammo
        Editors   = (Get-AT3PresetEditors)
        PropPorts = @(Get-AT3PresetPropPorts)
        Customs   = $customs
    }
    # CARRY EVERYTHING THIS EDITOR DOES NOT AUTHOR (see the note in 0.2.x: an
    # allow-list here once silently destroyed AT3 Official's sections).
    $authored = @("Name", "Saved", "Format", "AT3Version", "Global", "Ammo", "Editors", "PropPorts", "Customs")
    if ($Base) {
        foreach ($prop in $Base.PSObject.Properties) {
            if ($authored -contains $prop.Name) { continue }
            $obj[$prop.Name] = $prop.Value
        }
    }
    $obj["Saved"] = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
    $path = Get-AT3PresetPath -Name $Name
    [System.IO.File]::WriteAllText($path, ($obj | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding $false))
    return $path
}

function Get-AT3PresetPath {
    param([string]$Name)
    $safe = ($Name -replace '[^A-Za-z0-9 _.-]', '_').Trim()
    return (Join-Path $PresetsDir "$safe.json")
}

# Install what a format-3 preset carries beyond the tool settings: AT3-built
# records and ported props. Returns feedback lines.
function Install-AT3PresetContent {
    param($Preset)
    $msgs = @()
    if ($Preset.PropPorts) {
        foreach ($pp in @($Preset.PropPorts)) {
            $r = Invoke-AT3Python -Arguments @((Join-Path $ModToolsDir "port_prop_geo.py"), [string]$pp.Region, [string]$pp.Key) `
                -Activity ("Porting geometry into region " + [string]$pp.Region)
            if (-not ($r.Output -match "PORTED|ALREADY")) { $msgs += ("Prop port " + [string]$pp.Key + " -> " + [string]$pp.Region + ": FAILED") }
        }
    }
    if ($Preset.Customs -and @($Preset.Customs.Records).Count) {
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("at3_install_" + [guid]::NewGuid().ToString("N") + ".json")
        [System.IO.File]::WriteAllText($tmp, ([ordered]@{ Customs = $Preset.Customs } | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding $false))
        $r = Invoke-AT3Python -Arguments @((Join-Path $ModToolsDir "preset_customs.py"), "install", $tmp) -Activity "Building the preset's characters and weapons"
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
        $txt = [string]$r.Output
        Write-AT3Log ("preset customs install :: " + ($txt -replace "`r?`n", " | "))
        $bad = @($txt -split "`r?`n" | Where-Object { $_ -match "FAILED|REFUSED|SKIP" })
        $n = @($Preset.Customs.Records).Count
        if ($bad.Count) { $msgs += ("Custom records: $n in preset, problems:") ; $msgs += @($bad | ForEach-Object { "   " + $_.Trim() }) }
        else { $msgs += "Custom records: $n installed or already present." }
        $script:CatalogueFresh = $false
        [void](Update-AT3Index)
    }
    return $msgs
}

function Export-AT3Preset {
    param([string]$Path)
    $name = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $folder = Join-Path (Split-Path -Parent $Path) $name
    $hasFolder = Test-Path -LiteralPath $folder -PathType Container
    $dlg = New-Object Microsoft.Win32.SaveFileDialog
    $dlg.FileName = $name + $(if ($hasFolder) { ".zip" } else { ".json" })
    $dlg.Filter = $(if ($hasFolder) { "AT3 preset package (*.zip)|*.zip" } else { "AT3 preset (*.json)|*.json" })
    if (-not $dlg.ShowDialog()) { return $null }
    if ($hasFolder) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path $dlg.FileName) { Remove-Item -LiteralPath $dlg.FileName -Force }
        $z = [System.IO.Compression.ZipFile]::Open($dlg.FileName, "Create")
        try {
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $Path, "$name.json")
            foreach ($f in @(Get-ChildItem -LiteralPath $folder -Recurse -File)) {
                $rel = $name + "/" + $f.FullName.Substring($folder.Length + 1).Replace("\", "/")
                [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $f.FullName, $rel)
            }
        } finally { $z.Dispose() }
    } else {
        Copy-Item -LiteralPath $Path -Destination $dlg.FileName -Force
    }
    return $dlg.FileName
}

function Import-AT3Preset {
    $dlg = New-Object Microsoft.Win32.OpenFileDialog
    $dlg.Filter = "AT3 presets (*.json;*.zip)|*.json;*.zip"
    if (-not $dlg.ShowDialog()) { return $null }
    if (-not (Test-Path $PresetsDir)) { [void](New-Item -ItemType Directory -Force -Path $PresetsDir) }
    $src = $dlg.FileName
    if ($src.ToLower().EndsWith(".zip")) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $z = [System.IO.Compression.ZipFile]::OpenRead($src)
        try {
            $jsons = @($z.Entries | Where-Object { $_.FullName -notmatch "/" -and $_.Name -like "*.json" })
            if ($jsons.Count -ne 1) { throw "the package must hold exactly one preset .json at its top level" }
            $dest = Join-Path $PresetsDir $jsons[0].Name
            if ((Test-Path $dest) -and -not (Confirm-AT3Choice -Title "Import Preset" -Text ("A preset named '" + [System.IO.Path]::GetFileNameWithoutExtension($dest) + "' already exists. Replace it?"))) { return $null }
            $root = [System.IO.Path]::GetFullPath($PresetsDir)
            foreach ($e in $z.Entries) {
                if (-not $e.Name) { continue }
                $out = [System.IO.Path]::GetFullPath((Join-Path $PresetsDir $e.FullName))
                if (-not $out.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { continue }   # no ..\ escapes
                [void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out))
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $out, $true)
            }
        } finally { $z.Dispose() }
        return $dest
    }
    try { [void](Get-Content -LiteralPath $src -Raw | ConvertFrom-Json) } catch { throw "that file is not a valid preset (not JSON)" }
    $dest = Join-Path $PresetsDir ([System.IO.Path]::GetFileName($src))
    if ((Test-Path $dest) -and -not (Confirm-AT3Choice -Title "Import Preset" -Text ("A preset named '" + [System.IO.Path]::GetFileNameWithoutExtension($dest) + "' already exists. Replace it?"))) { return $null }
    Copy-Item -LiteralPath $src -Destination $dest -Force
    return $dest
}

function Show-AT3PresetMenu {
    $conv = New-Object System.Windows.Media.BrushConverter
    $menu = New-Object System.Windows.Controls.ContextMenu
    $menu.Placement = [System.Windows.Controls.Primitives.PlacementMode]::Left
    $menu.PlacementTarget = $btnPresets
    $menu.Background = $conv.ConvertFromString("#4A3524")
    $menu.BorderBrush = $conv.ConvertFromString("#8A6D3B")

    $save = New-Object System.Windows.Controls.MenuItem
    $save.Header = "+ Save Preset"
    $save.Foreground = $conv.ConvertFromString("#F2E4C4")
    [void]$save.Add_Click({
        try {
            Write-AT3Log "Save Preset clicked"
            $menu.IsOpen = $false
            $n = Show-AT3NameDialog
            Write-AT3Log ("name entered: '" + [string]$n + "'")
            if (-not $n) { return }
            $target = Get-AT3PresetPath -Name $n
            $base = $script:LoadedPreset
            if (Test-Path -LiteralPath $target) {
                if (-not (Confirm-AT3Choice -Title "Save Preset" -Text ("A preset named '" + $n + "' already exists. Overwrite it with the current settings?"))) { return }
                try { $base = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json } catch { }
            }
            $p = Save-AT3PresetV2 -Name $n -Base $base
            Write-AT3Log ("saved to " + $p)
            Set-AT3Feedback -Append -Text ("Preset saved: " + (Split-Path -Leaf $p))
        } catch {
            Write-AT3Log ("SAVE FAILED: " + $_.Exception.GetType().Name + ": " + $_.Exception.Message)
            Set-AT3Feedback -Append -Text ("Could not save preset: " + $_.Exception.Message)
        }
    }.GetNewClosure())
    [void]$menu.Items.Add($save)

    $imp = New-Object System.Windows.Controls.MenuItem
    $imp.Header = "Import Preset..."
    $imp.Foreground = $conv.ConvertFromString("#F2E4C4")
    [void]$imp.Add_Click({
        try {
            $menu.IsOpen = $false
            $got = Import-AT3Preset
            if ($got) { Set-AT3Feedback -Append -Text ("Imported preset: " + [System.IO.Path]::GetFileNameWithoutExtension($got) + ". Open PRESETS to load it.") }
        } catch { Set-AT3Feedback -Append -Text ("Could not import preset: " + $_.Exception.Message) }
    }.GetNewClosure())
    [void]$menu.Items.Add($imp)

    $opn = New-Object System.Windows.Controls.MenuItem
    $opn.Header = "Open Presets Folder"
    $opn.Foreground = $conv.ConvertFromString("#F2E4C4")
    [void]$opn.Add_Click({
        $menu.IsOpen = $false
        if (-not (Test-Path $PresetsDir)) { [void](New-Item -ItemType Directory -Force -Path $PresetsDir) }
        Start-Process explorer.exe -ArgumentList ('"' + $PresetsDir + '"')
    }.GetNewClosure())
    [void]$menu.Items.Add($opn)
    [void]$menu.Items.Add((New-Object System.Windows.Controls.Separator))

    foreach ($f in (Get-PresetFiles)) {
        $mi = New-Object System.Windows.Controls.MenuItem
        $mi.Tag = $f.FullName
        $mi.Foreground = $conv.ConvertFromString("#F2E4C4")

        # The header is a panel rather than a string so the delete button can sit
        # inside the row. The X is docked right and added FIRST - in a DockPanel
        # the last child fills whatever is left, which is what the name should do.
        $hdr = New-Object System.Windows.Controls.DockPanel
        $hdr.MinWidth = 210
        $del = New-Object System.Windows.Controls.Button
        $del.Content = [string][char]0x2716
        $del.Width = 20
        $del.Height = 18
        $del.Padding = New-Object System.Windows.Thickness 0
        $del.FontSize = 10
        $del.Margin = New-Object System.Windows.Thickness 12,0,0,0
        $del.ToolTip = "Delete this preset"
        $del.Background = $conv.ConvertFromString("#4A2A22")
        $del.Foreground = $conv.ConvertFromString("#E8C9A0")
        $del.BorderBrush = $conv.ConvertFromString("#8A5A3B")
        [void][System.Windows.Controls.DockPanel]::SetDock($del, "Right")
        [void]$hdr.Children.Add($del)
        # Export and overwrite sit beside delete, same size and style.
        $exp = New-Object System.Windows.Controls.Button
        $exp.Content = [string][char]0x21E7
        $exp.ToolTip = "Export this preset to share it"
        $ovw = New-Object System.Windows.Controls.Button
        $ovw.Content = [string][char]0x270E
        $ovw.ToolTip = "Overwrite this preset with the current settings"
        foreach ($b in @($exp, $ovw)) {
            $b.Width = 20; $b.Height = 18; $b.Padding = New-Object System.Windows.Thickness 0
            $b.FontSize = 10; $b.Margin = New-Object System.Windows.Thickness 4,0,0,0
            $b.Background = $conv.ConvertFromString("#3A2A1E"); $b.Foreground = $conv.ConvertFromString("#E8C9A0")
            $b.BorderBrush = $conv.ConvertFromString("#8A6D3B")
            [void][System.Windows.Controls.DockPanel]::SetDock($b, "Right")
            [void]$hdr.Children.Add($b)
        }
        [void]$exp.Add_Click({
            param($s3, $e3)
            $e3.Handled = $true
            $menu.IsOpen = $false
            try {
                $got = Export-AT3Preset -Path $f.FullName
                if ($got) { Set-AT3Feedback -Append -Text ("Exported preset to " + $got) }
            } catch { Set-AT3Feedback -Append -Text ("Could not export preset: " + $_.Exception.Message) }
        }.GetNewClosure())
        [void]$ovw.Add_Click({
            param($s4, $e4)
            $e4.Handled = $true
            $menu.IsOpen = $false
            $nm = $f.BaseName
            if (-not (Confirm-AT3Choice -Title "Overwrite Preset" -Text ("Overwrite '" + $nm + "' with the current settings of every tool?" +
                [Environment]::NewLine + [Environment]::NewLine + "Its description and any hand-written sections are kept."))) { return }
            try {
                $base = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
                $p2 = Save-AT3PresetV2 -Name ([string]$(if ($base.Name) { $base.Name } else { $nm })) -Base $base
                if ($p2 -ne $f.FullName) { Move-Item -LiteralPath $p2 -Destination $f.FullName -Force }
                Set-AT3Feedback -Append -Text ("Preset overwritten: " + $nm)
            } catch { Set-AT3Feedback -Append -Text ("Could not overwrite preset: " + $_.Exception.Message) }
        }.GetNewClosure())
        $nameText = New-Object System.Windows.Controls.TextBlock
        $nameText.Text = $f.BaseName
        $nameText.VerticalAlignment = "Center"
        $nameText.Foreground = $conv.ConvertFromString("#F2E4C4")
        [void]$hdr.Children.Add($nameText)
        $mi.Header = $hdr

        [void]$del.Add_Click({
            param($s2, $e2)
            # Close the menu and stop the click here, or the row underneath is
            # invoked too and the preset gets LOADED on its way to being deleted.
            $e2.Handled = $true
            $menu.IsOpen = $false
            $nm = $f.BaseName
            $extra = ""
            $folder = Join-Path $PresetsDir $nm
            if (Test-Path -LiteralPath $folder -PathType Container) {
                $c = @(Get-ChildItem -LiteralPath $folder -Recurse -File -ErrorAction SilentlyContinue).Count
                $extra = [Environment]::NewLine + [Environment]::NewLine + "It also ships $c file(s) in Presets\$nm\, which will go with it."
            }
            $answer = [System.Windows.MessageBox]::Show(
                "Delete the preset '$nm'?" + [Environment]::NewLine + [Environment]::NewLine +
                "This permanently removes it from StrangerAT3\Presets. Changes already applied to the game are not affected - confirming any tool rewrites the game from the current settings." + $extra,
                "Delete Preset", "YesNo", "Warning")
            if ($answer -ne "Yes") { return }
            try {
                Set-AT3Feedback -Append -Text (Remove-AT3Preset -Path $f.FullName)
            } catch {
                Set-AT3Feedback -Append -Text ("Could not delete preset: " + $_.Exception.Message)
            }
        }.GetNewClosure())

        [void]$mi.Add_Click({
            param($s, $e)
            try {
                $pname = [System.IO.Path]::GetFileNameWithoutExtension([string]$s.Tag)
                $ans = [System.Windows.MessageBox]::Show(
                    ("Load and apply the preset '" + $pname + "'?" + [Environment]::NewLine + [Environment]::NewLine +
                     "It replaces the current settings in every tool and is written to the game now."),
                    "Load Preset", "YesNo", "Question")
                if ($ans -ne "Yes") { return }
                $n = Load-AT3Preset -Path ([string]$s.Tag)
                $extra = @(Install-AT3PresetContent -Preset $script:LoadedPreset)
                Set-AT3Feedback -Append -Text ((@("Loaded preset '" + $pname + "' - $n ammo value(s). Applying...") + $extra) -join "`r`n")
                Invoke-AT3Apply
            } catch {
                Set-AT3Feedback -Append -Text ("Could not load preset: " + $_.Exception.Message)
            }
        })
        [void]$menu.Items.Add($mi)
    }
    $btnPresets.ContextMenu = $menu
    $menu.IsOpen = $true
}

[void]$btnPresets.Add_Click({ Show-AT3PresetMenu })

# ===========================================================================
# CONFIRM / CANCEL - one bar for every tool window
#
# Add-AT3ConfirmBar wraps the window's existing content in a DockPanel with
# the bar docked at the bottom, so no tool's own layout has to change. The
# returned flag's .Ok is $true only when CONFIRM closed the window; the X,
# Escape and CANCEL all leave it $false. Each tool's close handler commits its
# edits only when .Ok is set, and the Show function calls Invoke-AT3Apply
# AFTER ShowDialog returns - never inside a GetNewClosure handler, where
# $script: would not reach the real session state.
# ===========================================================================
function Add-AT3ConfirmBar {
    param($Window, [string]$Note = "")
    $flag = @{ Ok = $false }
    $conv = New-Object System.Windows.Media.BrushConverter
    $inner = $Window.Content
    $Window.Content = $null
    $outer = New-Object System.Windows.Controls.DockPanel
    $bar = New-Object System.Windows.Controls.DockPanel
    $bar.Margin = New-Object System.Windows.Thickness 14,6,14,12
    [void][System.Windows.Controls.DockPanel]::SetDock($bar, "Bottom")
    $bOk = New-Object System.Windows.Controls.Button
    $bOk.Content = "Confirm"; $bOk.Width = 110; $bOk.Height = 28
    $bOk.Margin = New-Object System.Windows.Thickness 8,0,0,0
    $bOk.Background = $conv.ConvertFromString("#4A3524"); $bOk.Foreground = $conv.ConvertFromString("#F2E4C4")
    $bOk.ToolTip = "Write these changes to the game now."
    $bNo = New-Object System.Windows.Controls.Button
    $bNo.Content = "Cancel"; $bNo.Width = 90; $bNo.Height = 28
    $bNo.Margin = New-Object System.Windows.Thickness 8,0,0,0
    $bNo.ToolTip = "Close without keeping anything changed in this window."
    [void][System.Windows.Controls.DockPanel]::SetDock($bNo, "Right")
    [void][System.Windows.Controls.DockPanel]::SetDock($bOk, "Right")
    [void]$bar.Children.Add($bNo)
    [void]$bar.Children.Add($bOk)
    $tb = New-Object System.Windows.Controls.TextBlock
    $tb.Text = $Note
    $tb.VerticalAlignment = "Center"; $tb.TextWrapping = "Wrap"
    $tb.Foreground = $conv.ConvertFromString("#9A8A6C")
    [void]$bar.Children.Add($tb)
    [void]$outer.Children.Add($bar)
    [void]$outer.Children.Add($inner)
    $Window.Content = $outer
    [void]$bOk.Add_Click({ $flag.Ok = $true; $Window.Close() }.GetNewClosure())
    [void]$bNo.Add_Click({ $Window.Close() }.GetNewClosure())
    return $flag
}

# Byte snapshot of the editor CSVs a tool saves as it goes (the prop and spawn
# editors save on every region switch), so CANCEL can put them back exactly.
function Save-AT3EditorSnapshot {
    $snap = @{ Files = @{}; Dirs = @($PropDir) }
    $paths = @()
    if (Test-Path $PropDir) { $paths += @(Get-ChildItem -LiteralPath $PropDir -Filter *.csv -File | ForEach-Object { $_.FullName }) }
    $pn = Join-Path $AT3Dir "PropNames.csv"
    if (Test-Path $pn) { $paths += $pn }
    $snap.Names = $pn
    foreach ($q in $paths) { $snap.Files[$q] = [System.IO.File]::ReadAllBytes($q) }
    return $snap
}

function Restore-AT3EditorSnapshot {
    param($Snap)
    if (-not $Snap) { return }
    $now = @()
    if (Test-Path $PropDir) { $now += @(Get-ChildItem -LiteralPath $PropDir -Filter *.csv -File | ForEach-Object { $_.FullName }) }
    if (Test-Path $Snap.Names) { $now += $Snap.Names }
    foreach ($q in $now) {
        if (-not $Snap.Files.ContainsKey($q)) { Remove-Item -LiteralPath $q -ErrorAction SilentlyContinue }
    }
    foreach ($q in @($Snap.Files.Keys)) { [System.IO.File]::WriteAllBytes($q, $Snap.Files[$q]) }
}

# --- apply -----------------------------------------------------------------
# There is no APPLY CHANGES button any more. Every tool window has CONFIRM,
# which writes to the game at once, and CANCEL (or the window's X), which
# discards what was changed in that window. Confirm runs this.
#
# Level-touching stages share files and have a fixed order (reset -> preset ->
# props -> spawns -> randomizer -> blockmap sync), so any Confirm other than
# Global Rules re-runs the whole pipeline from SAVED state. Only confirmed
# edits ever reach saved state, so the result is exactly what the user
# confirmed across every tool.
function Invoke-AT3Apply {
    param([switch]$RulesOnly)
    $msgs = @()

    # Global rules live in SWSEMods pref files that nothing else touches, so
    # their Confirm writes only those - no bundle or level is rewritten.
    if ($RulesOnly) {
        $hp   = Get-OptionalDouble $script:GlobalRules.Health
        $stam = Get-OptionalDouble $script:GlobalRules.Stamina
        Set-AT3PlayerPrefs -Health $hp -Stamina $stam
        Set-AT3AiProfile `
            -FireRate (Get-MultiplierDouble $script:GlobalRules.FireRate 1.0) `
            -Reload   (Get-MultiplierDouble $script:GlobalRules.Reload   1.0) `
            -Accuracy (Get-MultiplierDouble $script:GlobalRules.Accuracy 1.0) `
            -MissTime (Get-MultiplierDouble $script:GlobalRules.MissTime 10.0)
        Set-AT3Feedback -Append -Text "Global rules written."
        return
    }

    # Rescan before anything below reads a hash's location. Startup's index
    # can be stale by now - the game may have run and SWSE saved something,
    # another AT3 session may be open, files may have been hand-edited. Every
    # RecOff resolved during this click has to come from what is on disk THIS
    # instant, not from whenever the window happened to open.
    $script:AT3IndexMap = $null
    if (Update-AT3Index) { $msgs += "File index refreshed." }
    [void](Update-AT3Catalogue)

    $hp   = Get-OptionalDouble $script:GlobalRules.Health
    $stam = Get-OptionalDouble $script:GlobalRules.Stamina
    Set-AT3PlayerPrefs -Health $hp -Stamina $stam
    Set-AT3AiProfile `
        -FireRate (Get-MultiplierDouble $script:GlobalRules.FireRate 1.0) `
        -Reload   (Get-MultiplierDouble $script:GlobalRules.Reload   1.0) `
        -Accuracy (Get-MultiplierDouble $script:GlobalRules.Accuracy 1.0) `
        -MissTime (Get-MultiplierDouble $script:GlobalRules.MissTime 10.0)
    $msgs += "Global rules written."

    # Preset files are a matched set - put any previous set back before writing,
    # or a region ends up half-modded and will not load.
    $reverted = Restore-AT3PresetFiles
    if ($reverted -gt 0) { $msgs += "Reverted $reverted preset file(s)." }

    # The spawn reset copies an older level file back, which would wipe any
    # ambience edit made since. Read every region's live ambience first; the
    # ambience stage below writes back whatever is not vanilla.
    foreach ($r in (Get-AT3Regions)) {
        if (Test-Path (Join-Path $RegionDataDir ("env_" + $r.Id + ".csv"))) { [void](Get-AT3AmbienceTables -Region ([string]$r.Id)) }
    }

    # Before the preset writes anything into a level.
    $msgs += (Reset-AT3SpawnLevels)

    if ($script:AmmoCur.Count -gt 0) { $msgs += (Set-AT3AmmoKnockback -Rows (Get-AT3AmmoRows)) }

    if ($script:LoadedPreset) {
        $msgs += (Set-AT3PresetFiles   -Preset $script:LoadedPreset)
        # Recipes before Mods: Mods writes the character's hash into the level,
        # and the character has to exist in a bundle before that means anything.
        $msgs += (Set-AT3PresetRecipes -Preset $script:LoadedPreset)
        $msgs += (Set-AT3PresetMods    -Preset $script:LoadedPreset)
    }

    $msgs += (Set-AT3PropsAll)
    $msgs += (Set-AT3SpawnsAll)
    # After the spawn stage, so it re-rolls on top of the user's own edits.
    $msgs += (Set-AT3RandomizerAll)

    $msgs += (Set-AT3AmbienceAll)
    # Re-read from the level on next use, now that it has been rewritten.
    $script:AmbienceTables = @{}

    # Last, so it sees whatever every earlier stage left on disk.
    $msgs += (Sync-AT3Blockmaps)

    # Game files changed - the catalogue must re-check before its next use.
    $script:CatalogueFresh = $false
    Set-AT3Feedback -Append -Text (($msgs | Where-Object { $_ }) -join "`r`n")
}

# --- open the game ---------------------------------------------------------
[void]$btnLaunch.Add_Click({
    if (-not (Test-Path $GameExe)) {
        Set-AT3Feedback -Append -Text "Cannot find Launcher.exe in the game folder."
        return
    }
    Start-Process -FilePath $GameExe -WorkingDirectory $GameRoot
    Set-AT3Feedback -Append -Text "Launcher opened. Changes already applied are in place."
})

# --- restore vanilla -------------------------------------------------------
[void]$btnRestore.Add_Click({
    $answer = [System.Windows.MessageBox]::Show(
        "Undo every change AT3 has made to the game?" + [Environment]::NewLine + [Environment]::NewLine +
        "This restores the backup copies AT3 made on this machine, and clears every editor input: spawns, props, ambience, gameplay rules, ammo, and the randomizer. Your saved PRESETS are kept, so you can load one to put it back.",
        "Restore Vanilla", "YesNo", "Question")
    if ($answer -ne "Yes") { return }
    Set-AT3Feedback -Append -Text (Restore-AT3Vanilla)
})

Write-AT3Timing "window built"
[void]$window.Add_ContentRendered({ Write-AT3Timing "window shown" })
$window.ShowDialog() | Out-Null
