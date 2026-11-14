import Foundation
import SwiftUI

@MainActor
final class AppStore: ObservableObject {
    static let shared = AppStore()

    @Published var signals: [TradeSignal] = []
    @Published var watch: [TradeSignal] = []
    @Published var lastScan: Date?
    @Published var error: String?
    @Published var loading = false

    private let defaults = UserDefaults.standard

    var minScore: Int {
        (defaults.object(forKey: "minScore") as? Int) ?? 70
    }

    var notificationsOn: Bool {
        (defaults.object(forKey: "notificationsOn") as? Bool) ?? true
    }

    func makeAPI() -> APIClient? {
        let url = defaults.string(forKey: "serverURL") ?? ""
        let token = defaults.string(forKey: "apiToken") ?? ""
        if url.isEmpty { return nil }
        return APIClient(baseURL: url, token: token)
    }

    func refresh() async {
        guard let api = makeAPI() else {
            error = "Set the server URL and token in Settings."
            return
        }
        loading = true
        defer { loading = false }
        do {
            let s: SignalsResponse = try await api.get("/api/v1/signals", query: ["limit": "40"])
            let w: WatchResponse = try await api.get("/api/v1/watchlist")
            signals = s.signals
            watch = w.items
            lastScan = Date(timeIntervalSince1970: Double(s.lastScanTs) / 1000)
            error = nil
            notifyNew(s.signals)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func notifyNew(_ list: [TradeSignal]) {
        let ids = list.compactMap { $0.sid }
        guard let maxId = ids.max() else { return }
        guard let last = defaults.object(forKey: "lastNotifiedId") as? Int else {
            defaults.set(maxId, forKey: "lastNotifiedId")  // first run: do not replay history
            return
        }
        if notificationsOn {
            for s in list.reversed() {
                guard let sid = s.sid, sid > last else { continue }
                if s.score >= minScore && (s.ageCandles ?? 0) <= 6 {
                    Notifier.notify(s)
                }
            }
        }
        if maxId > last { defaults.set(maxId, forKey: "lastNotifiedId") }
    }

    func pollLoop() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(nanoseconds: 15_000_000_000)
        }
    }
}
