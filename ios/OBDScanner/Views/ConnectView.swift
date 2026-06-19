import SwiftUI
import CoreBluetooth

struct ConnectView: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject var ble: BLEManager

    var body: some View {
        NavigationStack {
            List {
                Section("Adapter") {
                    HStack {
                        Circle()
                            .fill(ble.isConnected ? .green : (ble.poweredOn ? .orange : .red))
                            .frame(width: 10, height: 10)
                        Text(ble.statusText).font(.callout)
                    }
                    if ble.isConnected {
                        Button("Disconnect", role: .destructive) { ble.disconnect() }
                    } else {
                        Button(ble.isScanning ? "Scanning…" : "Scan for adapters") {
                            ble.startScan()
                        }
                        .disabled(!ble.poweredOn || ble.isScanning)
                    }
                }

                if !ble.isConnected {
                    Section("Found devices") {
                        if ble.discovered.isEmpty {
                            Text("No devices yet. Power the adapter and scan.")
                                .foregroundStyle(.secondary)
                        }
                        ForEach(ble.discovered, id: \.identifier) { p in
                            Button {
                                ble.connect(p)
                            } label: {
                                HStack {
                                    Image(systemName: "dot.radiowaves.right")
                                    Text(p.name ?? "Unknown").foregroundStyle(.primary)
                                }
                            }
                        }
                    }
                }

                if model.sessionReady {
                    Section("Vehicle") {
                        LabeledContent("VIN", value: model.vin.isEmpty ? "(not reported)" : model.vin)
                        LabeledContent("Protocol", value: model.protocolName)
                        LabeledContent("Battery", value: model.voltage)
                        LabeledContent("Sensors", value: "\(model.supportedPIDs.count) available")
                    }
                }
            }
            .navigationTitle("OBD-II Scanner")
        }
    }
}
