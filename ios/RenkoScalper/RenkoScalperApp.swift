import SwiftUI

@main
struct RenkoScalperApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var store = AppStore.shared
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store)
        }
        .onChange(of: phase) { newPhase in
            if newPhase == .background { BackgroundRefresh.schedule() }
        }
        .backgroundTask(.appRefresh(BackgroundRefresh.id)) {
            await BackgroundRefresh.run()
        }
    }
}

struct RootView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        TabView {
            SignalsView()
                .tabItem { Label("Signals", systemImage: "bolt.fill") }
            WatchlistView()
                .tabItem { Label("Watchlist", systemImage: "eye") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task { await store.pollLoop() }
    }
}
