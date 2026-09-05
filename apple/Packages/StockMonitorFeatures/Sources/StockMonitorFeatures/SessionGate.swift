import Observation
import StockMonitorCore
import SwiftUI

@MainActor
@Observable
public final class AppSessionModel {
    public private(set) var state: AuthState = .restoring
    public var username = ""
    public var password = ""
    public var remember = true
    public private(set) var isSubmitting = false
    public private(set) var message: String?
    private let session: AuthSession

    public init(session: AuthSession) {
        self.session = session
    }

    public func restore() async {
        await session.restore()
        state = await session.state
    }

    public func login() async {
        guard !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !password.isEmpty else {
            message = "请输入用户名和密码"
            return
        }
        isSubmitting = true
        defer { isSubmitting = false; password = "" }
        do {
            _ = try await session.login(username: username, password: password, remember: remember)
            state = await session.state
            message = nil
        } catch {
            state = await session.state
            message = Self.message(for: error)
        }
    }

    public func logout() async {
        await session.logout()
        state = .signedOut
    }

    private static func message(for error: Error) -> String {
        guard let error = error as? APIError else { return "登录失败，请稍后重试" }
        return switch error {
        case let .http(_, message, _): message ?? "用户名或密码不正确"
        case .transport: "无法连接服务器"
        default: "服务器响应无法读取"
        }
    }
}

public struct SessionGateView<Content: View>: View {
    @State private var model: AppSessionModel
    private let content: (SessionIdentity) -> Content

    public init(model: AppSessionModel, @ViewBuilder content: @escaping (SessionIdentity) -> Content) {
        _model = State(initialValue: model)
        self.content = content
    }

    public var body: some View {
        Group {
            switch model.state {
            case let .authenticated(identity): content(identity)
            case .restoring: ProgressView("正在恢复安全会话…").controlSize(.large)
            case .offline:
                ContentUnavailableView("当前离线", systemImage: "wifi.slash", description: Text("恢复网络后重试登录；私有数据不会从缓存打开。"))
            case .signedOut, .failed: LoginView(model: model)
            }
        }
        .task {
            if case .restoring = model.state {
                await model.restore()
            }
        }
    }
}

private struct LoginView: View {
    @Bindable var model: AppSessionModel

    var body: some View {
        VStack(spacing: 22) {
            Image(systemName: "chart.line.uptrend.xyaxis")
                .font(.system(size: 44, weight: .medium))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            VStack(spacing: 6) {
                Text("Stock Monitor").font(.largeTitle.bold())
                Text("连接你的自托管市场工作台").foregroundStyle(.secondary)
            }
            Form {
                TextField("用户名", text: $model.username)
                    .textContentType(.username)
                SecureField("密码", text: $model.password)
                    .textContentType(.password)
                    .onSubmit { Task { await model.login() } }
                Toggle("在这台 Mac 上保持登录", isOn: $model.remember)
                if let message = model.message {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("login.error")
                }
            }
            .formStyle(.grouped)
            Button { Task { await model.login() } } label: {
                if model.isSubmitting {
                    ProgressView().controlSize(.small)
                } else {
                    Text("登录")
                }
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(model.isSubmitting)
        }
        .padding(40)
        .frame(width: 440)
        .accessibilityIdentifier("login.view")
    }
}
