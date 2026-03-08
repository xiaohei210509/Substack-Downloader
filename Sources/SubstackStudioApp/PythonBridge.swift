import Foundation

struct PythonBridge {
    let repositoryRoot: URL

    enum BridgeError: LocalizedError {
        case pythonMissing(String)
        case invalidArticleCount

        var errorDescription: String? {
            switch self {
            case let .pythonMissing(path):
                return "未找到 Python 解释器：\(path)"
            case .invalidArticleCount:
                return "文章数量必须是大于或等于 0 的整数。"
            }
        }
    }

    var pythonExecutableURL: URL {
        repositoryRoot.appendingPathComponent(".venv/bin/python3")
    }

    var scraperScriptURL: URL {
        repositoryRoot.appendingPathComponent("substack_scraper.py")
    }

    func makeDownloadCommand(from form: DownloadFormState) throws -> [String] {
        let pythonPath = pythonExecutableURL.path
        guard FileManager.default.fileExists(atPath: pythonPath) else {
            throw BridgeError.pythonMissing(pythonPath)
        }

        guard let count = Int(form.articleCount), count >= 0 else {
            throw BridgeError.invalidArticleCount
        }

        var arguments = [scraperScriptURL.path]
        arguments += ["--url", form.url]
        arguments += ["--directory", form.markdownDirectory]
        arguments += ["--html-directory", form.htmlDirectory]
        arguments += ["--number", String(count)]
        for format in form.outputFormats.selectedCLIValues {
            arguments += ["--format", format]
        }

        if form.premiumEnabled {
            arguments.append("--premium")
        }
        if form.headlessEnabled {
            arguments.append("--headless")
        }
        if form.overwriteExisting {
            arguments.append("--overwrite")
        }
        if !form.substackEmail.isEmpty {
            arguments += ["--email", form.substackEmail]
        }
        if !form.substackPassword.isEmpty {
            arguments += ["--password", form.substackPassword]
        }

        return [pythonPath] + arguments
    }

    func makeTranslationCommand(from form: TranslationFormState) throws -> [String] {
        let pythonPath = pythonExecutableURL.path
        guard FileManager.default.fileExists(atPath: pythonPath) else {
            throw BridgeError.pythonMissing(pythonPath)
        }

        var arguments = [scraperScriptURL.path]
        switch form.scope {
        case .file:
            arguments += ["--translate-file", form.sourcePath]
        case .directory:
            arguments += ["--translate-directory", form.sourcePath]
        }
        arguments += ["--target-language", form.language.rawValue]
        arguments += ["--html-directory", form.outputDirectory]
        for format in form.outputFormats.selectedCLIValues {
            arguments += ["--format", format]
        }
        arguments += ["--openai-api-key", form.openAIKey]
        arguments += ["--openai-base-url", form.openAIBaseURL]
        arguments += ["--openai-api-mode", form.apiMode.rawValue]
        arguments += ["--openai-model", form.model]

        if form.overwriteExisting {
            arguments.append("--overwrite")
        }

        return [pythonPath] + arguments
    }

    @discardableResult
    func run(
        command: [String],
        environment: [String: String] = [:],
        onOutput: @escaping @Sendable (String) -> Void
    ) async throws -> Int32 {
        let process = Process()
        process.currentDirectoryURL = repositoryRoot
        process.executableURL = URL(fileURLWithPath: command[0])
        process.arguments = Array(command.dropFirst())

        var mergedEnvironment = ProcessInfo.processInfo.environment
        environment.forEach { mergedEnvironment[$0.key] = $0.value }
        process.environment = mergedEnvironment

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        func outputHandler(_ handle: FileHandle) async throws {
            for try await line in handle.bytes.lines {
                let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if !text.isEmpty {
                    onOutput(text)
                }
            }
        }

        try process.run()

        async let stdoutTask: Void = outputHandler(stdout.fileHandleForReading)
        async let stderrTask: Void = outputHandler(stderr.fileHandleForReading)

        process.waitUntilExit()
        _ = try await (stdoutTask, stderrTask)
        return process.terminationStatus
    }
}
