#Requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\{0\.0\.1\.00000000\}\.\{[0-9A-Fa-f-]{36}\}$')]
    [string]$EndpointId,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 30)]
    [int]$DurationSeconds,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ [IO.Path]::GetExtension($_) -ieq '.wav' })]
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$captureSource = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Codex.WasapiCapture
{
    internal enum DataFlow
    {
        Render = 0,
        Capture = 1,
        All = 2
    }

    internal enum Role
    {
        Console = 0,
        Multimedia = 1,
        Communications = 2
    }

    [Flags]
    internal enum DeviceState : uint
    {
        Active = 0x00000001
    }

    internal enum AudioClientShareMode
    {
        Shared = 0,
        Exclusive = 1
    }

    [Flags]
    internal enum AudioClientBufferFlags : uint
    {
        None = 0,
        DataDiscontinuity = 0x1,
        Silent = 0x2,
        TimestampError = 0x4
    }

    [Flags]
    internal enum ClassContext : uint
    {
        InprocServer = 0x1,
        InprocHandler = 0x2,
        LocalServer = 0x4,
        RemoteServer = 0x10,
        All = InprocServer | InprocHandler | LocalServer | RemoteServer
    }

    [ComImport]
    [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    internal class MMDeviceEnumeratorComObject
    {
    }

    [ComImport]
    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceEnumerator
    {
        [PreserveSig]
        int EnumAudioEndpoints(DataFlow dataFlow, DeviceState stateMask, out IMMDeviceCollection devices);

        [PreserveSig]
        int GetDefaultAudioEndpoint(DataFlow dataFlow, Role role, out IMMDevice device);

        [PreserveSig]
        int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string endpointId, out IMMDevice device);

        [PreserveSig]
        int RegisterEndpointNotificationCallback(IntPtr client);

        [PreserveSig]
        int UnregisterEndpointNotificationCallback(IntPtr client);
    }

    [ComImport]
    [Guid("0BD7A1BE-7A1A-44DB-8397-C0A3D9B2A62A")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceCollection
    {
        [PreserveSig]
        int GetCount(out uint count);

        [PreserveSig]
        int Item(uint index, out IMMDevice device);
    }

    [ComImport]
    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDevice
    {
        [PreserveSig]
        int Activate(
            [In] ref Guid interfaceId,
            ClassContext classContext,
            IntPtr activationParameters,
            [MarshalAs(UnmanagedType.IUnknown)] out object instance);

        [PreserveSig]
        int OpenPropertyStore(uint storageAccess, out IntPtr properties);

        [PreserveSig]
        int GetId([MarshalAs(UnmanagedType.LPWStr)] out string endpointId);

        [PreserveSig]
        int GetState(out DeviceState state);
    }

    [ComImport]
    [Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioClient
    {
        [PreserveSig]
        int Initialize(
            AudioClientShareMode shareMode,
            uint streamFlags,
            long bufferDuration,
            long periodicity,
            IntPtr format,
            IntPtr audioSessionGuid);

        [PreserveSig]
        int GetBufferSize(out uint bufferFrameCount);

        [PreserveSig]
        int GetStreamLatency(out long latency);

        [PreserveSig]
        int GetCurrentPadding(out uint currentPadding);

        [PreserveSig]
        int IsFormatSupported(AudioClientShareMode shareMode, IntPtr format, out IntPtr closestMatch);

        [PreserveSig]
        int GetMixFormat(out IntPtr format);

        [PreserveSig]
        int GetDevicePeriod(out long defaultPeriod, out long minimumPeriod);

        [PreserveSig]
        int Start();

        [PreserveSig]
        int Stop();

        [PreserveSig]
        int Reset();

        [PreserveSig]
        int SetEventHandle(IntPtr eventHandle);

        [PreserveSig]
        int GetService(
            [In] ref Guid interfaceId,
            [MarshalAs(UnmanagedType.IUnknown)] out object instance);
    }

    [ComImport]
    [Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioCaptureClient
    {
        [PreserveSig]
        int GetBuffer(
            out IntPtr data,
            out uint frames,
            out AudioClientBufferFlags flags,
            out ulong devicePosition,
            out ulong qpcPosition);

        [PreserveSig]
        int ReleaseBuffer(uint frames);

        [PreserveSig]
        int GetNextPacketSize(out uint frames);
    }

    public sealed class CaptureResult
    {
        public string EndpointId { get; set; }
        public string OutputPath { get; set; }
        public ushort FormatTag { get; set; }
        public ushort Channels { get; set; }
        public uint SampleRate { get; set; }
        public ushort BitsPerSample { get; set; }
        public ushort BlockAlign { get; set; }
        public ulong Frames { get; set; }
        public ulong DataBytes { get; set; }
        public int DiscontinuityPackets { get; set; }
        public int TimestampErrorPackets { get; set; }
    }

    public static class Recorder
    {
        private static readonly Guid AudioClientInterfaceId =
            new Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2");

        private static readonly Guid AudioCaptureClientInterfaceId =
            new Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317");

        public static CaptureResult Capture(string endpointId, int durationSeconds, string outputPath)
        {
            CaptureResult result = null;
            Exception failure = null;

            Thread captureThread = new Thread(delegate()
            {
                try
                {
                    result = CaptureCore(endpointId, durationSeconds, outputPath);
                }
                catch (Exception exception)
                {
                    failure = exception;
                }
            });

            captureThread.IsBackground = false;
            captureThread.SetApartmentState(ApartmentState.STA);
            captureThread.Start();
            captureThread.Join();

            if (failure != null)
            {
                throw new InvalidOperationException("WASAPI capture failed.", failure);
            }

            return result;
        }

        private static CaptureResult CaptureCore(string endpointId, int durationSeconds, string outputPath)
        {
            IMMDeviceEnumerator enumerator = null;
            IMMDevice device = null;
            IAudioClient audioClient = null;
            IAudioCaptureClient captureClient = null;
            object audioClientObject = null;
            object captureClientObject = null;
            IntPtr mixFormat = IntPtr.Zero;
            bool started = false;

            try
            {
                enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                CheckResult(enumerator.GetDevice(endpointId, out device), "IMMDeviceEnumerator.GetDevice");

                DeviceState deviceState;
                CheckResult(device.GetState(out deviceState), "IMMDevice.GetState");
                if ((deviceState & DeviceState.Active) == 0)
                {
                    throw new InvalidOperationException("The requested capture endpoint is not active.");
                }

                Guid audioClientId = AudioClientInterfaceId;
                CheckResult(
                    device.Activate(ref audioClientId, ClassContext.All, IntPtr.Zero, out audioClientObject),
                    "IMMDevice.Activate");
                audioClient = (IAudioClient)audioClientObject;

                CheckResult(audioClient.GetMixFormat(out mixFormat), "IAudioClient.GetMixFormat");

                ushort formatTag = unchecked((ushort)Marshal.ReadInt16(mixFormat, 0));
                ushort channels = unchecked((ushort)Marshal.ReadInt16(mixFormat, 2));
                uint sampleRate = unchecked((uint)Marshal.ReadInt32(mixFormat, 4));
                ushort blockAlign = unchecked((ushort)Marshal.ReadInt16(mixFormat, 12));
                ushort bitsPerSample = unchecked((ushort)Marshal.ReadInt16(mixFormat, 14));
                ushort extraSize = unchecked((ushort)Marshal.ReadInt16(mixFormat, 16));
                int formatSize = 18 + extraSize;

                if (channels == 0 || sampleRate == 0 || blockAlign == 0 || formatSize < 18 || formatSize > 256)
                {
                    throw new InvalidDataException("The endpoint returned an invalid shared-mode mix format.");
                }

                byte[] formatBytes = new byte[formatSize];
                Marshal.Copy(mixFormat, formatBytes, 0, formatBytes.Length);

                CheckResult(
                    audioClient.Initialize(
                        AudioClientShareMode.Shared,
                        0,
                        10000000,
                        0,
                        mixFormat,
                        IntPtr.Zero),
                    "IAudioClient.Initialize");

                Guid captureClientId = AudioCaptureClientInterfaceId;
                CheckResult(
                    audioClient.GetService(ref captureClientId, out captureClientObject),
                    "IAudioClient.GetService");
                captureClient = (IAudioCaptureClient)captureClientObject;

                string fullOutputPath = Path.GetFullPath(outputPath);
                string outputDirectory = Path.GetDirectoryName(fullOutputPath);
                if (String.IsNullOrWhiteSpace(outputDirectory) || !Directory.Exists(outputDirectory))
                {
                    throw new DirectoryNotFoundException("The WAV output directory does not exist.");
                }

                ulong totalFrames = 0;
                ulong totalDataBytes = 0;
                int discontinuityPackets = 0;
                int timestampErrorPackets = 0;

                using (FileStream stream = new FileStream(
                    fullOutputPath,
                    FileMode.CreateNew,
                    FileAccess.Write,
                    FileShare.Read))
                using (BinaryWriter writer = new BinaryWriter(stream, Encoding.ASCII, true))
                {
                    WriteFourCc(writer, "RIFF");
                    long riffSizePosition = stream.Position;
                    writer.Write((uint)0);
                    WriteFourCc(writer, "WAVE");
                    WriteFourCc(writer, "fmt ");
                    writer.Write((uint)formatBytes.Length);
                    writer.Write(formatBytes);
                    if ((formatBytes.Length & 1) != 0)
                    {
                        writer.Write((byte)0);
                    }

                    WriteFourCc(writer, "data");
                    long dataSizePosition = stream.Position;
                    writer.Write((uint)0);

                    CheckResult(audioClient.Start(), "IAudioClient.Start");
                    started = true;

                    Stopwatch stopwatch = Stopwatch.StartNew();
                    while (stopwatch.Elapsed < TimeSpan.FromSeconds(durationSeconds))
                    {
                        uint nextFrames;
                        CheckResult(
                            captureClient.GetNextPacketSize(out nextFrames),
                            "IAudioCaptureClient.GetNextPacketSize");

                        if (nextFrames == 0)
                        {
                            Thread.Sleep(2);
                            continue;
                        }

                        while (nextFrames > 0)
                        {
                            IntPtr data;
                            uint frames;
                            AudioClientBufferFlags flags;
                            ulong devicePosition;
                            ulong qpcPosition;

                            CheckResult(
                                captureClient.GetBuffer(
                                    out data,
                                    out frames,
                                    out flags,
                                    out devicePosition,
                                    out qpcPosition),
                                "IAudioCaptureClient.GetBuffer");

                            try
                            {
                                int byteCount = checked((int)(frames * blockAlign));
                                byte[] packet = new byte[byteCount];
                                if ((flags & AudioClientBufferFlags.Silent) == 0 && byteCount > 0)
                                {
                                    Marshal.Copy(data, packet, 0, byteCount);
                                }

                                writer.Write(packet);
                                totalFrames += frames;
                                totalDataBytes += unchecked((uint)byteCount);

                                if ((flags & AudioClientBufferFlags.DataDiscontinuity) != 0)
                                {
                                    discontinuityPackets++;
                                }

                                if ((flags & AudioClientBufferFlags.TimestampError) != 0)
                                {
                                    timestampErrorPackets++;
                                }
                            }
                            finally
                            {
                                CheckResult(
                                    captureClient.ReleaseBuffer(frames),
                                    "IAudioCaptureClient.ReleaseBuffer");
                            }

                            CheckResult(
                                captureClient.GetNextPacketSize(out nextFrames),
                                "IAudioCaptureClient.GetNextPacketSize");
                        }
                    }

                    CheckResult(audioClient.Stop(), "IAudioClient.Stop");
                    started = false;

                    writer.Flush();
                    long fileLength = stream.Length;
                    if (totalDataBytes > UInt32.MaxValue || fileLength - 8 > UInt32.MaxValue)
                    {
                        throw new InvalidDataException("The capture is too large for a RIFF/WAVE file.");
                    }

                    stream.Position = riffSizePosition;
                    writer.Write((uint)(fileLength - 8));
                    stream.Position = dataSizePosition;
                    writer.Write((uint)totalDataBytes);
                    writer.Flush();
                }

                return new CaptureResult
                {
                    EndpointId = endpointId,
                    OutputPath = fullOutputPath,
                    FormatTag = formatTag,
                    Channels = channels,
                    SampleRate = sampleRate,
                    BitsPerSample = bitsPerSample,
                    BlockAlign = blockAlign,
                    Frames = totalFrames,
                    DataBytes = totalDataBytes,
                    DiscontinuityPackets = discontinuityPackets,
                    TimestampErrorPackets = timestampErrorPackets
                };
            }
            finally
            {
                if (started && audioClient != null)
                {
                    audioClient.Stop();
                }

                if (mixFormat != IntPtr.Zero)
                {
                    Marshal.FreeCoTaskMem(mixFormat);
                }

                ReleaseComObject(captureClientObject);
                ReleaseComObject(audioClientObject);
                ReleaseComObject(device);
                ReleaseComObject(enumerator);
            }
        }

        private static void CheckResult(int result, string operation)
        {
            if (result < 0)
            {
                throw new COMException(operation + " failed.", result);
            }
        }

        private static void ReleaseComObject(object instance)
        {
            if (instance != null && Marshal.IsComObject(instance))
            {
                Marshal.FinalReleaseComObject(instance);
            }
        }

        private static void WriteFourCc(BinaryWriter writer, string value)
        {
            byte[] bytes = Encoding.ASCII.GetBytes(value);
            if (bytes.Length != 4)
            {
                throw new ArgumentException("A RIFF FourCC must be exactly four ASCII bytes.");
            }

            writer.Write(bytes);
        }
    }
}
'@

if (-not ('Codex.WasapiCapture.Recorder' -as [type])) {
    Add-Type -TypeDefinition $captureSource -Language CSharp
}

$captureResult = [Codex.WasapiCapture.Recorder]::Capture(
    $EndpointId,
    $DurationSeconds,
    $OutputPath
)

$captureResult | ConvertTo-Json -Compress
