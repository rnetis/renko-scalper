import SwiftUI

struct SignalDetailView: View {
    @EnvironmentObject var store: AppStore
    let s: TradeSignal
    @State private var renko: RenkoResponse?
    @State private var chartError: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("\(s.sideName) \(s.symbol)").font(.title3.bold())
                    Spacer()
                    Text("\(s.score) · \(s.grade)").font(.title3.bold())
                }

                if let r = renko {
                    RenkoChartView(bricks: r.bricks, entry: s.entry, stop: s.currentStop ?? s.stop, tp1: s.tp1)
                    Text("Renko brick \(fmtPrice(r.size)) · \(s.style == "scalp" ? "1m" : "5m") base")
                        .font(.caption2).foregroundColor(.secondary)
                } else if let e = chartError {
                    Text("Chart unavailable: \(e)").font(.caption).foregroundColor(.secondary)
                } else {
                    ProgressView().frame(maxWidth: .infinity)
                }

                GroupBox("Levels") {
                    VStack(spacing: 8) {
                        row("Entry (≈)", fmtPrice(s.entry))
                        row("Stop", fmtPrice(s.currentStop ?? s.stop))
                        row("TP1 (close half)", fmtPrice(s.tp1))
                        row("Net R at TP1", String(format: "%.2f", s.netRr1))
                        row("TP1 vs costs", String(format: "%.1fx", s.costMultiple))
                    }
                }

                GroupBox("Plan") {
                    Text("At TP1 close half and move the stop to breakeven. Let the runner trail \(fmtPrice(2 * s.brickLtf)) (2 Renko bricks) behind the best price and exit only when the market takes you out. If the stop is hit, it is a normal loss - no revenge trade.")
                        .font(.footnote)
                }

                if let z = s.sizing {
                    GroupBox("Position size") {
                        VStack(spacing: 8) {
                            row("Quantity", fmtPrice(z.qty))
                            row("Notional", fmtPrice(z.notional) + " USDT")
                            row("Risk if stopped", fmtPrice(z.riskUsdt) + " USDT")
                            row("Isolated leverage", "≤ \(z.leverageHint)x")
                            row("Margin", fmtPrice(z.marginUsdt) + " USDT")
                        }
                    }
                } else {
                    Text("Position size is below the exchange minimum for your risk budget.")
                        .font(.footnote).foregroundColor(.secondary)
                }

                GroupBox("Why") {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(s.reasons, id: \.self) { Text("• \($0)").font(.footnote) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                if !s.warnings.isEmpty {
                    GroupBox("Watch out") {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(s.warnings, id: \.self) { Text("⚠︎ \($0)").font(.footnote).foregroundColor(.orange) }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                Text("Decision support, not financial advice. Futures with leverage can lose more than you expect.")
                    .font(.caption2).foregroundColor(.secondary)
            }
            .padding()
        }
        .navigationTitle(s.symbol.replacingOccurrences(of: "-SWAP-USDT", with: ""))
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadChart() }
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).foregroundColor(.secondary)
            Spacer()
            Text(v).bold()
        }
        .font(.footnote)
    }

    private func loadChart() async {
        guard let api = store.makeAPI() else { return }
        do {
            let r: RenkoResponse = try await api.get(
                "/api/v1/renko",
                query: ["symbol": s.symbol, "style": s.style, "tf": "ltf", "limit": "70"])
            renko = r
        } catch {
            chartError = error.localizedDescription
        }
    }
}
