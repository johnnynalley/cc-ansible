param(
  [string]$Profile = 'Untitled',
  [string]$SceneCollection = 'Untitled'
)

$ErrorActionPreference = 'Stop'

function Get-IniValue {
  param(
    [string]$Path,
    [string]$Section,
    [string]$Key
  )

  $inSection = $false
  foreach ($line in Get-Content -Path $Path) {
    if ($line.Trim() -eq "[$Section]") {
      $inSection = $true
      continue
    }

    if ($inSection -and $line -match '^\s*\[.+\]\s*$') {
      break
    }

    if ($inSection -and $line -match "^\s*$([regex]::Escape($Key))\s*=(.*)$") {
      return $Matches[1].Trim()
    }
  }

  return $null
}

$base = Join-Path $env:APPDATA 'obs-studio'
$profileDir = Join-Path $base "basic\profiles\$Profile"
$profilePath = Join-Path $profileDir 'basic.ini'
$servicePath = Join-Path $profileDir 'service.json'
$streamEncoderPath = Join-Path $profileDir 'streamEncoder.json'
$scenePath = Join-Path $base "basic\scenes\$SceneCollection.json"
$aitumPath = Join-Path $base 'plugin_config\vertical-canvas\config.json'

foreach ($requiredPath in @($profilePath, $streamEncoderPath, $scenePath)) {
  if (-not (Test-Path $requiredPath)) {
    throw "Required OBS config file is missing: $requiredPath"
  }
}

$scene = Get-Content -Raw -Path $scenePath | ConvertFrom-Json
$encoder = Get-Content -Raw -Path $streamEncoderPath | ConvertFrom-Json
if (Test-Path $servicePath) {
  $service = Get-Content -Raw -Path $servicePath | ConvertFrom-Json
}

Write-Output "obs_running=$([bool](Get-Process obs64 -ErrorAction SilentlyContinue))"
if ($service) {
  Write-Output "service_type=$($service.type)"
  Write-Output "service_server=$($service.settings.server)"
  Write-Output "service_key_present=$([bool]$service.settings.key)"
}
Write-Output "output_mode=$(Get-IniValue -Path $profilePath -Section 'Output' -Key 'Mode')"
Write-Output "encoder=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'Encoder')"
Write-Output "track_index=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'TrackIndex')"
Write-Output "vod_enabled=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'VodTrackEnabled')"
Write-Output "vod_track=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'VodTrackIndex')"
Write-Output "multi_track_audio_mixes=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'StreamMultiTrackAudioMixes')"
Write-Output "track1_bitrate=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'Track1Bitrate')"
Write-Output "track2_bitrate=$(Get-IniValue -Path $profilePath -Section 'AdvOut' -Key 'Track2Bitrate')"
Write-Output "stream_bitrate=$($encoder.bitrate)"

$sourceNames = @(
  'Stream Mix',
  'Apple Music Sonobus',
  'Game Capture',
  'MacBook Webcam'
)

foreach ($sourceName in $sourceNames) {
  $source = $scene.sources | Where-Object name -eq $sourceName | Select-Object -First 1
  if ($source) {
    Write-Output "source_mixer=$sourceName`:$($source.mixers)"
  } else {
    Write-Output "source_missing=$sourceName"
  }
}

if (Test-Path $aitumPath) {
  $aitum = Get-Content -Raw -Path $aitumPath | ConvertFrom-Json
  foreach ($canvas in $aitum.canvas) {
    Write-Output "aitum_canvas=$($canvas.name):stream_audio_track=$($canvas.stream_audio_track):audio_bitrate=$($canvas.audio_bitrate)"
  }
} else {
  Write-Output 'aitum_config=missing'
}

$mediaVmLanIp = '192.168.1.136'
$route = Find-NetRoute -RemoteIPAddress $mediaVmLanIp |
  Sort-Object RouteMetric, InterfaceMetric |
  Select-Object -First 1

if ($route) {
  $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
  Write-Output "media_vm_route_destination=$($route.DestinationPrefix)"
  Write-Output "media_vm_route_next_hop=$($route.NextHop)"
  Write-Output "media_vm_route_interface=$($adapter.Name)"
  Write-Output "media_vm_route_status=$($adapter.Status)"
  Write-Output "media_vm_route_link_speed=$($adapter.LinkSpeed)"
} else {
  Write-Output "media_vm_route=missing"
}
