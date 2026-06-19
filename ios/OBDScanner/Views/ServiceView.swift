import SwiftUI

struct ServiceView: View {
    @EnvironmentObject var model: AppModel
    @State private var pendingSpec: ServiceSpec?

    var body: some View {
        NavigationStack {
            Group {
                if !model.sessionReady {
                    ContentUnavailablePlaceholder(
                        title: "Not connected",
                        message: "Connect to an adapter to use service functions.")
                } else {
                    List {
                        Section {
                            Text("These functions WRITE to the car. Only run them "
                                + "with the vehicle safely parked. The ECU may "
                                + "reject UDS/actuator requests — that is normal.")
                                .font(.footnote)
                                .foregroundStyle(.orange)
                        }

                        Section("Functions") {
                            ForEach(OBDService.commands) { spec in
                                Button {
                                    pendingSpec = spec
                                } label: {
                                    HStack {
                                        Image(systemName: spec.caution
                                            ? "exclamationmark.triangle.fill" : "checkmark.circle")
                                            .foregroundStyle(spec.caution ? .orange : .green)
                                        VStack(alignment: .leading) {
                                            Text(spec.title).foregroundStyle(.primary)
                                            Text(spec.engine).font(.caption).foregroundStyle(.secondary)
                                        }
                                    }
                                }
                            }
                        }

                        if !model.serviceLog.isEmpty {
                            Section("Result") {
                                ForEach(Array(model.serviceLog.enumerated()), id: \.offset) { _, line in
                                    Text(line).font(.system(.caption, design: .monospaced))
                                }
                            }
                        }

                        Section("Honda idle / throttle relearn") {
                            Text(OBDService.idleRelearn)
                                .font(.footnote)
                                .textSelection(.enabled)
                        }
                    }
                }
            }
            .navigationTitle("Service")
            .alert(pendingSpec?.title ?? "", isPresented: Binding(
                get: { pendingSpec != nil },
                set: { if !$0 { pendingSpec = nil } }
            ), presenting: pendingSpec) { spec in
                Button("Proceed", role: .destructive) {
                    Task { await model.runService(spec) }
                }
                Button("Cancel", role: .cancel) {}
            } message: { spec in
                Text("\(spec.detail)\n\nEngine state: \(spec.engine)"
                    + (spec.caution ? "\n\nThis writes to the ECU." : ""))
            }
        }
    }
}
