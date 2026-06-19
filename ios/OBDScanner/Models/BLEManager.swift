import Foundation
import CoreBluetooth

enum TransportError: LocalizedError {
    case notConnected
    case timeout
    case bluetoothOff
    case noUsableCharacteristic

    var errorDescription: String? {
        switch self {
        case .notConnected: return "Not connected to an adapter."
        case .timeout: return "The adapter did not respond in time."
        case .bluetoothOff: return "Bluetooth is off or unauthorized."
        case .noUsableCharacteristic:
            return "Connected, but no readable/writable channel was found."
        }
    }
}

/// CoreBluetooth transport for BLE ELM327 dongles. Exposes an async
/// `send(_:)` that writes a command and accumulates notification bytes until
/// the ELM327 prompt ('>') arrives — the BLE analogue of the Python
/// `_read_until_prompt`. One command is in flight at a time (the OBD link is
/// half-duplex), enforced by the driver awaiting each call.
@MainActor
final class BLEManager: NSObject, ObservableObject {

    // Note: many ELM327 clones don't advertise their GATT service in the
    // advertising packet, so we scan with `nil` services (catch-all) and pick
    // the write/notify characteristics after connecting — see didDiscover…
    @Published var isScanning = false
    @Published var isConnected = false
    @Published var poweredOn = false
    @Published var discovered: [CBPeripheral] = []
    @Published var statusText = "Idle."

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var writeChar: CBCharacteristic?
    private var notifyChar: CBCharacteristic?

    private var buffer = Data()
    private var pending: CheckedContinuation<String, Error>?
    private let prompt: UInt8 = 0x3E // '>'
    var readTimeout: TimeInterval = 8.0

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    // MARK: scanning / connection

    func startScan() {
        guard poweredOn else { statusText = "Turn on Bluetooth."; return }
        discovered.removeAll()
        isScanning = true
        statusText = "Scanning for adapters…"
        // nil services = catch dongles that don't advertise a known service.
        central.scanForPeripherals(withServices: nil)
    }

    func stopScan() {
        isScanning = false
        central.stopScan()
    }

    func connect(_ p: CBPeripheral) {
        stopScan()
        peripheral = p
        p.delegate = self
        statusText = "Connecting to \(p.name ?? "adapter")…"
        central.connect(p)
    }

    func disconnect() {
        if let p = peripheral { central.cancelPeripheralConnection(p) }
        isConnected = false
        writeChar = nil
        notifyChar = nil
        statusText = "Disconnected."
    }

    // MARK: command I/O

    func send(_ command: String) async throws -> String {
        guard isConnected, let p = peripheral, let wc = writeChar else {
            throw TransportError.notConnected
        }
        let data = Data((command + "\r").utf8)
        buffer.removeAll()

        return try await withCheckedThrowingContinuation { cont in
            self.pending = cont
            let type: CBCharacteristicWriteType =
                wc.properties.contains(.write) ? .withResponse : .withoutResponse
            p.writeValue(data, for: wc, type: type)

            // Fail the call if the prompt never arrives. The timeout runs on the
            // main actor so it can safely touch `pending`.
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(self.readTimeout * 1_000_000_000))
                if let c = self.pending {
                    self.pending = nil
                    c.resume(throwing: TransportError.timeout)
                }
            }
        }
    }

    private func deliver(_ text: String) {
        if let c = pending {
            pending = nil
            c.resume(returning: text)
        }
    }
}

// MARK: - CBCentralManagerDelegate

extension BLEManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        poweredOn = central.state == .poweredOn
        if !poweredOn { statusText = "Bluetooth not ready." }
    }

    func centralManager(_ central: CBCentralManager,
                        didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        // Only surface named devices to keep the list readable.
        guard peripheral.name?.isEmpty == false else { return }
        if !discovered.contains(where: { $0.identifier == peripheral.identifier }) {
            discovered.append(peripheral)
        }
    }

    func centralManager(_ central: CBCentralManager,
                        didConnect peripheral: CBPeripheral) {
        statusText = "Discovering services…"
        peripheral.discoverServices(nil)
    }

    func centralManager(_ central: CBCentralManager,
                        didFailToConnect peripheral: CBPeripheral,
                        error: Error?) {
        statusText = "Connect failed: \(error?.localizedDescription ?? "unknown")"
    }

    func centralManager(_ central: CBCentralManager,
                        didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        isConnected = false
        statusText = "Adapter disconnected."
        if let c = pending { pending = nil; c.resume(throwing: TransportError.notConnected) }
    }
}

// MARK: - CBPeripheralDelegate

extension BLEManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverServices error: Error?) {
        for service in peripheral.services ?? [] {
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        // Mirror the Python char-selection: a writable char for commands and a
        // notify char for responses; some dongles use one char for both.
        for c in service.characteristics ?? [] {
            let p = c.properties
            if p.contains(.write) || p.contains(.writeWithoutResponse) {
                if writeChar == nil { writeChar = c }
            }
            if p.contains(.notify) || p.contains(.indicate) {
                if notifyChar == nil {
                    notifyChar = c
                    peripheral.setNotifyValue(true, for: c)
                }
            }
        }
        // Single shared characteristic case.
        if notifyChar == nil, let wc = writeChar,
           wc.properties.contains(.notify) {
            notifyChar = wc
            peripheral.setNotifyValue(true, for: wc)
        }

        if writeChar != nil && notifyChar != nil && !isConnected {
            isConnected = true
            statusText = "Connected. Ready."
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard let data = characteristic.value else { return }
        buffer.append(data)
        if buffer.contains(prompt) {
            let text = String(decoding: buffer, as: UTF8.self)
                .replacingOccurrences(of: ">", with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            buffer.removeAll()
            deliver(text)
        }
    }
}
