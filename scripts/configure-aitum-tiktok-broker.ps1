param(
  [string]$Server = 'rtmp://100.66.6.113:1936/live',
  [string]$StreamKey = 'vertical'
)

$base = Join-Path $env:APPDATA 'obs-studio'
$path = Join-Path $base 'plugin_config\vertical-canvas\config.json'

if (-not (Test-Path $path)) {
  Write-Output "aitum_config=missing"
  exit 1
}

$obs = Get-Process obs64 -ErrorAction SilentlyContinue
if ($obs) {
  Write-Output "closing_obs=true"
  $obs | Stop-Process -Force
  Start-Sleep -Seconds 2
} else {
  Write-Output "closing_obs=false"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$path.pre-tiktok-broker-$stamp.bak"
Copy-Item -Path $path -Destination $backup -Force

$json = Get-Content -Raw -Path $path | ConvertFrom-Json
for ($i = 0; $i -lt $json.canvas.Count; $i++) {
  $canvas = $json.canvas[$i]

  if ($canvas.PSObject.Properties.Name -contains 'streaming_match_main') {
    $canvas.streaming_match_main = $true
  }
  if ($canvas.PSObject.Properties.Name -contains 'streaming_video_bitrate') {
    $canvas.streaming_video_bitrate = 12000
  }
  if ($canvas.PSObject.Properties.Name -contains 'audio_bitrate') {
    $canvas.audio_bitrate = 160
  }
  if ($canvas.PSObject.Properties.Name -contains 'stream_audio_track') {
    $canvas.stream_audio_track = 0
  }
  if ($canvas.PSObject.Properties.Name -contains 'stream_encoder') {
    $canvas.stream_encoder = 'jim_nvenc'
  }
  if ($canvas.PSObject.Properties.Name -contains 'stream_encoder_settings') {
    if ($null -eq $canvas.stream_encoder_settings) {
      $canvas.stream_encoder_settings = [PSCustomObject]@{}
    }
    $canvas.stream_encoder_settings | Add-Member -NotePropertyName bitrate -NotePropertyValue 12000 -Force
  }

  if ($canvas.stream_outputs.Count -eq 0) {
    $canvas.stream_outputs += [PSCustomObject]@{
      name = 'media-vm TikTok Broker'
      stream_server = $Server
      stream_key = $StreamKey
      enabled = $true
    }
  } else {
    $canvas.stream_outputs[0].name = 'media-vm TikTok Broker'
    $canvas.stream_outputs[0].stream_server = $Server
    $canvas.stream_outputs[0].stream_key = $StreamKey
    $canvas.stream_outputs[0].enabled = $true
  }
}

$json | ConvertTo-Json -Depth 100 | Set-Content -Path $path -Encoding UTF8
Write-Output "aitum_backup=$backup"

$json = Get-Content -Raw -Path $path | ConvertFrom-Json
for ($i = 0; $i -lt $json.canvas.Count; $i++) {
  $canvas = $json.canvas[$i]
  Write-Output "canvas[$i].streaming_match_main=$($canvas.streaming_match_main)"
  Write-Output "canvas[$i].stream_encoder=$($canvas.stream_encoder)"
  Write-Output "canvas[$i].streaming_video_bitrate=$($canvas.streaming_video_bitrate)"
  Write-Output "canvas[$i].stream_audio_track=$($canvas.stream_audio_track)"
  Write-Output "canvas[$i].audio_bitrate=$($canvas.audio_bitrate)"

  for ($j = 0; $j -lt $canvas.stream_outputs.Count; $j++) {
    $output = $canvas.stream_outputs[$j]
    Write-Output "canvas[$i].stream_outputs[$j].name=$($output.name)"
    Write-Output "canvas[$i].stream_outputs[$j].enabled=$($output.enabled)"
    Write-Output "canvas[$i].stream_outputs[$j].server=$($output.stream_server)"
    if ($output.stream_key) {
      Write-Output "canvas[$i].stream_outputs[$j].key=present"
    } else {
      Write-Output "canvas[$i].stream_outputs[$j].key=missing"
    }
  }
}
