import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var store: AppStore
    @AppStorage("serverURL") private var serverURL = ""
    @AppStorage("apiToken") private var apiToken = ""
    @AppStorage("notificationsOn") private var notificationsOn = true
    @AppStorage("minScore") private var minScore = 70
    @State private var status = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("http://your-server:8787", text: $serverURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    SecureField("API token", text: $apiToken)
                    Button("Test connection") {
                        Task { await testConnection() }
                    }
                    if !status.isEmpty {
                        Text(status).font(.footnote).foregroundColor(.secondary)
                    }
                }

                Section(header: Text("Notifications"),
                        footer: Text("iOS only runs this app's checks while it is open or briefly in the background. For alerts that always arrive, also enable Telegram or ntfy on the server.")) {
                    Toggle("Local alerts for new signals", isOn: $notificationsOn)
                        .onChange(of: notificationsOn) { on in
                            if on { Task { _ = await Notifier.requestAuth() } }
                        }
                    Stepper("Minimum score: \(minScore)", value: $minScore, in: 50...95, step: 5)
                    Button("Send test notification") {
                        Task {
                            if await Notifier.requestAuth() { Notifier.test() }
                        }
                    }
                }

                Section("About") {
                    Text("Renko + Wyckoff + dual-time-frame momentum scanner for Toobit USDT-M futures. It never places orders and needs no exchange keys. Not financial advice.")
                        .font(.footnote)
                }
            }
            .navigationTitle("Settings")
        }
    }

    private func testConnection() async {
        status = "Testing..."
        let api = APIClient(baseURL: serverURL, token: apiToken)
        do {
            let h: Health = try await api.get("/api/v1/health")
            // health is public; verify the token against a protected route too
            let _: SignalsResponse = try await api.get("/api/v1/signals", query: ["limit": "1"])
            status = "OK · \(h.symbols) symbols · \(h.cycles) scans"
            await store.refresh()
        } catch {
            status = error.localizedDescription
        }
    }
}
