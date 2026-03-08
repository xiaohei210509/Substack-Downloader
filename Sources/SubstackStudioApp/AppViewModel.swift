import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

@MainActor
final class AppViewModel: ObservableObject {
    private enum DefaultsKey {
        static let downloadMarkdownDirectory = "download.markdownDirectory"
        static let downloadHTMLDirectory = "download.htmlDirectory"
        static let translationOutputDirectory = "translation.outputDirectory"
        static let openAIKey = "translation.openAIKey"
        static let openAIBaseURL = "translation.openAIBaseURL"
        static let openAIModel = "translation.openAIModel"
        static let apiMode = "translation.apiMode"
        static let targetLanguage = "translation.targetLanguage"
    }

    @Published var workflowMode: WorkflowMode = .download
    @Published var downloadForm: DownloadFormState {
        didSet {
            persistDirectoryPreferences()
        }
    }
    @Published var translationForm: TranslationFormState {
        didSet {
            persistTranslationPreferences()
            persistDirectoryPreferences()
        }
    }
    @Published var progress = TaskProgress()
    @Published var taskState: AppTaskState = .idle
    @Published var logs: [LogEntry] = []
    @Published var lastDiagnosticMessage: String?

    private let repositoryRoot: URL
    private let bridge: PythonBridge
    private var runningTask: Task<Void, Never>?

    init() {
        if let bundledBackend = Bundle.main.resourceURL?.appendingPathComponent("backend"),
           FileManager.default.fileExists(atPath: bundledBackend.path) {
            self.repositoryRoot = bundledBackend
        } else {
            self.repositoryRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        }
        self.bridge = PythonBridge(repositoryRoot: repositoryRoot)
        let defaults = UserDefaults.standard
        let defaultMarkdownDirectory = repositoryRoot.appendingPathComponent("downloads_md").path
        let defaultHTMLDirectory = repositoryRoot.appendingPathComponent("downloads_html").path
        let defaultTranslationOutputDirectory = repositoryRoot.appendingPathComponent("translated_output").path
        self.downloadForm = DownloadFormState(
            markdownDirectory: defaults.string(forKey: DefaultsKey.downloadMarkdownDirectory) ?? defaultMarkdownDirectory,
            htmlDirectory: defaults.string(forKey: DefaultsKey.downloadHTMLDirectory) ?? defaultHTMLDirectory
        )
        self.translationForm = TranslationFormState(
            outputDirectory: defaults.string(forKey: DefaultsKey.translationOutputDirectory) ?? defaultTranslationOutputDirectory,
            language: TranslationLanguage(rawValue: defaults.string(forKey: DefaultsKey.targetLanguage) ?? "Chinese") ?? .chinese,
            openAIKey: defaults.string(forKey: DefaultsKey.openAIKey) ?? ProcessInfo.processInfo.environment["OPENAI_API_KEY"] ?? "",
            openAIBaseURL: defaults.string(forKey: DefaultsKey.openAIBaseURL) ?? ProcessInfo.processInfo.environment["OPENAI_BASE_URL"] ?? "https://api.openai.com/v1",
            apiMode: APIMode(rawValue: defaults.string(forKey: DefaultsKey.apiMode) ?? "auto") ?? .auto,
            model: defaults.string(forKey: DefaultsKey.openAIModel) ?? "gpt-5-mini"
        )
    }

    var canRun: Bool {
        switch workflowMode {
        case .download:
            return !downloadForm.url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                !downloadForm.outputFormats.selectedCLIValues.isEmpty &&
                taskState != .running
        case .translate:
            return !translationForm.sourcePath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                !translationForm.openAIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                !translationForm.outputFormats.selectedCLIValues.isEmpty &&
                taskState != .running
        }
    }

    func appendLog(_ message: String) {
        logs.append(LogEntry(timestamp: Date(), message: message))
    }

    func clearLogs() {
        logs.removeAll()
    }

    func chooseDownloadMarkdownDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        if panel.runModal() == .OK, let path = panel.url?.path {
            downloadForm.markdownDirectory = path
        }
    }

    func chooseDownloadHTMLDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        if panel.runModal() == .OK, let path = panel.url?.path {
            downloadForm.htmlDirectory = path
        }
    }

    func chooseTranslationOutputDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        if panel.runModal() == .OK, let path = panel.url?.path {
            translationForm.outputDirectory = path
        }
    }

    func chooseTranslationSource(scope: TranslationScope) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = scope == .directory
        panel.canChooseFiles = scope == .file
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        if scope == .file {
            panel.allowedContentTypes = [UTType.plainText]
        }
        if panel.runModal() == .OK, let path = panel.url?.path {
            translationForm.sourcePath = path
        }
    }

    func openPath(_ path: String) {
        guard !path.isEmpty else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func runCurrentWorkflow() {
        guard runningTask == nil else { return }

        progress = TaskProgress()
        taskState = .running
        lastDiagnosticMessage = nil

        runningTask = Task { [weak self] in
            guard let self else { return }
            do {
                switch workflowMode {
                case .download:
                    try await runDownload()
                case .translate:
                    try await runTranslation()
                }
            } catch {
                taskState = .failure("执行失败")
                appendLog("错误：\(error.localizedDescription)")
            }
            runningTask = nil
        }
    }

    private func runDownload() async throws {
        let command = try bridge.makeDownloadCommand(from: downloadForm)

        let status = try await bridge.run(command: command) { [weak self] line in
            Task { @MainActor in
                self?.handlePythonOutput(line)
            }
        }

        if status == 0 {
            taskState = .success("下载完成")
        } else {
            taskState = .failure("下载失败")
            appendLog(lastDiagnosticMessage ?? "错误：下载失败。请检查链接、输出格式，以及付费账号是否有效。")
        }
    }

    private func runTranslation() async throws {
        let command = try bridge.makeTranslationCommand(from: translationForm)

        let status = try await bridge.run(command: command) { [weak self] line in
            Task { @MainActor in
                self?.handlePythonOutput(line)
            }
        }

        if status == 0 {
            taskState = .success("翻译完成")
        } else {
            taskState = .failure("翻译失败")
            appendLog(lastDiagnosticMessage ?? "错误：翻译失败。请优先把接口模式切换到 Chat Completions，并检查 Base URL、模型名和 API Key。")
        }
    }

    private func handlePythonOutput(_ line: String) {
        if let progressValue = parseProgress(from: line) {
            progress = progressValue
            taskState = .running
            return
        }
        if line.hasPrefix("错误：") || line.hasPrefix("API 请求失败") {
            lastDiagnosticMessage = line
            appendLog(line)
            taskState = .failure("执行失败")
            return
        }
        if line.lowercased().contains("error") || line.lowercased().contains("failed") || line.lowercased().contains("exception") {
            lastDiagnosticMessage = "错误：\(line)"
            return
        }
        if line.hasPrefix("/") || line.hasPrefix("./") || line.contains(".md") || line.contains(".html") || line.contains(".pdf") {
            appendLog(line)
        }
    }

    private func parseProgress(from line: String) -> TaskProgress? {
        guard line.hasPrefix("TRANSLATION_PROGRESS ") else {
            return nil
        }
        let pattern = #"(\d+)\s*/\s*(\d+)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return nil
        }

        let range = NSRange(line.startIndex..<line.endIndex, in: line)
        guard let match = regex.firstMatch(in: line, range: range),
              let currentRange = Range(match.range(at: 1), in: line),
              let totalRange = Range(match.range(at: 2), in: line),
              let current = Int(line[currentRange]),
              let total = Int(line[totalRange]) else {
            return nil
        }

        return TaskProgress(current: current, total: total)
    }

    private func persistTranslationPreferences() {
        let defaults = UserDefaults.standard
        defaults.set(translationForm.openAIKey, forKey: DefaultsKey.openAIKey)
        defaults.set(translationForm.openAIBaseURL, forKey: DefaultsKey.openAIBaseURL)
        defaults.set(translationForm.model, forKey: DefaultsKey.openAIModel)
        defaults.set(translationForm.apiMode.rawValue, forKey: DefaultsKey.apiMode)
        defaults.set(translationForm.language.rawValue, forKey: DefaultsKey.targetLanguage)
    }

    private func persistDirectoryPreferences() {
        let defaults = UserDefaults.standard
        defaults.set(downloadForm.markdownDirectory, forKey: DefaultsKey.downloadMarkdownDirectory)
        defaults.set(downloadForm.htmlDirectory, forKey: DefaultsKey.downloadHTMLDirectory)
        defaults.set(translationForm.outputDirectory, forKey: DefaultsKey.translationOutputDirectory)
    }
}
