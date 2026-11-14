import Foundation
import UIKit
import UserNotifications
import BackgroundTasks

enum Notifier {
    static func requestAuth() async -> Bool {
        do {
            return try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .sound, .badge])
        } catch {
            return false
        }
    }

    static func notify(_ s: TradeSignal) {
        let content = UNMutableNotificationContent()
        content.title = "\(s.isLong ? "🟢" : "🔴") \(s.sideName) \(s.symbol) · \(s.score)"
        content.body = "Entry \(fmtPrice(s.entry))  Stop \(fmtPrice(s.stop))  TP1 \(fmtPrice(s.tp1))"
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        let req = UNNotificationRequest(identifier: s.key, content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(req)
    }

    static func test() {
        let content = UNMutableNotificationContent()
        content.title = "Renko Scalper"
        content.body = "Notifications are working."
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: trigger))
    }
}

enum BackgroundRefresh {
    static let id = "app.renkoscalper.refresh"

    static func schedule() {
        let request = BGAppRefreshTaskRequest(identifier: id)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    @MainActor static func run() async {
        await AppStore.shared.refresh()
        schedule()
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .list])
    }
}
