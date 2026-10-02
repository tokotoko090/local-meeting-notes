import AppKit
import AVFoundation
import CoreAudio
import CoreMedia
import ScreenCaptureKit

func emit(_ payload: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) {
        print(text)
        fflush(stdout)
    }
}

struct CaptureFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

func microphoneDevices() -> [AVCaptureDevice] {
    AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external],
                                    mediaType: .audio, position: .unspecified).devices
        .sorted { $0.uniqueID < $1.uniqueID }
}

func permissions() -> [String: Any] {
    let status = AVCaptureDevice.authorizationStatus(for: .audio)
    let mic = status == .authorized ? "granted" : status == .notDetermined ? "not_determined" : "denied"
    return ["ok": true, "microphone": mic,
            "system_audio": CGPreflightScreenCaptureAccess() ? "granted" : "picker_required"]
}

final class CapturePicker: NSObject, SCContentSharingPickerObserver, @unchecked Sendable {
    private var continuation: CheckedContinuation<SCContentFilter, Error>?
    @MainActor func select(shouldStop: @escaping @Sendable () -> Bool) async throws -> SCContentFilter {
        NSApplication.shared.setActivationPolicy(.accessory)
        NSApplication.shared.finishLaunching()
        let picker = SCContentSharingPicker.shared
        var configuration = SCContentSharingPickerConfiguration()
        configuration.allowedPickerModes = [.singleDisplay]
        configuration.allowsChangingSelectedContent = false
        picker.defaultConfiguration = configuration
        picker.add(self)
        picker.isActive = true
        let cancellation = Task { @MainActor in
            while !Task.isCancelled {
                if shouldStop() {
                    picker.isActive = false
                    self.finish(.failure(CaptureFailure(message: "録音開始前に停止しました。")))
                    return
                }
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
        }
        defer { cancellation.cancel() }
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            picker.present(using: .display)
        }
    }
    private func finish(_ result: Result<SCContentFilter, Error>) {
        DispatchQueue.main.async {
            guard let continuation = self.continuation else { return }
            self.continuation = nil
            SCContentSharingPicker.shared.remove(self)
            continuation.resume(with: result)
        }
    }
    func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
        finish(.failure(CaptureFailure(message: "録音対象の選択をキャンセルしました。")))
    }
    func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter, for stream: SCStream?) {
        finish(.success(filter))
    }
    func contentSharingPickerStartDidFailWithError(_ error: Error) { finish(.failure(error)) }
}

// Both tracks are mono PCM16 at 48 kHz. Absolute host-clock sample timestamps
// supply leading silence and fill gaps, so transcript offsets share one origin.
final class WaveTrack {
    let handle: FileHandle
    let epoch: Double
    let rate: Double = 48_000
    var frames: Int64 = 0
    var receivedFrames: Int64 = 0
    var audible = false
    var converter: AVAudioConverter?
    var inputFormat: AVAudioFormat?
    let outputFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48_000,
                                    channels: 1, interleaved: false)!

    init(url: URL, epoch: Double) throws {
        self.epoch = epoch
        FileManager.default.createFile(atPath: url.path, contents: nil)
        handle = try FileHandle(forWritingTo: url)
        try handle.write(contentsOf: Data(repeating: 0, count: 44))
    }

    func pad(to target: Int64) throws {
        while frames < target {
            let count = Int(min(target - frames, 48_000))
            try append(Data(repeating: 0, count: count * 2), count: count)
        }
    }

    func append(_ data: Data, count: Int) throws {
        guard (frames + Int64(count)) * 2 < Int64(UInt32.max) - 36 else {
            throw CaptureFailure(message: "録音がWAVのサイズ上限に達しました。保存して新しい録音を開始してください。")
        }
        try handle.write(contentsOf: data)
        frames += Int64(count)
    }

    func write(_ sample: CMSampleBuffer) throws {
        guard CMSampleBufferDataIsReady(sample),
              let description = CMSampleBufferGetFormatDescription(sample) else { return }
        let format = AVAudioFormat(cmAudioFormatDescription: description)
        guard let pcm = AVAudioPCMBuffer(pcmFormat: format,
                                        frameCapacity: AVAudioFrameCount(CMSampleBufferGetNumSamples(sample))) else { return }
        pcm.frameLength = pcm.frameCapacity
        var size = 0
        var retained: CMBlockBuffer?
        let measured = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sample, bufferListSizeNeededOut: &size, bufferListOut: nil, bufferListSize: 0,
            blockBufferAllocator: kCFAllocatorDefault, blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: UInt32(kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment), blockBufferOut: &retained)
        guard measured == noErr, size > 0 else { throw CaptureFailure(message: "音声バッファのサイズを取得できません: \(measured)") }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: size, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        let list = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        let result = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sample, bufferListSizeNeededOut: nil, bufferListOut: list, bufferListSize: size,
            blockBufferAllocator: kCFAllocatorDefault, blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: UInt32(kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment), blockBufferOut: &retained)
        guard result == noErr else { throw CaptureFailure(message: "音声バッファの読み取りに失敗しました: \(result)") }
        let source = UnsafeMutableAudioBufferListPointer(list)
        let destination = UnsafeMutableAudioBufferListPointer(pcm.mutableAudioBufferList)
        guard source.count == destination.count else { throw CaptureFailure(message: "未対応の音声形式です。") }
        for index in 0..<source.count {
            guard let src = source[index].mData, let dst = destination[index].mData,
                  source[index].mDataByteSize <= destination[index].mDataByteSize else {
                throw CaptureFailure(message: "音声バッファのサイズが一致しません。")
            }
            memcpy(dst, src, Int(source[index].mDataByteSize))
        }
        if inputFormat != format {
            converter = AVAudioConverter(from: format, to: outputFormat)
            inputFormat = format
        }
        guard let converter,
              let output = AVAudioPCMBuffer(pcmFormat: outputFormat,
                frameCapacity: AVAudioFrameCount(ceil(Double(pcm.frameLength) * rate / format.sampleRate)) + 64) else {
            throw CaptureFailure(message: "音声形式を変換できません。")
        }
        var supplied = false
        var error: NSError?
        converter.convert(to: output, error: &error) { _, status in
            if supplied { status.pointee = .noDataNow; return nil }
            supplied = true
            status.pointee = .haveData
            return pcm
        }
        if let error { throw error }
        guard let samples = output.floatChannelData?[0] else { return }
        let timestamp = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample))
        guard timestamp.isFinite, abs(timestamp - epoch) < 7 * 24 * 3600 else {
            throw CaptureFailure(message: "録音の時刻を同期できません。")
        }
        let start = Int64(((timestamp - epoch) * rate).rounded())
        let skip = Int(min(Int64(output.frameLength), max(0, frames - start)))
        try pad(to: max(0, start))
        let count = Int(output.frameLength) - skip
        guard count > 0 else { return }
        var bytes = Data(capacity: count * 2)
        for index in skip..<Int(output.frameLength) {
            let value = samples[index].isFinite ? max(-1, min(1, samples[index])) : 0
            if abs(value) > 0.0001 { audible = true }
            var integer = Int16((value * 32767).rounded()).littleEndian
            withUnsafeBytes(of: &integer) { bytes.append(contentsOf: $0) }
        }
        try append(bytes, count: count)
        receivedFrames += Int64(count)
    }

    func finish(duration: Double) throws {
        defer { try? handle.close() }
        var paddingError: Error?
        do { try pad(to: Int64((duration * rate).rounded())) } catch { paddingError = error }
        var header = Data()
        func ascii(_ text: String) { header.append(contentsOf: text.utf8) }
        func u32(_ value: UInt32) { var n = value.littleEndian; withUnsafeBytes(of: &n) { header.append(contentsOf: $0) } }
        func u16(_ value: UInt16) { var n = value.littleEndian; withUnsafeBytes(of: &n) { header.append(contentsOf: $0) } }
        ascii("RIFF"); u32(UInt32(frames * 2 + 36)); ascii("WAVEfmt "); u32(16)
        u16(1); u16(1); u32(48_000); u32(96_000); u16(2); u16(16)
        ascii("data"); u32(UInt32(frames * 2))
        try handle.seek(toOffset: 0)
        try handle.write(contentsOf: header)
        try handle.synchronize()
        if let paddingError { throw paddingError }
    }
}

// Mutable capture state is confined to queue while a stream is running.
final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    let queue = DispatchQueue(label: "local-meeting-notes.audio")
    var mic: WaveTrack!
    var system: WaveTrack!
    var failure: Error?
    var stopRequested = false
    func requestStop() { queue.async { self.stopRequested = true } }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        queue.async { self.failure = error; self.stopRequested = true }
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard failure == nil else { return }
        do {
            if type == .audio { try system.write(sampleBuffer) }
            if type == .microphone { try mic.write(sampleBuffer) }
        } catch { failure = error; stopRequested = true }
    }

    func record(directory: URL, microphoneID: String?) async throws {
        DispatchQueue.global().async {
            while let line = readLine() {
                if ["stop", "quit", "exit"].contains(line.trimmingCharacters(in: .whitespacesAndNewlines)) { break }
            }
            self.requestStop() // Also stop safely if the parent disappears.
        }
        signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN)
        let signals = [SIGTERM, SIGINT].map { number -> DispatchSourceSignal in
            let source = DispatchSource.makeSignalSource(signal: number, queue: queue)
            source.setEventHandler { self.stopRequested = true }
            source.resume()
            return source
        }
        defer { for source in signals { source.cancel() } }
        var micAllowed = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        if !micAllowed { micAllowed = await AVCaptureDevice.requestAccess(for: .audio) }
        guard micAllowed else {
            throw CaptureFailure(message: "マイクの権限が必要です。システム設定 → プライバシーとセキュリティ → マイクで許可してください。")
        }
        let devices = microphoneDevices()
        guard let device = microphoneID == nil ? AVCaptureDevice.default(for: .audio) : devices.first(where: { $0.uniqueID == microphoneID }) else {
            throw CaptureFailure(message: "選択したマイクが見つかりません。デバイスを再読み込みしてください。")
        }
        let filter: SCContentFilter
        if CGPreflightScreenCaptureAccess() {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else { throw CaptureFailure(message: "録音対象のディスプレイが見つかりません。") }
            filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        } else {
            // Apple's picker grants access to the selected content for this stream.
            // Do not reject a local ad-hoc build solely on the legacy preflight result.
            emit(["event": "status", "message": "macOSの共有画面でディスプレイを選んでください。音声だけを保存し、映像は保存しません。"])
            let picker = CapturePicker()
            filter = try await picker.select { self.queue.sync { self.stopRequested } }
        }
        guard !queue.sync(execute: { stopRequested }) else { throw CaptureFailure(message: "録音開始前に停止しました。") }
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.captureMicrophone = true
        config.microphoneCaptureDeviceID = device.uniqueID
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48_000
        config.channelCount = 1
        config.width = 2; config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let epoch = CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock()))
        mic = try WaveTrack(url: directory.appendingPathComponent("mic.wav"), epoch: epoch)
        system = try WaveTrack(url: directory.appendingPathComponent("system.wav"), epoch: epoch)
        do {
            try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
            try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: queue)
            try await stream.startCapture()
        } catch {
            try? mic.finish(duration: 0); try? system.finish(duration: 0)
            throw error
        }
        emit(["event": "recording_started", "output_dir": directory.path,
              "mic_device": device.localizedName, "system_device": "Macの再生音（全体）",
              "recording_started_at": ISO8601DateFormatter().string(from: Date(timeIntervalSinceNow:
                epoch - CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock())))), "clock": "host_time"])
        while !queue.sync(execute: { stopRequested }) {
            try await Task.sleep(nanoseconds: 200_000_000)
            if !device.isConnected {
                queue.sync { failure = CaptureFailure(message: "マイクが切断されました。録音済みの音声は保存しました。"); stopRequested = true }
            }
        }
        do { try await stream.stopCapture() } catch { queue.sync { if failure == nil { failure = error } } }
        let duration = CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock())) - epoch
        try queue.sync {
            // Finalize both files even if one fails to flush.
            var finalError: Error?
            let alignedDuration = max(duration, Double(max(mic.frames, system.frames)) / 48_000)
            do { try mic.finish(duration: alignedDuration) } catch { finalError = error }
            do { try system.finish(duration: alignedDuration) } catch { if finalError == nil { finalError = error } }
            if let finalError { throw finalError }
            if mic.receivedFrames == 0, failure == nil { failure = CaptureFailure(message: "マイクの音声を取得できませんでした。権限と接続を確認してください。") }
        }
        emit(["event": "recording_stopped", "duration_seconds": duration,
              "mic_frames": mic.receivedFrames, "system_frames": system.receivedFrames,
              "mic_audible": mic.audible, "system_audible": system.audible])
        if let failure { throw failure }
        if !system.audible { emit(["event": "warning", "message": "Macの再生音が無音でした。会議音声が再生されているか確認してください。"] ) }
    }
}

@main
struct MeetingAudio {
    @MainActor static func main() async {
        let args = Array(CommandLine.arguments.dropFirst())
        do {
            switch args.first {
            case "self-test":
                guard args.count == 2 else { throw CaptureFailure(message: "Test output directory required") }
                let directory = URL(fileURLWithPath: args[1])
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                // Exercise timestamp alignment and 44.1 kHz -> 48 kHz conversion
                // with synthetic samples, without requesting recording access.
                for (name, rate, start) in [("mic", 44_100.0, 0.1), ("system", 48_000.0, 0.3)] {
                    let track = try WaveTrack(url: directory.appendingPathComponent("\(name).wav"), epoch: 100)
                    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, channels: 1, interleaved: false)!
                    for part in 0..<10 {
                        let count = Int(rate / 100)
                        let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count))!
                        pcm.frameLength = pcm.frameCapacity
                        for i in 0..<count { pcm.floatChannelData![0][i] = 0.25 * sin(Float(i + part * count) * 2 * .pi * 440 / Float(rate)) }
                        var timing = CMSampleTimingInfo(duration: CMTime(value: 1, timescale: Int32(rate)),
                            presentationTimeStamp: CMTime(seconds: 100 + start + Double(part) / 100, preferredTimescale: 1_000_000), decodeTimeStamp: .invalid)
                        var sample: CMSampleBuffer?
                        let status = CMSampleBufferCreate(allocator: kCFAllocatorDefault, dataBuffer: nil,
                            dataReady: false, makeDataReadyCallback: nil, refcon: nil, formatDescription: format.formatDescription,
                            sampleCount: count, sampleTimingEntryCount: 1, sampleTimingArray: &timing,
                            sampleSizeEntryCount: 0, sampleSizeArray: nil, sampleBufferOut: &sample)
                        guard status == noErr, let sample else { throw CaptureFailure(message: "Could not create test audio") }
                        let copied = CMSampleBufferSetDataBufferFromAudioBufferList(sample,
                            blockBufferAllocator: kCFAllocatorDefault, blockBufferMemoryAllocator: kCFAllocatorDefault,
                            flags: 0, bufferList: pcm.audioBufferList)
                        guard copied == noErr else { throw CaptureFailure(message: "Could not set test audio") }
                        CMSampleBufferSetDataReady(sample)
                        try track.write(sample)
                    }
                    try track.finish(duration: 0.5)
                }
                emit(["ok": true, "output_dir": directory.path])
            case "list-devices":
                var devices: [[String: Any]] = microphoneDevices().enumerated().map { index, device in
                    ["index": index, "id": device.uniqueID, "name": device.localizedName,
                     "is_default": device.uniqueID == AVCaptureDevice.default(for: .audio)?.uniqueID,
                     "channels": 1, "sample_rate": 48_000, "is_input": true, "is_loopback": false, "kind": "mic"]
                }
                devices.append(["index": -1, "id": "system", "name": "Macの再生音（全体）",
                                "channels": 1, "sample_rate": 48_000, "is_input": false, "is_loopback": true, "kind": "system"])
                emit(["ok": true, "devices": devices])
            case "permissions": emit(permissions())
            case "pick-directory":
                NSApplication.shared.setActivationPolicy(.accessory)
                NSApplication.shared.finishLaunching()
                NSApplication.shared.activate(ignoringOtherApps: true)
                let panel = NSOpenPanel()
                panel.canChooseFiles = false; panel.canChooseDirectories = true
                panel.allowsMultipleSelection = false
                panel.canCreateDirectories = args.contains("--create")
                panel.prompt = "選択"
                if let offset = args.firstIndex(of: "--initial"), args.count > offset + 1 {
                    panel.directoryURL = URL(fileURLWithPath: args[offset + 1])
                }
                if panel.runModal() == .OK, let url = panel.url { emit(["ok": true, "output_dir": url.path]) }
                else { emit(["ok": false, "canceled": true]) }
            case "record":
                guard args.count >= 2 else { throw CaptureFailure(message: "保存先が指定されていません。") }
                try await Recorder().record(directory: URL(fileURLWithPath: args[1]),
                                            microphoneID: args.count >= 3 ? args[2] : nil)
            default: throw CaptureFailure(message: "Unknown command")
            }
        } catch {
            emit(["ok": false, "event": "error", "error": error.localizedDescription, "message": error.localizedDescription])
            exit(2)
        }
    }
}
