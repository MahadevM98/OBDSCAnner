import SwiftUI

struct ExtractView: View {
    @EnvironmentObject var model: AppModel

    private var text: String { model.report.map(Extract.toText) ?? "" }

    var body: some View {
        NavigationStack {
            Group {
                if !model.sessionReady {
                    ContentUnavailablePlaceholder(
                        title: "Not connected",
                        message: "Connect to an adapter to run a full extract.")
                } else if model.extracting {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text(model.extractProgress.isEmpty ? "Working…" : model.extractProgress)
                            .foregroundStyle(.secondary)
                    }
                } else if let report = model.report {
                    ScrollView([.horizontal, .vertical]) {
                        Text(Extract.toText(report))
                            .font(.system(.footnote, design: .monospaced))
                            .textSelection(.enabled)
                            .padding()
                    }
                } else {
                    ContentUnavailablePlaceholder(
                        title: "No extract yet",
                        message: "Reads Modes 01/02/03/06/07/09/0A in one pass.")
                }
            }
            .navigationTitle("Full Extract")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("Extract") { Task { await model.runExtract() } }
                        .disabled(!model.sessionReady || model.extracting)
                }
                ToolbarItem(placement: .topBarLeading) {
                    if model.report != nil {
                        ShareLink(item: text) { Image(systemName: "square.and.arrow.up") }
                    }
                }
            }
        }
    }
}
