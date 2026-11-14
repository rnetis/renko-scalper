import SwiftUI

struct SignalRow: View {
    let s: TradeSignal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(s.sideName)
                    .font(.caption.bold())
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(s.isLong ? Color.green.opacity(0.2) : Color.red.opacity(0.2))
                    .foregroundColor(s.isLong ? .green : .red)
                    .cornerRadius(6)
                Text(s.symbol.replacingOccurrences(of: "-SWAP-USDT", with: ""))
                    .font(.headline)
                Text(s.style.uppercased())
                    .font(.caption2).foregroundColor(.secondary)
                Spacer()
                Text("\(s.score) \(s.grade)")
                    .font(.subheadline.bold())
            }
            HStack(spacing: 14) {
                Label(fmtPrice(s.entry), systemImage: "arrow.right.circle").font(.caption)
                Label(fmtPrice(s.stop), systemImage: "xmark.octagon").font(.caption).foregroundColor(.orange)
                Label(fmtPrice(s.tp1), systemImage: "target").font(.caption).foregroundColor(.green)
            }
            if let st = s.status {
                Text(statusText(st))
                    .font(.caption2).foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private func statusText(_ st: String) -> String {
        switch st {
        case "open": return "Open · \(Int(s.ageCandles ?? 0)) candles old"
        case "tp1": return "TP1 hit · runner trailing"
        case "stopped": return "Stopped " + (s.resultR.map { String(format: "(%.2fR)", $0) } ?? "")
        case "runner_exit": return "Closed " + (s.resultR.map { String(format: "(%.2fR)", $0) } ?? "")
        default: return st.capitalized
        }
    }
}

struct SignalsView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        NavigationStack {
            List {
                if let e = store.error {
                    Text(e).font(.footnote).foregroundColor(.red)
                }
                if store.signals.isEmpty && store.error == nil {
                    Text("No signals yet. Alerts appear only when every rule lines up - waiting is part of the plan.")
                        .font(.footnote).foregroundColor(.secondary)
                }
                ForEach(store.signals) { s in
                    NavigationLink(value: s) { SignalRow(s: s) }
                }
            }
            .navigationTitle("Signals")
            .navigationDestination(for: TradeSignal.self) { SignalDetailView(s: $0) }
            .refreshable { await store.refresh() }
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    if store.loading { ProgressView() }
                }
            }
        }
    }
}

struct WatchlistView: View {
    @EnvironmentObject var store: AppStore

    var body: some View {
        NavigationStack {
            List {
                Section(footer: Text("Setups that passed every gate. Only those at or above your alert score are pushed.")) {
                    ForEach(store.watch) { s in
                        NavigationLink(value: s) { SignalRow(s: s) }
                    }
                }
            }
            .navigationTitle("Best now")
            .navigationDestination(for: TradeSignal.self) { SignalDetailView(s: $0) }
            .refreshable { await store.refresh() }
        }
    }
}
