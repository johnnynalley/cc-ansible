Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scenePath = Join-Path $env:APPDATA 'obs-studio\basic\scenes\Untitled.json'
$profilePath = Join-Path $env:APPDATA 'obs-studio\basic\profiles\Untitled\basic.ini'

$sourceName = 'MacBook Apple Music'
$ndiSourceName = 'JOHNNYS-MACBOOK-PRO (MacBook Apple Music)'
$sceneNames = @(
  'Streaming (Mic on, desktop audio)'
)
$monitoringDeviceName = 'SteelSeries Sonar - Media'
$monitoringDeviceId = '{0.0.0.00000000}.{415788a6-95ac-4475-be0f-232b484ce6c4}'

if (-not (Test-Path $scenePath)) {
  throw "OBS scene collection not found: $scenePath"
}
if (-not (Test-Path $profilePath)) {
  throw "OBS profile not found: $profilePath"
}

$obs = Get-Process obs64 -ErrorAction SilentlyContinue
if ($obs) {
  Write-Output 'closing_obs=true'
  $obs | Stop-Process -Force
  Start-Sleep -Seconds 2
} else {
  Write-Output 'closing_obs=false'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$sceneBackup = "$scenePath.pre-apple-music-ndi-$stamp.bak"
$profileBackup = "$profilePath.pre-apple-music-ndi-$stamp.bak"
Copy-Item -Path $scenePath -Destination $sceneBackup -Force
Copy-Item -Path $profilePath -Destination $profileBackup -Force

$collection = Get-Content -Path $scenePath -Raw | ConvertFrom-Json

function New-ObsSource {
  param(
    [string]$Name,
    [string]$Id,
    [object]$Settings
  )

  [ordered]@{
    balance = 0.5
    deinterlace_field_order = 0
    deinterlace_mode = 0
    enabled = $true
    flags = 0
    hotkeys = [ordered]@{
      'libobs.mute' = @()
      'libobs.push-to-mute' = @()
      'libobs.push-to-talk' = @()
      'libobs.unmute' = @()
    }
    id = $Id
    mixers = 0
    monitoring_type = 1
    muted = $false
    name = $Name
    prev_ver = 536936450
    private_settings = [ordered]@{}
    'push-to-mute' = $false
    'push-to-mute-delay' = 0
    'push-to-talk' = $false
    'push-to-talk-delay' = 0
    settings = $Settings
    sync = 0
    uuid = ([guid]::NewGuid().ToString())
    versioned_id = $Id
    volume = 1.0
  }
}

function New-SceneItem {
  param(
    [object]$Source,
    [int]$Id
  )

  [ordered]@{
    name = $Source.name
    source_uuid = $Source.uuid
    visible = $true
    locked = $true
    rot = 0.0
    scale_ref = [ordered]@{ x = 1920.0; y = 1080.0 }
    align = 5
    bounds_type = 0
    bounds_align = 0
    bounds_crop = $false
    crop_left = 0
    crop_top = 0
    crop_right = 0
    crop_bottom = 0
    id = $Id
    group_item_backup = $false
    pos = [ordered]@{ x = 0.0; y = 0.0 }
    pos_rel = [ordered]@{ x = -1.7777777910232544; y = -1.0 }
    scale = [ordered]@{ x = 1.0; y = 1.0 }
    scale_rel = [ordered]@{ x = 1.0; y = 1.0 }
    bounds = [ordered]@{ x = 0.0; y = 0.0 }
    bounds_rel = [ordered]@{ x = 0.0; y = 0.0 }
    scale_filter = 'disable'
    blend_method = 'default'
    blend_type = 'normal'
    show_transition = [ordered]@{ duration = 300 }
    hide_transition = [ordered]@{ duration = 300 }
    private_settings = [ordered]@{}
  }
}

$sources = @($collection.sources)
$musicSource = $sources | Where-Object { $_.name -eq $sourceName } | Select-Object -First 1

if (-not $musicSource) {
  $settings = [ordered]@{
    ndi_fix_alpha_blending = $false
    ndi_source_name = $ndiSourceName
    ndi_recv_hw_accel = $true
  }
  $musicSource = [pscustomobject](New-ObsSource -Name $sourceName -Id 'ndi_source' -Settings $settings)
  $sources += $musicSource
  Write-Output 'music_source=created'
} else {
  $musicSource.id = 'ndi_source'
  $musicSource.versioned_id = 'ndi_source'
  $musicSource.monitoring_type = 1
  $musicSource.muted = $false
  $musicSource.mixers = 0
  if (-not $musicSource.settings) {
    $musicSource | Add-Member -MemberType NoteProperty -Name settings -Value ([pscustomobject]@{}) -Force
  }
  $musicSource.settings | Add-Member -MemberType NoteProperty -Name ndi_source_name -Value $ndiSourceName -Force
  $musicSource.settings | Add-Member -MemberType NoteProperty -Name ndi_recv_hw_accel -Value $true -Force
  $musicSource.settings | Add-Member -MemberType NoteProperty -Name ndi_fix_alpha_blending -Value $false -Force
  Write-Output 'music_source=updated'
}

foreach ($sceneName in $sceneNames) {
  $scene = $sources | Where-Object { $_.name -eq $sceneName -and $_.id -eq 'scene' } | Select-Object -First 1
  if (-not $scene) {
    Write-Output "scene_missing=$sceneName"
    continue
  }

  $items = @($scene.settings.items)
  $alreadyPresent = $items | Where-Object { $_.source_uuid -eq $musicSource.uuid } | Select-Object -First 1
  if ($alreadyPresent) {
    $alreadyPresent.visible = $true
    $alreadyPresent.locked = $true
    Write-Output "scene_item=present scene=$sceneName"
    continue
  }

  $nextId = [int]$scene.settings.id_counter + 1
  $items += [pscustomobject](New-SceneItem -Source $musicSource -Id $nextId)
  $scene.settings.items = $items
  $scene.settings.id_counter = $nextId
  Write-Output "scene_item=created scene=$sceneName"
}

$collection.sources = $sources
$collection | ConvertTo-Json -Depth 100 | Set-Content -Path $scenePath -Encoding UTF8

$profile = Get-Content -Path $profilePath -Raw
$profile = [regex]::Replace($profile, '(?m)^MonitoringDeviceId=.*$', "MonitoringDeviceId=$monitoringDeviceId")
$profile = [regex]::Replace($profile, '(?m)^MonitoringDeviceName=.*$', "MonitoringDeviceName=$monitoringDeviceName")
Set-Content -Path $profilePath -Value $profile -Encoding UTF8

Write-Output "scene_backup=$sceneBackup"
Write-Output "profile_backup=$profileBackup"
