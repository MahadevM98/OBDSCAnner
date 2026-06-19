import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        TabView {
            ConnectView(ble: model.ble)
                .tabItem { Label("Connect", systemImage: "antenna.radiowaves.left.and.right") }
            DashboardView()
                .tabItem { Label("Dashboard", systemImage: "gauge.with.dots.needle.bottom.50percent") }
            CodesView()
                .tabItem { Label("Codes", systemImage: "exclamationmark.triangle") }
            ExtractView()
                .tabItem { Label("Extract", systemImage: "doc.text.magnifyingglass") }
            ServiceView()
                .tabItem { Label("Service", systemImage: "wrench.and.screwdriver") }
        }
        .overlay(alignment: .bottom) {
            if !model.statusText.isEmpty {
                Text(model.statusText)
                    .font(.caption)
                    .padding(6)
                    .frame(maxWidth: .infinity)
                    .background(.thinMaterial)
            }
        }
    }
}
