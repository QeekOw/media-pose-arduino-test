# Convert the downloaded stock clips in clips-raw/ into the five Clips in clips/, then verify them.
# Name each download after its situation: front, side, fast, far, empty (any video extension).
#   .\scripts\prepare-clips.ps1
# Output is 1280x720, 30 fps, H.264, no audio, at most 30 s. A source shorter than 20 s is rejected.
# A source that is not 16:9 is scaled to fill and centre-cropped.
. "$PSScriptRoot\board.ps1"

$Situations = "front", "side", "fast", "far", "empty"
$MinSeconds = 20
$MaxSeconds = 30
$RawDir = "$RepoRoot\clips-raw"
$OutDir = "$RepoRoot\clips"

function Get-VideoInfo([string]$Path) {
    $json = & ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate -show_entries format=duration -of json $Path
    if ($LASTEXITCODE -ne 0) { throw "ffprobe failed on $Path" }
    $info = $json | ConvertFrom-Json
    $s = $info.streams[0]
    [pscustomobject]@{
        Codec    = $s.codec_name
        Width    = [int]$s.width
        Height   = [int]$s.height
        Fps      = $s.r_frame_rate
        Duration = [double]$info.format.duration
    }
}

New-Item -ItemType Directory -Force $RawDir, $OutDir | Out-Null

foreach ($name in $Situations) {
    $source = Get-ChildItem $RawDir -File | Where-Object { $_.BaseName -eq $name } | Select-Object -First 1
    if (-not $source) { Write-Warning "no source for '$name' in clips-raw/"; continue }
    $duration = (Get-VideoInfo $source.FullName).Duration
    if ($duration -lt $MinSeconds) {
        throw "$($source.Name) is $([math]::Round($duration, 1)) s; pick a source of at least $MinSeconds s"
    }
    Invoke-Native ffmpeg -y -v error -i $source.FullName -t $MaxSeconds -an `
        -vf "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=30" `
        "-c:v" libx264 -pix_fmt yuv420p -preset medium -crf 20 -movflags +faststart "$OutDir\$name.mp4"
}

$failed = @()
$report = foreach ($name in $Situations) {
    $path = "$OutDir\$name.mp4"
    if (-not (Test-Path $path)) { $failed += "$name.mp4 is missing"; continue }
    $v = Get-VideoInfo $path
    $problems = @()
    if ($v.Codec -ne "h264") { $problems += "codec $($v.Codec)" }
    if ($v.Width -ne 1280 -or $v.Height -ne 720) { $problems += "size $($v.Width)x$($v.Height)" }
    if ($v.Fps -ne "30/1") { $problems += "fps $($v.Fps)" }
    if ($v.Duration -lt $MinSeconds -or $v.Duration -gt $MaxSeconds + 0.1) { $problems += "duration $($v.Duration)" }
    if ($problems) { $failed += "$name.mp4: $($problems -join ', ')" }
    [pscustomobject]@{
        Clip     = "$name.mp4"
        Size     = "$($v.Width)x$($v.Height)"
        Fps      = $v.Fps
        Codec    = $v.Codec
        Duration = [math]::Round($v.Duration, 1)
        Result   = if ($problems) { "FAIL" } else { "ok" }
    }
}
$report | Format-Table -AutoSize | Out-String | Write-Host
if ($failed) { throw "clip check failed:`n$($failed -join "`n")" }
Write-Host "All five Clips verified."
