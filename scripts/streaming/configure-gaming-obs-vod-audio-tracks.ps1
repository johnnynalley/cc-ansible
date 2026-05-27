param(
  [string]$Profile = 'Untitled',
  [string]$SceneCollection = 'Untitled',
  [int]$StreamBitrateKbps = 12000,
  [int]$AudioBitrateKbps = 160
)

$ErrorActionPreference = 'Stop'

function Set-IniValue {
  param(
    [string]$Path,
    [string]$Section,
    [string]$Key,
    [string]$Value
  )

  $lines = [System.Collections.Generic.List[string]]::new()
  if (Test-Path $Path) {
    foreach ($line in Get-Content -Path $Path) {
      [void]$lines.Add($line)
    }
  }

  $sectionHeader = "[$Section]"
  $sectionIndex = -1
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Trim() -eq $sectionHeader) {
      $sectionIndex = $i
      break
    }
  }

  if ($sectionIndex -lt 0) {
    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim() -ne '') {
      [void]$lines.Add('')
    }
    [void]$lines.Add($sectionHeader)
    [void]$lines.Add("${Key}=${Value}")
    Set-Content -Path $Path -Value $lines -Encoding UTF8
    return
  }

  $insertIndex = $lines.Count
  for ($i = $sectionIndex + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*\[.+\]\s*$') {
      $insertIndex = $i
      break
    }

    if ($lines[$i] -match "^\s*$([regex]::Escape($Key))\s*=") {
      $lines[$i] = "${Key}=${Value}"
      Set-Content -Path $Path -Value $lines -Encoding UTF8
      return
    }
  }

  $lines.Insert($insertIndex, "${Key}=${Value}")
  Set-Content -Path $Path -Value $lines -Encoding UTF8
}

function Copy-IfPresent {
  param(
    [string]$Path,
    [string]$DestinationRoot
  )

  if (Test-Path $Path) {
    Copy-Item -Path $Path -Destination (Join-Path $DestinationRoot (Split-Path -Leaf $Path)) -Force
  }
}

$obs = Get-Process obs64 -ErrorAction SilentlyContinue
if ($obs) {
  throw 'OBS is running. Close OBS before editing profile and scene JSON.'
}

$base = Join-Path $env:APPDATA 'obs-studio'
$profileDir = Join-Path $base "basic\profiles\$Profile"
$scenePath = Join-Path $base "basic\scenes\$SceneCollection.json"
$globalPath = Join-Path $base 'global.ini'
$profilePath = Join-Path $profileDir 'basic.ini'
$streamEncoderPath = Join-Path $profileDir 'streamEncoder.json'
$aitumPath = Join-Path $base 'plugin_config\vertical-canvas\config.json'

foreach ($requiredPath in @($globalPath, $profilePath, $scenePath, $streamEncoderPath)) {
  if (-not (Test-Path $requiredPath)) {
    throw "Required OBS config file is missing: $requiredPath"
  }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $env:LOCALAPPDATA "CodexBackups\obs-vod-audio-$stamp"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
Copy-IfPresent -Path $globalPath -DestinationRoot $backupRoot
Copy-IfPresent -Path $profilePath -DestinationRoot $backupRoot
Copy-IfPresent -Path $streamEncoderPath -DestinationRoot $backupRoot
Copy-IfPresent -Path $scenePath -DestinationRoot $backupRoot
Copy-IfPresent -Path $aitumPath -DestinationRoot $backupRoot

Set-IniValue -Path $globalPath -Section 'General' -Key 'EnableCustomServerVodTrack' -Value 'true'

Set-IniValue -Path $profilePath -Section 'Output' -Key 'Mode' -Value 'Advanced'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'Encoder' -Value 'obs_nvenc_h264_tex'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'ApplyServiceSettings' -Value 'true'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'TrackIndex' -Value '1'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'VodTrackEnabled' -Value 'true'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'VodTrackIndex' -Value '2'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'StreamMultiTrackAudioMixes' -Value '3'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'AudioEncoder' -Value 'ffmpeg_aac'
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'Track1Bitrate' -Value "$AudioBitrateKbps"
Set-IniValue -Path $profilePath -Section 'AdvOut' -Key 'Track2Bitrate' -Value "$AudioBitrateKbps"

$encoderSettings = [ordered]@{
  rate_control = 'CBR'
  bitrate = $StreamBitrateKbps
  max_bitrate = $StreamBitrateKbps
  keyint_sec = 2
  preset = 'p5'
  tune = 'hq'
  multipass = 'qres'
  profile = 'high'
  lookahead = $false
  adaptive_quantization = $true
  bf = 2
  bframe_ref_mode = 0
  device = -1
}
$encoderSettings | ConvertTo-Json -Depth 10 | Set-Content -Path $streamEncoderPath -Encoding UTF8

$scene = Get-Content -Raw -Path $scenePath | ConvertFrom-Json
$trackAssignments = @{
  'Game Capture' = 3
  'MacBook Webcam' = 3
  'Stream Mix' = 3
  'Apple Music Sonobus' = 1
}
$seen = @{}

foreach ($source in $scene.sources) {
  if ($trackAssignments.ContainsKey($source.name)) {
    $source.mixers = [int]$trackAssignments[$source.name]
    $seen[$source.name] = $true
  }
}

foreach ($sourceName in $trackAssignments.Keys) {
  if (-not $seen.ContainsKey($sourceName)) {
    Write-Output "warning=source_missing:$sourceName"
  }
}

foreach ($deviceName in @('DesktopAudioDevice1', 'AuxAudioDevice1')) {
  if ($scene.PSObject.Properties.Name -contains $deviceName -and $null -ne $scene.$deviceName) {
    $scene.$deviceName.mixers = 3
  }
}

$scene | ConvertTo-Json -Depth 100 | Set-Content -Path $scenePath -Encoding UTF8

if (Test-Path $aitumPath) {
  $aitum = Get-Content -Raw -Path $aitumPath | ConvertFrom-Json
  foreach ($canvas in $aitum.canvas) {
    if ($canvas.PSObject.Properties.Name -contains 'stream_audio_track') {
      $canvas.stream_audio_track = 0
    }
    if ($canvas.PSObject.Properties.Name -contains 'audio_bitrate') {
      $canvas.audio_bitrate = $AudioBitrateKbps
    }
  }
  $aitum | ConvertTo-Json -Depth 100 | Set-Content -Path $aitumPath -Encoding UTF8
}

Write-Output "backup=$backupRoot"
Write-Output "output_mode=Advanced"
Write-Output "stream_encoder=obs_nvenc_h264_tex"
Write-Output "stream_bitrate_kbps=$StreamBitrateKbps"
Write-Output "track1=full_music"
Write-Output "track2=clean_no_apple_music"
Write-Output "landscape_stream_tracks=1,2"
Write-Output "twitch_vod_track=2"
Write-Output "aitum_stream_audio_track=0_obs_track_1"
