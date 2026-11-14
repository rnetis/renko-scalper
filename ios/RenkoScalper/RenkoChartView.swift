import SwiftUI

struct RenkoChartView: View {
    let bricks: [BrickDTO]
    let entry: Double?
    let stop: Double?
    let tp1: Double?

    var body: some View {
        Canvas { ctx, size in
            guard !bricks.isEmpty else { return }
            var lo = bricks.map { min($0.o, $0.c) }.min() ?? 0
            var hi = bricks.map { max($0.o, $0.c) }.max() ?? 1
            for v in [entry, stop, tp1].compactMap({ $0 }) {
                lo = min(lo, v)
                hi = max(hi, v)
            }
            let pad = (hi - lo) * 0.06
            let top = hi + pad
            let range = max(hi + pad - (lo - pad), 1e-9)
            let height = size.height
            let toY: (Double) -> CGFloat = { p in height * CGFloat((top - p) / range) }

            let w = size.width / CGFloat(bricks.count)
            for (i, b) in bricks.enumerated() {
                let yTop = toY(max(b.o, b.c))
                let yBot = toY(min(b.o, b.c))
                let rect = CGRect(x: CGFloat(i) * w + 0.5, y: yTop,
                                  width: max(w - 1, 1), height: max(yBot - yTop, 1))
                ctx.fill(Path(rect), with: .color(b.dir > 0 ? Color.green : Color.red))
            }

            let lines: [(Double?, Color, String)] = [
                (entry, Color.blue, "Entry"),
                (stop, Color.orange, "Stop"),
                (tp1, Color.mint, "TP1"),
            ]
            for (price, color, label) in lines {
                guard let p = price else { continue }
                let y = toY(p)
                var path = Path()
                path.move(to: CGPoint(x: 0, y: y))
                path.addLine(to: CGPoint(x: size.width, y: y))
                ctx.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                ctx.draw(Text(label).font(.caption2).foregroundColor(color),
                         at: CGPoint(x: 4, y: y - 7), anchor: .leading)
            }
        }
        .frame(height: 260)
        .background(Color(.secondarySystemBackground))
        .cornerRadius(10)
    }
}
