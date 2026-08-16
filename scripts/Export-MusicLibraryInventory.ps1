<#
.SYNOPSIS
    Recursively inventories an audio library (e.g. a NAS folder tree of
    "recovered" DJ files) into a CSV, without touching Serato/Lexicon/
    Rekordbox at all.

.DESCRIPTION
    Walks -RootPath, and for every audio file found calls MediaInfo (a
    free, portable CLI tool — https://mediaarea.net/en/MediaInfo/Download)
    to read its real format/bitrate/duration/tags directly from the file
    header. Writes two files to -OutputDir:

      inventory.csv       One row per file. Columns are deliberately named
                           to match what the music-popularity-tagger CLI's
                           CSV loader expects (filename, artist, title,
                           playlist), so this file can be fed straight into
                           `tagger inventory.csv` with no conversion step.

      folder_summary.csv  One row per folder: file count, average bitrate,
                           % lossless, % at/below -LowBitrateThresholdKbps.
                           Sorted by file count descending, so the folders
                           that look like real curated sets/crates (lots of
                           files) surface first — a starting point for
                           "which folders are worth a closer look for a
                           wedding/party set".

    Deliberately does NOT touch Serato/Lexicon/Rekordbox — this is a
    read-only pass over the files themselves, so it can't create the kind
    of duplicate-detection mess a full re-import would.

.PARAMETER RootPath
    Folder to scan recursively (a UNC path like \\NAS\Music, a mapped
    drive like Z:\Music, or a local path all work).

.PARAMETER OutputDir
    Where to write inventory.csv and folder_summary.csv. Created if it
    doesn't exist. Defaults to .\music-inventory-output.

.PARAMETER MediaInfoPath
    Path to mediainfo.exe (or plain "mediainfo" if it's on PATH). The
    portable/no-install ZIP from mediaarea.net works fine — no admin
    rights or installer needed, which matters if you're running this
    against an old/locked-down box.

.PARAMETER Extensions
    Audio file extensions to include. Defaults cover the common DJ
    library formats.

.PARAMETER LowBitrateThresholdKbps
    Bitrate (kbps) at/below which an MP3 is flagged low_bitrate=true in
    the output — the "ban candidate" threshold. Defaults to 128.

.PARAMETER BatchSize
    How many files to hand to a single MediaInfo invocation. MediaInfo
    processes a whole batch in one process launch (much faster than one
    launch per file across a 12k-track library), but command lines have a
    length limit, so very long NAS paths need a smaller batch. Defaults to
    150; lower it if you see command-line-too-long errors.

.PARAMETER Limit
    Only process the first N files found — useful for a quick smoke test
    on a big library before committing to a full run.

.EXAMPLE
    .\Export-MusicLibraryInventory.ps1 -RootPath '\\NAS\Music\Recovered' -Limit 50

.EXAMPLE
    .\Export-MusicLibraryInventory.ps1 -RootPath 'Z:\DJ\Recovered' -OutputDir 'C:\Temp\inventory' -MediaInfoPath 'C:\Tools\MediaInfo\mediainfo.exe'
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RootPath,

    [string]$OutputDir = ".\music-inventory-output",

    [string]$MediaInfoPath = "mediainfo",

    [string[]]$Extensions = @("mp3", "flac", "wav", "aiff", "aif", "m4a", "alac", "ogg", "wma", "ape"),

    [int]$LowBitrateThresholdKbps = 128,

    [int]$BatchSize = 150,

    [int]$Limit
)

$ErrorActionPreference = "Stop"

# Without this, on a machine whose OS locale uses a comma as the decimal
# separator (e.g. French Windows), [math]::Round() results get stringified
# with a comma ("0,25") instead of a period ("0.25") when written to CSV —
# breaking any numeric parsing of duration_min/filesize_mb/etc downstream.
# Forcing invariant culture makes all number-to-string conversions in this
# script use "." regardless of the server's regional settings.
[System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::InvariantCulture
[System.Threading.Thread]::CurrentThread.CurrentUICulture = [System.Globalization.CultureInfo]::InvariantCulture

# Without this, accented characters (é, à, ç...) coming back from MediaInfo's
# stdout can get mis-decoded on Windows depending on the console's codepage —
# a classic PowerShell gotcha when capturing external process output. Since
# French track/folder names are very likely here, force UTF-8 explicitly.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    Write-Warning "Could not force UTF-8 console encoding; accented characters in tags may not come through correctly."
}

function Test-MediaInfoAvailable {
    param([string]$Path)
    $cmd = Get-Command -Name $Path -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "Can't find MediaInfo at '$Path'. Download the free CLI (no install needed) from " +
              "https://mediaarea.net/en/MediaInfo/Download and pass its path via -MediaInfoPath, " +
              "or put it on PATH."
    }
}

function Get-AudioFiles {
    param([string]$Root, [string[]]$Exts, [int]$MaxCount)
    $pattern = $Exts | ForEach-Object { "*.$_" }
    $files = Get-ChildItem -LiteralPath $Root -Recurse -File -Include $pattern -ErrorAction SilentlyContinue
    if ($MaxCount -and $MaxCount -gt 0) {
        $files = $files | Select-Object -First $MaxCount
    }
    return $files
}

# Tab-separated fields, newline-terminated records. MediaInfo interprets a
# literal "\n" in the template as a newline in its output; a real tab
# character (not the two-char "\t") is used as the field separator since
# MediaInfo does not interpret "\t" as an escape.
$Tab = "`t"
$InformFields = @(
    "%FileName%", "%FileExtension%", "%Format%", "%OverallBitRate%",
    "%Duration%", "%FileSize%", "%Performer%", "%Title%", "%Genre%", "%CompleteName%"
)
$InformTemplate = "General;" + ($InformFields -join $Tab) + "\n"

function Invoke-MediaInfoBatch {
    param([string[]]$Paths, [string]$MediaInfoExe, [string]$Template)
    $output = & $MediaInfoExe "--Inform=$Template" @Paths 2>$null
    return $output | Where-Object { $_ -and $_.Trim().Length -gt 0 }
}

function ConvertTo-InventoryRecord {
    param([string]$Line, [int]$LowBitrateThreshold)

    $parts = $Line -split $Tab
    if ($parts.Count -lt 10) { return $null }

    $baseName = $parts[0]
    $extension = $parts[1]
    $fileName = if ($extension) { "$baseName.$extension" } else { $baseName }
    $format = $parts[2]
    $bitRateRaw = $parts[3]
    $durationMsRaw = $parts[4]
    $fileSizeRaw = $parts[5]
    $performer = $parts[6]
    $title = $parts[7]
    $genre = $parts[8]
    $fullPath = $parts[9]

    $bitrateKbps = $null
    if ($bitRateRaw -match '^\d+$') { $bitrateKbps = [math]::Round([int64]$bitRateRaw / 1000) }

    $durationMin = $null
    if ($durationMsRaw -match '^\d+$') { $durationMin = [math]::Round([int64]$durationMsRaw / 60000, 2) }

    $fileSizeMB = $null
    if ($fileSizeRaw -match '^\d+$') { $fileSizeMB = [math]::Round([int64]$fileSizeRaw / 1MB, 2) }

    $isLossless = $format -in @("FLAC", "Wave", "WAV", "ALAC", "Monkey's Audio", "APE")
    $lowBitrate = (-not $isLossless) -and $bitrateKbps -and ($bitrateKbps -le $LowBitrateThreshold)

    $parentFolder = Split-Path -Path $fullPath -Parent

    [PSCustomObject]@{
        filename      = $fileName
        artist        = $performer
        title         = $title
        playlist      = Split-Path -Path $parentFolder -Leaf
        genre         = $genre
        format        = $format
        extension     = $extension
        bitrate_kbps  = $bitrateKbps
        duration_min  = $durationMin
        filesize_mb   = $fileSizeMB
        low_bitrate   = $lowBitrate
        full_path     = $fullPath
        parent_folder = $parentFolder
    }
}

function Split-IntoBatches {
    param([object[]]$Items, [int]$Size)
    $batches = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $Items.Count; $i += $Size) {
        $end = [Math]::Min($i + $Size, $Items.Count) - 1
        $batches.Add($Items[$i..$end])
    }
    return $batches
}

# --- Main ---

Test-MediaInfoAvailable -Path $MediaInfoPath

if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "Scanning $RootPath for audio files ($($Extensions -join ', '))..."
$files = Get-AudioFiles -Root $RootPath -Exts $Extensions -MaxCount $Limit
Write-Host "Found $($files.Count) files."

if ($files.Count -eq 0) {
    Write-Warning "No matching audio files found under $RootPath. Nothing to do."
    return
}

$paths = $files | ForEach-Object { $_.FullName }
$batches = Split-IntoBatches -Items $paths -Size $BatchSize

$records = New-Object System.Collections.Generic.List[object]
$batchNum = 0
foreach ($batch in $batches) {
    $batchNum++
    Write-Progress -Activity "Reading tags via MediaInfo" -Status "Batch $batchNum / $($batches.Count)" `
        -PercentComplete (($batchNum / $batches.Count) * 100)

    $lines = Invoke-MediaInfoBatch -Paths $batch -MediaInfoExe $MediaInfoPath -Template $InformTemplate
    foreach ($line in $lines) {
        $record = ConvertTo-InventoryRecord -Line $line -LowBitrateThreshold $LowBitrateThresholdKbps
        if ($record) { $records.Add($record) }
    }
}
Write-Progress -Activity "Reading tags via MediaInfo" -Completed

$inventoryPath = Join-Path $OutputDir "inventory.csv"
$records |
    Select-Object filename, artist, title, playlist, genre, format, extension, bitrate_kbps, duration_min, filesize_mb, low_bitrate, full_path |
    Export-Csv -Path $inventoryPath -NoTypeInformation -Encoding UTF8

Write-Host "Wrote $($records.Count) rows to $inventoryPath"

$summary = $records |
    Group-Object parent_folder |
    ForEach-Object {
        $group = $_.Group
        $bitrates = $group | Where-Object { $_.bitrate_kbps } | ForEach-Object { $_.bitrate_kbps }
        $losslessCount = ($group | Where-Object { $_.format -in @("FLAC", "Wave", "WAV", "ALAC", "Monkey's Audio", "APE") }).Count
        $lowBitrateCount = ($group | Where-Object { $_.low_bitrate }).Count

        [PSCustomObject]@{
            folder               = $_.Name
            file_count           = $group.Count
            avg_bitrate_kbps     = if ($bitrates.Count -gt 0) { [math]::Round(($bitrates | Measure-Object -Average).Average) } else { $null }
            pct_lossless         = [math]::Round(100 * $losslessCount / $group.Count, 1)
            pct_low_bitrate      = [math]::Round(100 * $lowBitrateCount / $group.Count, 1)
            total_size_mb        = [math]::Round((($group | Where-Object { $_.filesize_mb } | Measure-Object filesize_mb -Sum).Sum), 1)
        }
    } |
    Sort-Object file_count -Descending

$summaryPath = Join-Path $OutputDir "folder_summary.csv"
$summary | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8
Write-Host "Wrote $($summary.Count) folder summaries to $summaryPath"

$flagged = ($records | Where-Object { $_.low_bitrate }).Count
Write-Host ""
Write-Host "Summary: $($records.Count) files scanned, $flagged flagged as low_bitrate (<= ${LowBitrateThresholdKbps}kbps MP3)."
Write-Host "Next step: 'tagger $inventoryPath -o results.csv' feeds this straight into the popularity scoring."
