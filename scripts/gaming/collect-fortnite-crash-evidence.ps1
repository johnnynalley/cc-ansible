param(
    [int]$Days = 7,
    [int]$MaxEvents = 80,
    [int]$MaxLogMatches = 120,
    [int]$MaxCrashItems = 30
)

$ErrorActionPreference = "SilentlyContinue"
if (Get-Variable -Name Ansible -ErrorAction SilentlyContinue) {
    $Ansible.Changed = $false
}

function ConvertTo-IsoString {
    param($Value)
    if (-not $Value) {
        return $null
    }
    try {
        return ([datetime]$Value).ToString("o")
    } catch {
        return [string]$Value
    }
}

function Redact-Text {
    param([AllowNull()][string]$Text)
    if (-not $Text) {
        return $Text
    }
    $redacted = [string]$Text
    $rules = @(
        @{
            Pattern = '(?i)([-/]AUTH_(?:LOGIN|PASSWORD|TYPE)\s*=\s*)("[^"]+"|\S+)'
            Replacement = '${1}<redacted>'
        },
        @{
            Pattern = '(?i)([-/]caldera\s*=\s*)("[^"]+"|\S+)'
            Replacement = '${1}<redacted>'
        },
        @{
            Pattern = '(?i)((?:access_token|refresh_token|id_token|client_secret|sentry_key|api_key|apikey|password|token)=)([^&\s"]+)'
            Replacement = '${1}<redacted>'
        },
        @{
            Pattern = '(?i)((?:--|-|/)(?:access-token|refresh-token|id-token|client-secret|api-key|apikey|password|token)\s+)"[^"]+"'
            Replacement = '${1}"<redacted>"'
        },
        @{
            Pattern = '(?i)((?:--|-|/)(?:access-token|refresh-token|id-token|client-secret|api-key|apikey|password|token)\s+)\S+'
            Replacement = '${1}<redacted>'
        }
    )
    foreach ($rule in $rules) {
        $redacted = [regex]::Replace($redacted, [string]$rule.Pattern, [string]$rule.Replacement)
    }
    return $redacted
}

function Limit-Text {
    param(
        [AllowNull()][string]$Text,
        [int]$Length = 900
    )
    $value = Redact-Text -Text (($Text -replace "\s+", " ").Trim())
    if (-not $value) {
        return $value
    }
    if ($value.Length -le $Length) {
        return $value
    }
    return $value.Substring(0, $Length - 3) + "..."
}

function Get-RegistryValue {
    param(
        [string]$Path,
        [string]$Name
    )
    try {
        $item = Get-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction Stop
        return $item.$Name
    } catch {
        return $null
    }
}

function Get-FileRows {
    param(
        [string]$Path,
        [string]$Pattern,
        [int]$Limit
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    $matches = @(Select-String -LiteralPath $Path -Pattern $Pattern -ErrorAction SilentlyContinue | Select-Object -Last $Limit)
    return @($matches | ForEach-Object {
        [pscustomobject]@{
            Path = $_.Path
            LineNumber = $_.LineNumber
            Text = Limit-Text -Text $_.Line -Length 500
        }
    })
}

$start = (Get-Date).AddDays(-1 * $Days)
$eventPattern = "Fortnite|FortniteClient|EasyAntiCheat|EAC|Epic|Unreal|UECC|CrashReport|nvlddmkm|Display driver|LiveKernelEvent|RADAR|APPCRASH|BEX64|0xc0000005|0xc0000409|DXGI|DeviceRemoved|device removed|device hung|D3D"
$eventProviders = @(
    "Application Error",
    "Windows Error Reporting",
    "Application Hang",
    "Microsoft-Windows-WER-SystemErrorReporting",
    "Microsoft-Windows-Kernel-Power",
    "Microsoft-Windows-WHEA-Logger",
    "Display",
    "nvlddmkm",
    "EasyAntiCheat",
    "EasyAntiCheat_EOS"
)

$events = @(Get-WinEvent -FilterHashtable @{
    LogName = @("Application", "System")
    StartTime = $start
} -ErrorAction SilentlyContinue | Where-Object {
    $eventProviders -contains $_.ProviderName -or
    $_.Id -in @(41, 1000, 1001, 1002, 1005, 10010, 4101, 6008) -or
    $_.Message -match $eventPattern
} | Sort-Object TimeCreated -Descending | Select-Object -First $MaxEvents | ForEach-Object {
    [pscustomobject]@{
        TimeCreated = ConvertTo-IsoString $_.TimeCreated
        LogName = $_.LogName
        ProviderName = $_.ProviderName
        Id = $_.Id
        LevelDisplayName = $_.LevelDisplayName
        Message = Limit-Text -Text $_.Message
    }
})

$resourceExhaustionEvents = @(Get-WinEvent -FilterHashtable @{
    LogName = "System"
    ProviderName = "Microsoft-Windows-Resource-Exhaustion-Detector"
    StartTime = $start
} -ErrorAction SilentlyContinue | Sort-Object TimeCreated -Descending | Select-Object -First 20 | ForEach-Object {
    [pscustomobject]@{
        TimeCreated = ConvertTo-IsoString $_.TimeCreated
        Id = $_.Id
        LevelDisplayName = $_.LevelDisplayName
        Message = Limit-Text -Text $_.Message -Length 1200
    }
})

$reliability = @(Get-CimInstance Win32_ReliabilityRecords -ErrorAction SilentlyContinue | Where-Object {
    ([datetime]$_.TimeGenerated) -ge $start -and (
        $_.ProductName -match $eventPattern -or
        $_.SourceName -match $eventPattern -or
        $_.Message -match $eventPattern
    )
} | Sort-Object TimeGenerated -Descending | Select-Object -First $MaxEvents | ForEach-Object {
    [pscustomobject]@{
        TimeGenerated = ConvertTo-IsoString $_.TimeGenerated
        SourceName = $_.SourceName
        ProductName = $_.ProductName
        EventIdentifier = $_.EventIdentifier
        Message = Limit-Text -Text $_.Message
    }
})

$crashRoot = Join-Path $env:LOCALAPPDATA "FortniteGame\Saved\Crashes"
$logRoot = Join-Path $env:LOCALAPPDATA "FortniteGame\Saved\Logs"
$crashDumpRoot = Join-Path $env:LOCALAPPDATA "CrashDumps"
$werRoots = @(
    (Join-Path $env:LOCALAPPDATA "Microsoft\Windows\WER\ReportArchive"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\Windows\WER\ReportQueue"),
    (Join-Path $env:ProgramData "Microsoft\Windows\WER\ReportArchive"),
    (Join-Path $env:ProgramData "Microsoft\Windows\WER\ReportQueue")
)

$crashItems = @(Get-ChildItem -LiteralPath $crashRoot -Force -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First $MaxCrashItems |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            FullName = $_.FullName
            Type = if ($_.PSIsContainer) { "Directory" } else { "File" }
            LastWriteTime = ConvertTo-IsoString $_.LastWriteTime
            Length = if ($_.PSIsContainer) { $null } else { $_.Length }
        }
    })

$latestCrashDetails = @()
foreach ($item in @($crashItems | Where-Object { $_.Type -eq "Directory" } | Select-Object -First 5)) {
    $detailFiles = @(Get-ChildItem -LiteralPath $item.FullName -Force -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "CrashContext|Fortnite|diagnostic|report|\\.log$|\\.txt$|\\.runtime-xml$|\\.xml$" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10 |
        ForEach-Object {
            [pscustomobject]@{
                Name = $_.Name
                RelativePath = $_.FullName.Replace($item.FullName, "").TrimStart("\")
                LastWriteTime = ConvertTo-IsoString $_.LastWriteTime
                Length = $_.Length
            }
        })
    $detailMatches = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $item.FullName -Force -Recurse -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and $_.Length -lt 10MB -and $_.Name -match "CrashContext|Fortnite|\\.log$|\\.txt$|\\.runtime-xml$|\\.xml$" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 5)) {
        $detailMatches += @(Get-FileRows -Path $file.FullName -Pattern "(?i)(Fatal|Unhandled|Exception|EXCEPTION_|Crash|DXGI|DeviceRemoved|device removed|device hung|nvwgf2umx|D3D|GPU|EasyAntiCheat|EAC)" -Limit 20)
    }
    $latestCrashDetails += [pscustomobject]@{
        CrashDirectory = $item.FullName
        LastWriteTime = $item.LastWriteTime
        Files = $detailFiles
        Matches = $detailMatches
    }
}

$logs = @(Get-ChildItem -LiteralPath $logRoot -Force -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            FullName = $_.FullName
            LastWriteTime = ConvertTo-IsoString $_.LastWriteTime
            Length = $_.Length
        }
    })

$logMatches = @()
foreach ($log in @($logs | Select-Object -First 5)) {
    $logMatches += @(Get-FileRows -Path $log.FullName -Pattern "(?i)(Fatal error|Fatal|Unhandled|Exception|EXCEPTION_|DXGI_ERROR|DeviceRemoved|device removed|device hung|nvwgf2umx|EasyAntiCheat|EAC|Crash|GPU crash|stopped responding|D3D|Error:)" -Limit ([math]::Max(1, [math]::Floor($MaxLogMatches / 5))))
}

$dumps = @(Get-ChildItem -LiteralPath $crashDumpRoot -Force -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "Fortnite|Epic|EasyAntiCheat|EAC" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 20 |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            FullName = $_.FullName
            LastWriteTime = ConvertTo-IsoString $_.LastWriteTime
            Length = $_.Length
        }
    })

$werReports = @()
foreach ($root in $werRoots) {
    if (-not (Test-Path -LiteralPath $root)) {
        continue
    }
    $werReports += @(Get-ChildItem -LiteralPath $root -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "Fortnite|Epic|EasyAntiCheat|EAC|LiveKernelEvent" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 20 |
        ForEach-Object {
            [pscustomobject]@{
                Name = $_.Name
                FullName = $_.FullName
                LastWriteTime = ConvertTo-IsoString $_.LastWriteTime
            }
        })
}

$processPattern = "Fortnite|EasyAnti|Epic|Medal|Discord|Signal|iCUE|Corsair|RTSS|MSIAfterburner|Tracker|Overwolf|obs|SteelSeries|Nextcloud|nvcontainer|NVIDIA|firefox"
$processes = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match $processPattern } |
    Sort-Object ProcessName, Id |
    ForEach-Object {
        [pscustomobject]@{
            ProcessName = $_.ProcessName
            Id = $_.Id
            StartTime = ConvertTo-IsoString $_.StartTime
            CpuSeconds = if ($null -ne $_.CPU) { [math]::Round($_.CPU, 3) } else { $null }
            WorkingSetMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
            PrivateMemoryMB = [math]::Round($_.PrivateMemorySize64 / 1MB, 1)
            VirtualMemoryGB = [math]::Round($_.VirtualMemorySize64 / 1GB, 2)
            PagedMemoryMB = [math]::Round($_.PagedMemorySize64 / 1MB, 1)
            NonpagedSystemMemoryMB = [math]::Round($_.NonpagedSystemMemorySize64 / 1MB, 1)
            Threads = $_.Threads.Count
        }
    })

$topMemoryProcesses = @(Get-Process -ErrorAction SilentlyContinue |
    Sort-Object PrivateMemorySize64 -Descending |
    Select-Object -First 30 |
    ForEach-Object {
        [pscustomobject]@{
            ProcessName = $_.ProcessName
            ProcessId = $_.Id
            PrivateMemoryMB = [math]::Round($_.PrivateMemorySize64 / 1MB, 1)
            PagedMemoryMB = [math]::Round($_.PagedMemorySize64 / 1MB, 1)
            PeakPagedMemoryMB = [math]::Round($_.PeakPagedMemorySize64 / 1MB, 1)
            WorkingSetMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
            VirtualMemoryGB = [math]::Round($_.VirtualMemorySize64 / 1GB, 2)
            ThreadCount = $_.Threads.Count
            StartTime = ConvertTo-IsoString $_.StartTime
        }
    })

$driverPattern = "Signal|Corsair|RTCore|NTIOLib|inpout|cpuz|EasyAntiCheat|BEDaisy|vgk|Logi|LGHUB"
$drivers = @(Get-CimInstance Win32_SystemDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match $driverPattern -or $_.DisplayName -match $driverPattern -or $_.PathName -match $driverPattern } |
    Sort-Object State, Name |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            DisplayName = $_.DisplayName
            State = $_.State
            StartMode = $_.StartMode
            PathName = $_.PathName
        }
    })

$gpuDrivers = @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.DeviceName -match "NVIDIA|RTX|GeForce" } |
    Sort-Object DeviceName |
    ForEach-Object {
        [pscustomobject]@{
            DeviceName = $_.DeviceName
            DriverVersion = $_.DriverVersion
            DriverDate = ConvertTo-IsoString $_.DriverDate
            InfName = $_.InfName
            Manufacturer = $_.Manufacturer
        }
    })

$hotfixes = @(Get-HotFix -ErrorAction SilentlyContinue |
    Where-Object { $_.HotFixID -in @("KB5121003", "KB5120708", "KB5123304") -or ([datetime]$_.InstalledOn) -ge $start } |
    Sort-Object InstalledOn -Descending |
    ForEach-Object {
        [pscustomobject]@{
            HotFixID = $_.HotFixID
            Description = $_.Description
            InstalledOn = ConvertTo-IsoString $_.InstalledOn
            InstalledBy = $_.InstalledBy
        }
    })

$gameMode = [pscustomobject]@{
    AutoGameModeEnabled = Get-RegistryValue -Path "HKCU:\Software\Microsoft\GameBar" -Name "AutoGameModeEnabled"
    AllowAutoGameMode = Get-RegistryValue -Path "HKCU:\Software\Microsoft\GameBar" -Name "AllowAutoGameMode"
    AppCaptureEnabled = Get-RegistryValue -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR" -Name "AppCaptureEnabled"
    GameDvrEnabled = Get-RegistryValue -Path "HKCU:\System\GameConfigStore" -Name "GameDVR_Enabled"
}

$graphics = [pscustomobject]@{
    HagsHwSchMode = Get-RegistryValue -Path "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers" -Name "HwSchMode"
    DwmOverlayTestMode = Get-RegistryValue -Path "HKLM:\SOFTWARE\Microsoft\Windows\Dwm" -Name "OverlayTestMode"
    FortniteGpuPreference = Get-RegistryValue -Path "HKCU:\Software\Microsoft\DirectX\UserGpuPreferences" -Name "Z:\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe"
}

$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
$cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
$memory = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
$cDrive = Get-CimInstance Win32_LogicalDisk -Filter 'DeviceID="C:"' -ErrorAction SilentlyContinue
$memoryPerf = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory -ErrorAction SilentlyContinue
$pageFileSettings = @(Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{
        Name = $_.Name
        InitialSizeMB = $_.InitialSize
        MaximumSizeMB = $_.MaximumSize
    }
})
$pageFileUsage = @(Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{
        Name = $_.Name
        AllocatedBaseSizeMB = $_.AllocatedBaseSize
        CurrentUsageMB = $_.CurrentUsage
        PeakUsageMB = $_.PeakUsage
    }
})
$memoryManagement = [pscustomobject]@{
    PagingFiles = Get-RegistryValue -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management" -Name "PagingFiles"
    ExistingPageFiles = Get-RegistryValue -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management" -Name "ExistingPageFiles"
    AutomaticManagedPagefile = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).AutomaticManagedPagefile
}

[pscustomobject]@{
    Hostname = $env:COMPUTERNAME
    CollectedAt = (Get-Date).ToString("o")
    WindowStart = $start.ToString("o")
    Os = [pscustomobject]@{
        Caption = $os.Caption
        Version = $os.Version
        BuildNumber = $os.BuildNumber
        LastBootUpTime = ConvertTo-IsoString $os.LastBootUpTime
    }
    Cpu = [pscustomobject]@{
        Name = $cpu.Name
        NumberOfCores = $cpu.NumberOfCores
        NumberOfLogicalProcessors = $cpu.NumberOfLogicalProcessors
        MaxClockSpeedMHz = $cpu.MaxClockSpeed
    }
    Memory = [pscustomobject]@{
        TotalPhysicalGB = if ($memory.TotalPhysicalMemory) { [math]::Round($memory.TotalPhysicalMemory / 1GB, 2) } else { $null }
        AvailableMBytes = $memoryPerf.AvailableMBytes
        CommittedMBytes = if ($memoryPerf.CommittedBytes) { [math]::Round($memoryPerf.CommittedBytes / 1MB, 1) } else { $null }
        CommitLimitMBytes = if ($memoryPerf.CommitLimit) { [math]::Round($memoryPerf.CommitLimit / 1MB, 1) } else { $null }
        PagesPerSec = $memoryPerf.PagesPersec
    }
    CDrive = [pscustomobject]@{
        SizeGB = if ($cDrive.Size) { [math]::Round($cDrive.Size / 1GB, 1) } else { $null }
        FreeGB = if ($cDrive.FreeSpace) { [math]::Round($cDrive.FreeSpace / 1GB, 1) } else { $null }
    }
    PageFileSettings = $pageFileSettings
    PageFileUsage = $pageFileUsage
    MemoryManagement = $memoryManagement
    GameMode = $gameMode
    Graphics = $graphics
    GpuDrivers = $gpuDrivers
    HotFixes = $hotfixes
    RelevantProcesses = $processes
    TopMemoryProcesses = $topMemoryProcesses
    RelevantDrivers = $drivers
    Events = $events
    ResourceExhaustionEvents = $resourceExhaustionEvents
    Reliability = $reliability
    CrashRoot = $crashRoot
    CrashItems = $crashItems
    LatestCrashDetails = $latestCrashDetails
    Logs = $logs
    LogMatches = $logMatches
    CrashDumps = $dumps
    WerReports = $werReports
}
