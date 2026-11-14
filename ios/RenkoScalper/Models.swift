import Foundation

struct Sizing: Codable, Hashable {
    let qty: Double
    let notional: Double
    let riskUsdt: Double
    let leverageHint: Int
    let marginUsdt: Double
    let stopPct: Double
}

struct TradeSignal: Codable, Identifiable, Hashable {
    var id: String { key }
    let sid: Int?
    let key: String
    let symbol: String
    let style: String
    let side: Int
    let sideName: String
    let score: Int
    let grade: String
    let ts: Int
    let price: Double
    let entry: Double
    let stop: Double
    let tp1: Double
    let brickLtf: Double
    let brickHtf: Double
    let riskDist: Double
    let costMultiple: Double
    let netRr1: Double
    let reasons: [String]
    let warnings: [String]
    let ltfMs: Int
    let status: String?
    let createdTs: Int?
    let ageCandles: Double?
    let currentStop: Double?
    let tp1Hit: Bool?
    let resultR: Double?
    let sizing: Sizing?

    enum CodingKeys: String, CodingKey {
        case sid = "id"
        case key, symbol, style, side, sideName, score, grade, ts, price, entry, stop, tp1
        case brickLtf, brickHtf, riskDist, costMultiple, netRr1, reasons, warnings, ltfMs
        case status, createdTs, ageCandles, currentStop, tp1Hit, resultR, sizing
    }

    var isLong: Bool { side > 0 }
    var isActive: Bool { status == "open" || status == "tp1" }
}

struct SignalsResponse: Codable {
    let signals: [TradeSignal]
    let lastScanTs: Int
    let serverTime: Int
    let minScore: Int
}

struct WatchResponse: Codable {
    let items: [TradeSignal]
    let lastScanTs: Int
    let minScore: Int
}

struct BrickDTO: Codable, Hashable {
    let ts: Int
    let dir: Int
    let o: Double
    let c: Double
    let vol: Double
}

struct RenkoResponse: Codable {
    let symbol: String
    let style: String
    let tf: String
    let size: Double
    let price: Double
    let bricks: [BrickDTO]
}

struct Health: Codable {
    let ok: Bool
    let cycles: Int
    let lastScanTs: Int
    let symbols: Int
    let lastError: String
    let serverTime: Int
}

func fmtPrice(_ x: Double) -> String {
    if x >= 1000 { return String(format: "%.2f", x) }
    if x >= 1 { return String(format: "%.4f", x) }
    return String(format: "%.6f", x)
}
