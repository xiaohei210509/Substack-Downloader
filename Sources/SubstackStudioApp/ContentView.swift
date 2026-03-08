import SwiftUI

struct ContentView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        HSplitView {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HeaderView(viewModel: viewModel)
                    WorkflowPicker(viewModel: viewModel)

                    if viewModel.workflowMode == .download {
                        DownloadFormView(viewModel: viewModel)
                    } else {
                        TranslationFormView(viewModel: viewModel)
                    }

                    ActionBar(viewModel: viewModel)
                }
                .padding(28)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(Color(nsColor: .windowBackgroundColor))

            LogPanelView(viewModel: viewModel)
                .frame(minWidth: 360, idealWidth: 410)
        }
    }
}

private struct HeaderView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Substack Studio")
                .font(.system(size: 30, weight: .bold, design: .rounded))

            Text("原生 SwiftUI macOS 客户端。下载文章、导出 PDF，并对已下载 Markdown 做翻译。")
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                StatusBadge(title: viewModel.taskState.title, state: viewModel.taskState)
                ProgressBadge(progress: viewModel.progress)
            }

            VStack(alignment: .leading, spacing: 8) {
                ProgressView(value: viewModel.progress.fractionCompleted)
                    .controlSize(.large)
                Text(viewModel.progress.summary)
                    .font(.footnote.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: 420, alignment: .leading)
        }
    }
}

private struct WorkflowPicker: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("工作模式")
                .font(.headline)

            Picker("工作模式", selection: $viewModel.workflowMode) {
                ForEach(WorkflowMode.allCases) { mode in
                    Text(mode.title).tag(mode)
                }
            }
            .pickerStyle(.segmented)

            Text(viewModel.workflowMode.subtitle)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .cardStyle()
    }
}

private struct DownloadFormView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("下载配置")
                .font(.headline)

            LabeledTextField(title: "Substack 链接", text: $viewModel.downloadForm.url, placeholder: "https://example.substack.com 或单篇文章地址")

            DirectoryField(
                title: "Markdown 输出目录",
                text: $viewModel.downloadForm.markdownDirectory,
                action: viewModel.chooseDownloadMarkdownDirectory
            )

            DirectoryField(
                title: "HTML / PDF 输出目录",
                text: $viewModel.downloadForm.htmlDirectory,
                action: viewModel.chooseDownloadHTMLDirectory
            )

            HStack(spacing: 16) {
                LabeledTextField(title: "文章数量", text: $viewModel.downloadForm.articleCount, placeholder: "0 表示全部")
                OutputFormatPicker(formats: $viewModel.downloadForm.outputFormats)
            }

            HStack(spacing: 16) {
                Toggle("付费模式", isOn: $viewModel.downloadForm.premiumEnabled)
                Toggle("无头浏览器", isOn: $viewModel.downloadForm.headlessEnabled)
                Toggle("覆盖已有文件", isOn: $viewModel.downloadForm.overwriteExisting)
            }

            HStack(spacing: 16) {
                SecureLabeledField(title: "Substack 邮箱", text: $viewModel.downloadForm.substackEmail, placeholder: "仅付费模式需要")
                SecureLabeledField(title: "Substack 密码", text: $viewModel.downloadForm.substackPassword, placeholder: "仅付费模式需要", secure: true)
            }
        }
        .cardStyle()
    }
}

private struct TranslationFormView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("翻译配置")
                .font(.headline)

            Picker("翻译范围", selection: $viewModel.translationForm.scope) {
                ForEach(TranslationScope.allCases) { scope in
                    Text(scope.title).tag(scope)
                }
            }
            .pickerStyle(.segmented)

            DirectoryField(
                title: "来源路径",
                text: $viewModel.translationForm.sourcePath,
                buttonTitle: viewModel.translationForm.scope == .file ? "选择文件" : "选择文件夹",
                action: { viewModel.chooseTranslationSource(scope: viewModel.translationForm.scope) }
            )

            DirectoryField(
                title: "翻译后输出目录",
                text: $viewModel.translationForm.outputDirectory,
                action: viewModel.chooseTranslationOutputDirectory
            )

            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("目标语言")
                        .font(.subheadline.weight(.medium))
                    Picker("目标语言", selection: $viewModel.translationForm.language) {
                        ForEach(TranslationLanguage.allCases) { language in
                            Text(language.title).tag(language)
                        }
                    }
                    .pickerStyle(.menu)
                }

                Toggle("覆盖已有文件", isOn: $viewModel.translationForm.overwriteExisting)
                    .padding(.top, 22)
            }

            HStack(spacing: 16) {
                SecureLabeledField(title: "OpenAI API Key", text: $viewModel.translationForm.openAIKey, placeholder: "sk-...", secure: true)
                LabeledTextField(title: "模型", text: $viewModel.translationForm.model, placeholder: "gpt-5-mini")
            }

            LabeledTextField(title: "OpenAI Base URL", text: $viewModel.translationForm.openAIBaseURL, placeholder: "https://api.openai.com/v1")

            VStack(alignment: .leading, spacing: 8) {
                Text("接口模式")
                    .font(.subheadline.weight(.medium))
                Picker("接口模式", selection: $viewModel.translationForm.apiMode) {
                    ForEach(APIMode.allCases) { mode in
                        Text(mode.title).tag(mode)
                    }
                }
                .pickerStyle(.segmented)
                Text("自动模式会根据接口类型选择更稳的调用方式；第三方兼容接口会优先使用 Chat Completions。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            OutputFormatPicker(formats: $viewModel.translationForm.outputFormats)

            Text("翻译模式不会重新抓取网页，而是直接读取已下载的 Markdown 文件，并生成新的翻译 Markdown / HTML / PDF。")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .cardStyle()
    }
}

private struct ActionBar: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        HStack(spacing: 12) {
            Button(action: viewModel.runCurrentWorkflow) {
                Label(viewModel.workflowMode == .download ? "开始下载" : "开始翻译", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!viewModel.canRun)

            Button("打开输出目录") {
                let path = viewModel.workflowMode == .download
                    ? viewModel.downloadForm.htmlDirectory
                    : viewModel.translationForm.outputDirectory
                viewModel.openPath(path)
            }
            .buttonStyle(.bordered)

            Button("清空日志") {
                viewModel.clearLogs()
            }
            .buttonStyle(.bordered)
        }
        .cardStyle()
    }
}

private struct LogPanelView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("运行日志")
                .font(.title3.bold())

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(viewModel.logs) { entry in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(entry.timestamp.formatted(date: .omitted, time: .standard))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                Text(entry.message)
                                    .font(.system(.body, design: .monospaced))
                                    .foregroundStyle(.primary)
                                    .textSelection(.enabled)
                            }
                            .id(entry.id)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                            .background(Color(nsColor: .textBackgroundColor))
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                    .stroke(Color.primary.opacity(0.06), lineWidth: 1)
                            )
                        }
                    }
                    .padding(.bottom, 8)
                }
                .onChange(of: viewModel.logs.count) { _ in
                    if let id = viewModel.logs.last?.id {
                        withAnimation {
                            proxy.scrollTo(id, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .padding(24)
        .background(
            LinearGradient(
                colors: [
                    Color(nsColor: .underPageBackgroundColor),
                    Color(nsColor: .windowBackgroundColor)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
    }
}

private struct OutputFormatPicker: View {
    @Binding var formats: OutputFormats

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("输出格式")
                .font(.subheadline.weight(.medium))
            HStack(spacing: 16) {
                Toggle("Markdown", isOn: $formats.markdown)
                Toggle("HTML", isOn: $formats.html)
                Toggle("PDF", isOn: $formats.pdf)
            }
        }
        .padding(.top, 22)
    }
}

struct SettingsView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("设置")
                .font(.title2.bold())

            Text("SwiftUI 客户端直接调用当前仓库下的 Python 后端：`.venv/bin/python3 substack_scraper.py`。如果你移动了仓库目录，需要重新在新目录中运行。")
                .foregroundStyle(.secondary)

            LabeledContent("当前工作目录") {
                Text(FileManager.default.currentDirectoryPath)
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
            }

            LabeledContent("Python 解释器") {
                Text(FileManager.default.currentDirectoryPath + "/.venv/bin/python3")
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
            }

            Spacer()
        }
    }
}

private struct StatusBadge: View {
    let title: String
    let state: AppTaskState

    var body: some View {
        Text(title)
            .font(.footnote.weight(.semibold))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(backgroundColor.opacity(0.16))
            .foregroundStyle(backgroundColor)
            .clipShape(Capsule())
    }

    private var backgroundColor: Color {
        switch state {
        case .idle:
            return .gray
        case .running:
            return .orange
        case .success:
            return .green
        case .failure:
            return .red
        }
    }
}

private struct ProgressBadge: View {
    let progress: TaskProgress

    var body: some View {
        HStack(spacing: 10) {
            ProgressView(value: progress.fractionCompleted)
                .frame(width: 90)
            Text(progress.summary)
                .font(.footnote.monospacedDigit())
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color.secondary.opacity(0.08))
        .clipShape(Capsule())
    }
}

private struct LabeledTextField: View {
    let title: String
    @Binding var text: String
    let placeholder: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline.weight(.medium))
            TextField(placeholder, text: $text)
                .textFieldStyle(.roundedBorder)
        }
    }
}

private struct SecureLabeledField: View {
    let title: String
    @Binding var text: String
    let placeholder: String
    var secure: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline.weight(.medium))
            if secure {
                SecureField(placeholder, text: $text)
                    .textFieldStyle(.roundedBorder)
            } else {
                TextField(placeholder, text: $text)
                    .textFieldStyle(.roundedBorder)
            }
        }
    }
}

private struct DirectoryField: View {
    let title: String
    @Binding var text: String
    var buttonTitle: String = "选择"
    let action: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline.weight(.medium))
            HStack(spacing: 10) {
                TextField("", text: $text)
                    .textFieldStyle(.roundedBorder)
                Button(buttonTitle, action: action)
                    .buttonStyle(.bordered)
            }
        }
    }
}

private extension View {
    func cardStyle() -> some View {
        self
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(Color.primary.opacity(0.05), lineWidth: 1)
            )
    }
}
