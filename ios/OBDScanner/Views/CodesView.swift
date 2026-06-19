import SwiftUI

struct CodesView: View {
    @EnvironmentObject var model: AppModel
    @State private var showClearConfirm = false

    var body: some View {
        NavigationStack {
            Group {
                if !model.sessionReady {
                    ContentUnavailablePlaceholder(
                        title: "Not connected",
                        message: "Connect to an adapter to read codes.")
                } else {
                    List {
                        codeSection("Stored (MIL)", model.stored)
                        codeSection("Pending", model.pending)
                        codeSection("Permanent", model.permanent)
                    }
                }
            }
            .navigationTitle("Trouble Codes")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("Read") { Task { await model.readCodes() } }
                        .disabled(!model.sessionReady)
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button("Clear", role: .destructive) { showClearConfirm = true }
                        .disabled(!model.sessionReady)
                }
            }
            .confirmationDialog("Erase all stored codes and turn off the MIL?",
                                isPresented: $showClearConfirm, titleVisibility: .visible) {
                Button("Clear codes", role: .destructive) { Task { await model.clearCodes() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Permanent codes can only be cleared by the ECU after the "
                    + "fault stays fixed across drive cycles.")
            }
        }
    }

    private func codeSection(_ title: String, _ codes: [DTCEntry]) -> some View {
        Section(title) {
            if codes.isEmpty {
                Text("None").foregroundStyle(.secondary)
            } else {
                ForEach(codes) { c in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(c.code).font(.headline.monospaced())
                        Text(c.desc).font(.callout).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}
