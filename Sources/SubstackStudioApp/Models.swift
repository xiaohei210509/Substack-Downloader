import Foundation

enum WorkflowMode: String, CaseIterable, Identifiable {
    case download
    case translate

    var id: String { rawValue }

    var title: String {
        switch self {
        case .download:
            return "下载文章"
        case .translate:
            return "翻译已下载文章"
        }
    }

    var subtitle: String {
        switch self {
        case .download:
            return "从 Substack 下载单篇或整站文章，导出 Markdown / HTML / PDF。"
        case .translate:
            return "基于现有 Markdown 文章生成翻译稿、HTML 和新的 PDF。"
        }
    }
}

enum TranslationScope: String, CaseIterable, Identifiable {
    case file
    case directory

    var id: String { rawValue }

    var title: String {
        switch self {
        case .file:
            return "单个文件"
        case .directory:
            return "整个文件夹"
        }
    }
}

enum TranslationLanguage: String, CaseIterable, Identifiable {
    case chinese = "Chinese"
    case english = "English"
    case japanese = "Japanese"
    case french = "French"
    case german = "German"
    case spanish = "Spanish"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .chinese:
            return "中文"
        case .english:
            return "英文"
        case .japanese:
            return "日文"
        case .french:
            return "法文"
        case .german:
            return "德文"
        case .spanish:
            return "西班牙文"
        }
    }
}

enum APIMode: String, CaseIterable, Identifiable {
    case auto
    case responses
    case chat

    var id: String { rawValue }

    var title: String {
        switch self {
        case .auto:
            return "自动"
        case .responses:
            return "Responses"
        case .chat:
            return "Chat Completions"
        }
    }
}

struct OutputFormats {
    var markdown: Bool = true
    var html: Bool = false
    var pdf: Bool = true

    var selectedCLIValues: [String] {
        var values: [String] = []
        if markdown { values.append("md") }
        if html { values.append("html") }
        if pdf { values.append("pdf") }
        return values
    }
}

struct DownloadFormState {
    var url: String = ""
    var markdownDirectory: String
    var htmlDirectory: String
    var articleCount: String = "0"
    var premiumEnabled: Bool = false
    var headlessEnabled: Bool = false
    var outputFormats = OutputFormats()
    var overwriteExisting: Bool = false
    var substackEmail: String = ""
    var substackPassword: String = ""
}

struct TranslationFormState {
    var sourcePath: String = ""
    var outputDirectory: String
    var scope: TranslationScope = .file
    var language: TranslationLanguage = .chinese
    var openAIKey: String = ProcessInfo.processInfo.environment["OPENAI_API_KEY"] ?? ""
    var openAIBaseURL: String = ProcessInfo.processInfo.environment["OPENAI_BASE_URL"] ?? "https://api.openai.com/v1"
    var apiMode: APIMode = .auto
    var model: String = "gpt-5-mini"
    var outputFormats = OutputFormats()
    var overwriteExisting: Bool = false
}

struct TaskProgress {
    var current: Int = 0
    var total: Int = 0

    var fractionCompleted: Double {
        guard total > 0 else { return 0 }
        return Double(current) / Double(total)
    }

    var summary: String {
        total > 0 ? "已处理 \(current) / \(total)" : "等待执行"
    }
}

struct LogEntry: Identifiable {
    let id = UUID()
    let timestamp: Date
    let message: String
}

enum AppTaskState: Equatable {
    case idle
    case running
    case success(String)
    case failure(String)

    var title: String {
        switch self {
        case .idle:
            return "空闲"
        case .running:
            return "执行中"
        case let .success(message):
            return message
        case let .failure(message):
            return message
        }
    }
}
