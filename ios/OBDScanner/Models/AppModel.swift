import Foundation
import Combine

/// Ties the BLE transport + ELM327 driver to the SwiftUI views. All state is
/// published on the main actor; long operations run as async Tasks.
@MainActor
final class AppModel: ObservableObject {
    let ble = BLEManager()
    lazy var elm = ELM327(ble)

    @Published var sessionReady = false
    @Published var vin = ""
    @Published var protocolName = ""
    @Published var voltage = ""
    @Published var supportedPIDs: [UInt8] = []
    @Published var statusText = ""

    // Dashboard
    @Published var dashboardPIDs: [UInt8] = []
    @Published var dashboardValues: [UInt8: String] = [:]
    @Published var polling = false
    private var pollTask: Task<Void, Never>?

    // Trouble codes
    @Published var stored: [DTCEntry] = []
    @Published var pending: [DTCEntry] = []
    @Published var permanent: [DTCEntry] = []

    // Full extract
    @Published var report: VehicleReport?
    @Published var extractProgress = ""
    @Published var extracting = false

    // Service
    @Published var serviceLog: [String] = []

    private var cancellables = Set<AnyCancellable>()

    init() {
        // When the BLE link comes up, negotiate the OBD session automatically.
        ble.$isConnected
            .removeDuplicates()
            .sink { [weak self] connected in
                guard let self else { return }
                if connected { Task { await self.startSession() } }
                else { self.sessionReady = false; self.stopPolling() }
            }
            .store(in: &cancellables)
    }

    func name(for pid: UInt8) -> String { PIDs.table[pid]?.name ?? String(format: "PID %02X", Int(pid)) }
    func unit(for pid: UInt8) -> String { PIDs.table[pid]?.unit ?? "" }

    // MARK: session

    func startSession() async {
        statusText = "Negotiating protocol…"
        do {
            let info = try await elm.initialize()
            protocolName = info["protocol"] ?? ""
            voltage = info["voltage"] ?? ""
            vin = (try? await elm.readVIN()) ?? ""
            let supported = (try? await elm.supportedPIDs()) ?? []
            supportedPIDs = supported.sorted()

            // Dashboard: supported ∩ default, but always keep STFT/LTFT even
            // when the ECU under-reports them (the desktop-app fix).
            var wanted = PIDs.dashboard.filter { supported.contains($0) }
            if wanted.isEmpty { wanted = PIDs.dashboard }
            for p in [0x06, 0x07] as [UInt8] where !wanted.contains(p) { wanted.append(p) }
            dashboardPIDs = wanted
            sessionReady = true
            statusText = "Connected. \(supportedPIDs.count) sensors available."
        } catch {
            statusText = "Setup failed: \(error.localizedDescription)"
        }
    }

    // MARK: dashboard polling

    func togglePolling() {
        polling ? stopPolling() : startPolling()
    }

    func startPolling() {
        guard sessionReady, !polling else { return }
        polling = true
        pollTask = Task {
            while !Task.isCancelled && polling {
                for pid in dashboardPIDs {
                    if Task.isCancelled { break }
                    if let (_, value, unit) = try? await elm.queryPID(pid) {
                        dashboardValues[pid] = "\(value.display) \(unit)".trimmingCharacters(in: .whitespaces)
                    }
                }
                try? await Task.sleep(nanoseconds: 150_000_000)
            }
        }
    }

    func stopPolling() {
        polling = false
        pollTask?.cancel()
        pollTask = nil
    }

    // MARK: trouble codes

    func readCodes() async {
        statusText = "Reading trouble codes…"
        stored = (try? await elm.readStoredDTCs()) ?? []
        pending = (try? await elm.readPendingDTCs()) ?? []
        permanent = (try? await elm.readPermanentDTCs()) ?? []
        statusText = "Codes: \(stored.count) stored, \(pending.count) pending, \(permanent.count) permanent."
    }

    func clearCodes() async {
        statusText = "Clearing codes…"
        let ok = (try? await elm.clearDTCs()) ?? false
        if ok { stored = []; pending = [] }
        statusText = ok ? "Codes erased and MIL reset. Re-read to confirm."
                        : "Erase sent but the ECU did not confirm."
    }

    // MARK: full extract

    func runExtract() async {
        guard sessionReady, !extracting else { return }
        extracting = true
        stopPolling()
        let r = await Extract.full(elm) { [weak self] label in
            self?.extractProgress = label
        }
        report = r
        extractProgress = ""
        extracting = false
        statusText = "Full extract complete."
    }

    // MARK: service

    func runService(_ spec: ServiceSpec) async {
        serviceLog.append(">>> \(spec.title)")
        var last: ServiceResult?
        for (i, cmd) in spec.steps.enumerated() {
            let expect = (i == spec.steps.count - 1) ? spec.expect : nil
            last = try? await elm.runCommand(cmd, expect: expect)
            if let l = last, !l.ok, l.detail.contains("rejected") { break }
        }
        if let l = last {
            serviceLog.append("  [\(l.ok ? "OK" : "—")] \(l.detail)")
            serviceLog.append("      raw: \(l.raw)")
        } else {
            serviceLog.append("  [—] no response")
        }
    }
}
