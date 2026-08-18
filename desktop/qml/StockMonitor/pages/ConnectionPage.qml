import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: page
    required property var environment
    required property var session
    padding: Space.xxxl
    background: Rectangle {
        color: Theme.canvas
    }

    AppCard {
        anchors.centerIn: parent
        width: Math.min(520, parent.width - Space.xxxl)
        padding: Space.xxl

        ColumnLayout {
            anchors.fill: parent
            spacing: Space.md

            Label {
                text: "Stock Monitor"
                color: Theme.textPrimary
                font.family: Type.family
                font.pixelSize: Type.display
                font.weight: Font.DemiBold
            }
            Label {
                text: "连接现有 FastAPI 服务"
                color: Theme.textSecondary
                font.pixelSize: Type.body
            }

            Label {
                text: "服务地址"
                color: Theme.textPrimary
                font.pixelSize: Type.caption
            }
            AppTextField {
                id: baseUrl
                focus: true
                Layout.fillWidth: true
                text: page.environment.baseUrl
                placeholderText: "https://stocks.example.com"
                enabled: !page.session.busy
                invalid: page.environment.validationError.length > 0
                errorText: page.environment.validationError
                Accessible.name: "服务地址"
                onEditingFinished: page.environment.setBaseUrl(text)
            }
            Label {
                Layout.fillWidth: true
                visible: page.environment.validationError.length > 0
                text: page.environment.validationError
                color: Theme.negative
                font.pixelSize: Type.caption
                wrapMode: Text.Wrap
            }
            AppButton {
                text: page.session.busy ? "检查中…" : "检查连接"
                enabled: !page.session.busy
                Accessible.name: text
                onClicked: {
                    if (page.environment.setBaseUrl(baseUrl.text))
                        page.session.testConnection();
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.borderWidth
                color: Theme.separator
            }

            Label {
                text: "用户名"
                color: Theme.textPrimary
                font.pixelSize: Type.caption
            }
            AppTextField {
                id: username
                Layout.fillWidth: true
                enabled: !page.session.busy
                Accessible.name: "用户名"
            }
            Label {
                text: "密码"
                color: Theme.textPrimary
                font.pixelSize: Type.caption
            }
            AppTextField {
                id: password
                Layout.fillWidth: true
                echoMode: TextInput.Password
                passwordCharacter: "●"
                enabled: !page.session.busy
                Accessible.name: "密码"
                onAccepted: loginButton.clicked()
            }
            AppSwitch {
                id: remember
                text: "服务端延长会话（令牌仍仅保存在内存）"
                enabled: !page.session.busy
            }
            AppButton {
                id: loginButton
                Layout.fillWidth: true
                kind: "primary"
                text: page.session.busy ? "登录中…" : "登录"
                enabled: !page.session.busy
                Accessible.name: text
                onClicked: {
                    if (page.environment.setBaseUrl(baseUrl.text))
                        page.session.login(username.text, password.text, remember.checked);
                }
            }

            Label {
                Layout.fillWidth: true
                visible: page.session.statusText.length > 0
                text: page.session.statusText
                color: page.session.connected ? Theme.positive : Theme.textSecondary
                font.pixelSize: Type.caption
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                visible: page.session.error.length > 0
                text: page.session.error
                color: Theme.negative
                font.pixelSize: Type.caption
                wrapMode: Text.Wrap
            }
        }
    }
}
