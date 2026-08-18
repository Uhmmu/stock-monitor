import QtQuick
import QtQuick.Controls
import QtTest
import StockMonitor

TestCase {
    id: testCase
    name: "DesignSystem"
    when: windowShown
    width: 640
    height: 480

    Component {
        id: buttonComponent
        AppButton {
            text: "Continue"
        }
    }
    Component {
        id: fieldComponent
        AppTextField {
            placeholderText: "Symbol"
        }
    }
    Component {
        id: sheetComponent
        AppSheet {
            contentItem: Label {
                text: "Sheet"
            }
        }
    }
    Component {
        id: menuComponent
        AppMenu {
            AppMenuItem {
                text: "Refresh"
            }
        }
    }

    function cleanup() {
        Theme.previewMode = "";
        Theme.previewContrast = -1;
        Theme.previewReducedMotion = -1;
        Theme.previewReducedTransparency = -1;
        Theme.previewDensity = "";
    }

    function test_themeTokens() {
        Theme.previewMode = "dark";
        compare(Theme.dark, true);
        compare(Theme.canvas.toString(), "#080a0f");
        Theme.previewMode = "light";
        compare(Theme.dark, false);
        compare(Theme.canvas.toString(), "#f1f3f7");
        Theme.previewContrast = 1;
        compare(Theme.borderWidth, 2);
        compare(Radius.inset(Radius.panel, Space.sm), Radius.control);
        compare(Type.numericDisplay, 38);
    }

    function test_reducedPreferences() {
        Theme.previewReducedMotion = 1;
        compare(Motion.duration(Motion.normal), 0);
        Theme.previewReducedTransparency = 1;
        compare(Theme.glassRegular.toString(), Theme.chromeOpaque.toString());
        Theme.previewDensity = "compact";
        compare(Theme.compact, true);
    }

    function test_buttonStates() {
        const button = createTemporaryObject(buttonComponent, testCase);
        verify(button);
        compare(button.enabled, true);
        button.loading = true;
        compare(button.enabled, false);
        button.loading = false;
        button.enabled = false;
        compare(button.enabled, false);
        button.enabled = true;
        button.forceActiveFocus(Qt.TabFocusReason);
        tryCompare(button, "visualFocus", true);
    }

    function test_keyboardFocus() {
        const field = createTemporaryObject(fieldComponent, testCase);
        verify(field);
        field.forceActiveFocus(Qt.TabFocusReason);
        tryCompare(field, "activeFocus", true);
    }

    function test_sheetEscape() {
        Theme.previewReducedMotion = 1;
        const sheet = createTemporaryObject(sheetComponent, testCase);
        verify(sheet);
        sheet.open();
        tryCompare(sheet, "opened", true);
        keyClick(Qt.Key_Escape);
        tryCompare(sheet, "opened", false);
    }

    function test_menuEscape() {
        const menu = createTemporaryObject(menuComponent, testCase);
        verify(menu);
        menu.open();
        tryCompare(menu, "opened", true);
        keyClick(Qt.Key_Escape);
        tryCompare(menu, "opened", false);
    }
}
