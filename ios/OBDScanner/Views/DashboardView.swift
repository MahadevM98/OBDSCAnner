import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var model: AppModel

    private let columns = [GridItem(.adaptive(minimum: 150), spacing: 12)]

    var body: some View {
        NavigationStack {
            Group {
                if !model.sessionReady {
                    ContentUnavailablePlaceholder(
                        title: "Not connected",
                        message: "Connect to an adapter on the Connect tab.")
                } else {
                    ScrollView {
                        LazyVGrid(columns: columns, spacing: 12) {
                            ForEach(model.dashboardPIDs, id: \.self) { pid in
                                gauge(pid)
                            }
                        }
                        .padding()
                    }
                }
            }
            .navigationTitle("Dashboard")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button(model.polling ? "Stop" : "Start") { model.togglePolling() }
                        .disabled(!model.sessionReady)
                }
            }
        }
    }

    private func gauge(_ pid: UInt8) -> some View {
        VStack(spacing: 6) {
            Text(model.name(for: pid))
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Text(model.dashboardValues[pid] ?? "—")
                .font(.title2.bold())
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity, minHeight: 80)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }
}

/// Small shared empty-state used by several tabs.
struct ContentUnavailablePlaceholder: View {
    let title: String
    let message: String
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "car").font(.largeTitle).foregroundStyle(.secondary)
            Text(title).font(.headline)
            Text(message).font(.callout).foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding()
    }
}
