pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

Item {
    id: page
    required property var watchlist

    property string filterText: ""
    property int searchActiveIndex: -1
    property int selectedRow: -1
    property var selectedItem: ({})

    function number(value, digits) {
        return typeof value === "number" && isFinite(value)
                ? value.toLocaleString(Qt.locale("en_US"), "f", digits) : "数据不足"
    }

    function percent(value) {
        return typeof value === "number" && isFinite(value)
                ? (value >= 0 ? "+" : "") + number(value, 2) + "%" : "—"
    }

    function peerNames(value) {
        if (!value)
            return ""
        if (typeof value.join === "function")
            return value.join("、")
        if (typeof value.count === "number" && typeof value.get === "function") {
            const names = []
            for (let i = 0; i < value.count; ++i)
                names.push(value.get(i).modelData || value.get(i).value || "")
            return names.filter(name => name.length > 0).join("、")
        }
        return String(value)
    }

    function groupName(groupId) {
        if (groupId === null || typeof groupId === "undefined" || groupId < 0)
            return ""
        for (let i = 0; i < page.watchlist.groups.length; ++i) {
            const group = page.watchlist.groups[i]
            if (Number(group.id) === Number(groupId))
                return group.name
        }
        return "未知分区"
    }

    function category(sector, industry, groupId) {
        const custom = groupName(groupId)
        if (custom.length > 0)
            return "自定义 · " + custom
        if (sector && industry)
            return sector + " · " + industry
        return sector || industry || "未分类"
    }

    function openSettings(index) {
        page.selectedRow = index
        page.selectedItem = page.watchlist.watchlisted.itemAt(index)
        settingsSheet.open()
    }

    function threshold(value, key) {
        const raw = String(value).trim()
        if (raw.length === 0)
            return ({[key]: null})
        const parsed = Number(raw)
        if (!isFinite(parsed) || parsed <= 0)
            return null
        return ({[key]: parsed})
    }

    function candidateDetails(candidate) {
        const fields = [candidate.exchange, candidate.country_code,
                        candidate.instrument_type, candidate.currency]
        const values = []
        for (let i = 0; i < fields.length; ++i)
            if (fields[i])
                values.push(fields[i])
        return values.length > 0 ? values.join(" · ") : "证券资料待验证"
    }

    function moveSearch(delta) {
        const results = page.watchlist.searchResults
        if (!results || results.length === 0)
            return
        let index = page.searchActiveIndex < 0 ? (delta > 0 ? -1 : results.length) : page.searchActiveIndex
        for (let step = 0; step < results.length; ++step) {
            index = (index + delta + results.length) % results.length
            if (!Boolean(results[index].is_duplicate)) {
                page.searchActiveIndex = index
                return
            }
        }
    }

    function chooseSearch() {
        const results = page.watchlist.searchResults
        const index = page.searchActiveIndex >= 0 ? page.searchActiveIndex : 0
        if (results && results.length > index && !Boolean(results[index].is_duplicate)) {
            page.watchlist.addSecurity(results[index])
            searchField.clear()
            page.watchlist.clearSearch()
        }
    }

    Component.onCompleted: page.watchlist.setActive(page.visible)
    onVisibleChanged: page.watchlist.setActive(page.visible)
    Component.onDestruction: page.watchlist.setActive(false)

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight + Space.xl * 2
        clip: true

        ColumnLayout {
            id: contentColumn
            width: Math.max(0, page.width - Space.xl * 2)
            x: Space.xl
            y: Space.xl
            spacing: Space.md

            RowLayout {
                Layout.fillWidth: true
                spacing: Space.sm
                Label {
                    Layout.fillWidth: true
                    text: "自选股"
                    color: Theme.textPrimary
                    font.pixelSize: Type.largeTitle
                    font.weight: Font.DemiBold
                }
                AppButton {
                    text: "刷新"
                    kind: "secondary"
                    loading: page.watchlist.busy
                    Accessible.description: "重新读取自选股与同行数据"
                    onClicked: page.watchlist.refresh()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: errorLabel.visible ? errorLabel.implicitHeight + Space.md * 2 : 0
                visible: page.watchlist.error.length > 0
                radius: Radius.control
                color: Theme.selected
                border.width: Theme.borderWidth
                border.color: Theme.negative
                Label {
                    id: errorLabel
                    anchors.fill: parent
                    anchors.margins: Space.md
                    text: page.watchlist.error
                    color: Theme.textPrimary
                    font.pixelSize: Type.caption
                    wrapMode: Text.Wrap
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: page.width >= 760 ? 3 : 1
                columnSpacing: Space.sm
                rowSpacing: Space.sm
                Repeater {
                    model: [
                        {label: "自选股", value: page.watchlist.watchlistedCount},
                        {label: "观察分区", value: page.watchlist.sectionCount},
                        {label: "同行样本", value: page.watchlist.matchedCount}
                    ]
                    delegate: AppCard {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.minimumHeight: 78
                        padding: Space.md
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: Space.xxs
                            Label {
                                text: modelData.label
                                color: Theme.textSecondary
                                font.pixelSize: Type.caption
                            }
                            Label {
                                text: modelData.value
                                color: Theme.textPrimary
                                font.family: Type.numericFamily
                                font.pixelSize: Type.numericDisplay
                            }
                        }
                    }
                }
            }

            AppCard {
                Layout.fillWidth: true
                padding: Space.lg
                ColumnLayout {
                    anchors.fill: parent
                    spacing: Space.sm
                    Label {
                        text: "搜索并添加证券"
                        color: Theme.textPrimary
                        font.pixelSize: Type.title
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "候选来自已验证的 Yahoo/Finnhub 映射；不会根据国际代码猜测另一数据源。"
                        color: Theme.textSecondary
                        font.pixelSize: Type.caption
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Space.sm
                        AppTextField {
                            id: searchField
                            Layout.fillWidth: true
                            placeholderText: "搜索股票代码或名称"
                            Accessible.name: "搜索证券"
                            onTextChanged: {
                                page.searchActiveIndex = text.length > 0 ? 0 : -1
                                page.watchlist.search(text)
                            }
                            Keys.onDownPressed: function(event) {
                                page.moveSearch(1)
                                event.accepted = true
                            }
                            Keys.onUpPressed: function(event) {
                                page.moveSearch(-1)
                                event.accepted = true
                            }
                            Keys.onReturnPressed: function(event) {
                                page.chooseSearch()
                                event.accepted = true
                            }
                            Keys.onEscapePressed: {
                                clear()
                                page.watchlist.clearSearch()
                            }
                        }
                        AppButton {
                            text: "清除"
                            kind: "secondary"
                            visible: searchField.text.length > 0
                            onClicked: {
                                searchField.clear()
                                page.watchlist.clearSearch()
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        visible: page.watchlist.searchBusy || page.watchlist.searchError.length > 0
                                   || page.watchlist.searchResults.length > 0
                        implicitHeight: Math.min(332, Math.max(46, searchResults.implicitHeight + Space.sm * 2))
                        color: Theme.elevated
                        radius: Radius.control
                        border.width: Theme.borderWidth
                        border.color: page.watchlist.searchError.length > 0 ? Theme.negative : Theme.separator
                        AppStateView {
                            anchors.fill: parent
                            visible: page.watchlist.searchBusy || page.watchlist.searchError.length > 0
                            kind: page.watchlist.searchBusy ? "loading" : "error"
                            title: page.watchlist.searchBusy ? "正在搜索" : "搜索失败"
                            message: page.watchlist.searchError
                        }
                        ListView {
                            id: searchResults
                            anchors.fill: parent
                            anchors.margins: Space.xs
                            visible: !page.watchlist.searchBusy && page.watchlist.searchError.length === 0
                            clip: true
                            model: page.watchlist.searchResults
                            currentIndex: page.searchActiveIndex
                            boundsBehavior: Flickable.StopAtBounds
                            delegate: Button {
                                id: resultButton
                                required property var modelData
                                width: ListView.view.width
                                implicitHeight: 52
                                enabled: !Boolean(modelData.is_duplicate)
                                Accessible.name: (modelData.display_symbol || "证券") + " " + (modelData.display_name || "")
                                Accessible.description: enabled ? "添加到自选股" : "已添加"
                                onClicked: {
                                    page.watchlist.addSecurity(modelData)
                                    searchField.clear()
                                    page.watchlist.clearSearch()
                                }
                                background: Rectangle {
                                    radius: Radius.control
                                    color: resultButton.down ? Theme.pressed : ListView.isCurrentItem ? Theme.selected
                                           : resultButton.hovered ? Theme.hover : "transparent"
                                    border.width: resultButton.visualFocus || Theme.contrast ? 2 : 0
                                    border.color: resultButton.visualFocus ? Theme.focus : Theme.separator
                                }
                                contentItem: RowLayout {
                                    spacing: Space.sm
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: Space.xxs
                                        Label {
                                            text: modelData.display_symbol || "未知代码"
                                            color: Theme.textPrimary
                                            font.family: Type.numericFamily
                                            font.weight: Font.DemiBold
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: (modelData.display_name || "证券资料待验证") + " · " + page.candidateDetails(modelData)
                                            color: Theme.textSecondary
                                            font.pixelSize: Type.caption
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Label {
                                        visible: Boolean(modelData.is_duplicate) || Boolean(modelData.is_local)
                                        text: modelData.is_duplicate ? "已添加" : "已入库"
                                        color: modelData.is_duplicate ? Theme.textTertiary : Theme.positive
                                        font.pixelSize: Type.caption
                                    }
                                }
                            }
                        }
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: page.width >= 980 ? 2 : 1
                columnSpacing: Space.md
                rowSpacing: Space.md

                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 360
                    padding: Space.lg
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Space.sm
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "自选列表"
                                color: Theme.textPrimary
                                font.pixelSize: Type.title
                                font.weight: Font.DemiBold
                            }
                            AppTextField {
                                Layout.preferredWidth: page.width >= 760 ? 190 : 140
                                placeholderText: "过滤已加载自选股"
                                Accessible.name: "过滤自选股"
                                onTextChanged: page.filterText = text.trim().toUpperCase()
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "按服务端 display_order 保持稳定；实时行情只更新当前行。"
                            color: Theme.textSecondary
                            font.pixelSize: Type.caption
                            wrapMode: Text.Wrap
                        }
                        ListView {
                            id: watchlistView
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: Space.xs
                            boundsBehavior: Flickable.StopAtBounds
                            model: page.watchlist.watchlisted
                            section.property: "sectionName"
                            section.delegate: Label {
                                required property string section
                                width: ListView.view.width
                                height: 34
                                leftPadding: Space.sm
                                verticalAlignment: Text.AlignVCenter
                                text: section
                                color: Theme.textSecondary
                                font.pixelSize: Type.caption
                                font.weight: Font.DemiBold
                            }
                            delegate: Item {
                                id: watchRow
                                required property int id
                                required property string ticker
                                required property string companyName
                                required property string officialSector
                                required property string officialIndustry
                                required property var userGroupId
                                required property var price
                                required property var changePercent
                                required property bool hasPrice
                                required property int displayOrder
                                width: ListView.view.width
                                property bool matches: page.filterText.length === 0
                                                      || ticker.toUpperCase().indexOf(page.filterText) >= 0
                                                      || companyName.toUpperCase().indexOf(page.filterText) >= 0
                                height: matches ? rowButton.implicitHeight : 0
                                visible: matches

                                Button {
                                    id: rowButton
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    implicitHeight: 78
                                    Accessible.name: ticker + "，" + (companyName || "名称数据不足")
                                    Accessible.description: "打开自选股设置"
                                    onClicked: page.openSettings(index)
                                    background: Rectangle {
                                        radius: Radius.control
                                        color: rowButton.down ? Theme.pressed : rowButton.hovered ? Theme.hover : Theme.contentRaised
                                        border.width: rowButton.visualFocus || Theme.contrast ? 2 : 0
                                        border.color: rowButton.visualFocus ? Theme.focus : Theme.separator
                                    }
                                    contentItem: RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: Space.md
                                        spacing: Space.md
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: Space.xxs
                                            Label {
                                                text: ticker
                                                color: Theme.textPrimary
                                                font.family: Type.numericFamily
                                                font.pixelSize: Type.numericBody
                                                font.weight: Font.DemiBold
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                text: companyName || "名称数据不足"
                                                color: Theme.textSecondary
                                                font.pixelSize: Type.caption
                                                elide: Text.ElideRight
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                text: page.category(officialSector, officialIndustry, userGroupId)
                                                color: Theme.textTertiary
                                                font.pixelSize: Type.micro
                                                elide: Text.ElideRight
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.preferredWidth: 120
                                            spacing: Space.xxs
                                            Label {
                                                Layout.fillWidth: true
                                                text: hasPrice ? page.number(price, 2) : "数据不足"
                                                color: Theme.textPrimary
                                                font.family: Type.numericFamily
                                                font.pixelSize: Type.numericBody
                                                horizontalAlignment: Text.AlignRight
                                            }
                                            Label {
                                                Layout.fillWidth: true
                                                text: page.percent(changePercent)
                                                color: typeof changePercent !== "number" || !isFinite(changePercent)
                                                       ? Theme.textTertiary : changePercent >= 0 ? Theme.positive : Theme.negative
                                                font.family: Type.numericFamily
                                                font.pixelSize: Type.caption
                                                horizontalAlignment: Text.AlignRight
                                            }
                                        }
                                        Label {
                                            text: "›"
                                            color: Theme.textTertiary
                                            font.pixelSize: Type.title
                                        }
                                    }
                                }
                            }
                        }
                        AppStateView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            visible: !page.watchlist.busy && page.watchlist.watchlistedCount === 0
                            kind: "empty"
                            title: "自选股为空"
                            message: "搜索并添加第一只证券。"
                        }
                        AppStateView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            visible: page.watchlist.busy && !page.watchlist.loaded
                            kind: "loading"
                            title: "正在加载"
                            message: "读取自选股、分区和同行样本。"
                        }
                    }
                }

                AppCard {
                    Layout.fillWidth: true
                    Layout.minimumHeight: 360
                    padding: Space.lg
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Space.sm
                        Label {
                            text: "观察分区"
                            color: Theme.textPrimary
                            font.pixelSize: Type.title
                            font.weight: Font.DemiBold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "自定义分区只改变展示归类；恢复官方分类不会删除行业资料。"
                            color: Theme.textSecondary
                            font.pixelSize: Type.caption
                            wrapMode: Text.Wrap
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            AppTextField {
                                id: groupNameField
                                Layout.fillWidth: true
                                placeholderText: "新分区名称"
                                Accessible.name: "新建观察分区"
                                Keys.onReturnPressed: {
                                    page.watchlist.createGroup(text)
                                    clear()
                                }
                            }
                            AppButton {
                                text: "新建"
                                kind: "primary"
                                onClicked: {
                                    page.watchlist.createGroup(groupNameField.text)
                                    groupNameField.clear()
                                }
                            }
                        }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: Space.xs
                            model: page.watchlist.groups
                            delegate: Rectangle {
                                required property var modelData
                                width: ListView.view.width
                                height: 44
                                radius: Radius.control
                                color: Theme.contentRaised
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: Space.sm
                                    spacing: Space.xs
                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        color: Theme.textPrimary
                                        elide: Text.ElideRight
                                    }
                                    AppButton {
                                        text: "↑"
                                        kind: "secondary"
                                        implicitWidth: 34
                                        leftPadding: 0
                                        rightPadding: 0
                                        Accessible.name: modelData.name + " 上移"
                                        onClicked: page.watchlist.moveGroup(modelData.id, Math.max(0, Number(modelData.displayOrder) - 1))
                                    }
                                    AppButton {
                                        text: "↓"
                                        kind: "secondary"
                                        implicitWidth: 34
                                        leftPadding: 0
                                        rightPadding: 0
                                        Accessible.name: modelData.name + " 下移"
                                        onClicked: page.watchlist.moveGroup(modelData.id, Number(modelData.displayOrder) + 1)
                                    }
                                    AppButton {
                                        text: "改名"
                                        kind: "secondary"
                                        onClicked: renameDialog.openFor(modelData.id, modelData.name)
                                    }
                                    AppButton {
                                        text: "删除"
                                        kind: "danger"
                                        onClicked: page.watchlist.deleteGroup(modelData.id)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            AppCard {
                Layout.fillWidth: true
                Layout.minimumHeight: 220
                padding: Space.lg
                ColumnLayout {
                    anchors.fill: parent
                    spacing: Space.sm
                    Label {
                        text: "匹配股票 · 同行估值"
                        color: Theme.textPrimary
                        font.pixelSize: Type.title
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "这些证券只用于已有估值模型的同行比较，不会自动加入自选股。"
                        color: Theme.textSecondary
                        font.pixelSize: Type.caption
                        wrapMode: Text.Wrap
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(240, contentHeight)
                        implicitHeight: contentHeight
                        clip: true
                        spacing: Space.xs
                        model: page.watchlist.matched
                        delegate: Button {
                            id: matchedRow
                            required property string ticker
                            required property string companyName
                            required property var peerReferencedBy
                            width: ListView.view.width
                            implicitHeight: 58
                            Accessible.name: matchedRow.ticker + "，" + (matchedRow.companyName || "名称数据不足")
                            Accessible.description: "加入自选股并启动完整同步"
                            onClicked: page.watchlist.promoteMatched(matchedRow.ticker)
                            background: Rectangle {
                                radius: Radius.control
                                color: matchedRow.down ? Theme.pressed : matchedRow.hovered ? Theme.hover : Theme.contentRaised
                                border.width: matchedRow.visualFocus || Theme.contrast ? 2 : 0
                                border.color: matchedRow.visualFocus ? Theme.focus : Theme.separator
                            }
                            contentItem: RowLayout {
                                anchors.fill: parent
                                anchors.margins: Space.md
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Space.xxs
                                    Label { text: matchedRow.ticker; color: Theme.textPrimary; font.family: Type.numericFamily; font.weight: Font.DemiBold }
                                    Label {
                                        Layout.fillWidth: true
                                        text: (matchedRow.companyName || "名称数据不足") + " · " + page.peerNames(matchedRow.peerReferencedBy)
                                        color: Theme.textSecondary
                                        font.pixelSize: Type.caption
                                        elide: Text.ElideRight
                                    }
                                }
                                Label { text: "加入自选股"; color: Theme.accent; font.pixelSize: Type.caption }
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: page.watchlist.matchedCount === 0
                        text: "当前没有匹配同行样本。"
                        color: Theme.textTertiary
                        font.pixelSize: Type.caption
                    }
                }
            }
        }
    }

    AppSheet {
        id: settingsSheet
        height: Math.min(620, Overlay.overlay ? Overlay.overlay.height - Space.xxxl * 2 : 620)
        contentItem: Flickable {
            contentWidth: width
            contentHeight: settingsContent.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ColumnLayout {
                id: settingsContent
                width: parent.width
                spacing: Space.md
            Label {
                text: (page.selectedItem.ticker || "自选股") + " 设置"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            Label {
                Layout.fillWidth: true
                text: (page.selectedItem.companyName || "名称数据不足") + " · "
                      + page.category(page.selectedItem.officialSector, page.selectedItem.officialIndustry,
                                       page.selectedItem.userGroupId)
                color: Theme.textSecondary
                font.pixelSize: Type.caption
                wrapMode: Text.Wrap
            }
            ComboBox {
                id: groupCombo
                Layout.fillWidth: true
                model: {
                    const values = [{id: -1, name: "恢复官方分类"}]
                    for (let i = 0; i < page.watchlist.groups.length; ++i)
                        values.push(page.watchlist.groups[i])
                    return values
                }
                textRole: "name"
                valueRole: "id"
                currentIndex: {
                    const selected = page.selectedItem.userGroupId
                    if (selected === null || typeof selected === "undefined")
                        return 0
                    for (let i = 0; i < model.length; ++i)
                        if (Number(model[i].id) === Number(selected))
                            return i
                    return 0
                }
                Accessible.name: "自定义分区"
                onActivated: {
                    const value = currentIndex === 0 ? null : Number(model[currentIndex].id)
                    page.watchlist.updateWatchlist(page.selectedItem.id, {user_group_id: value})
                }
            }
            AppSwitch {
                text: "波动报警"
                checked: Boolean(page.selectedItem.alertEnabled)
                Accessible.name: "波动报警"
                onToggled: {
                    page.watchlist.updateWatchlist(page.selectedItem.id, {alert_enabled: checked})
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; text: "显示顺序"; color: Theme.textSecondary }
                AppButton {
                    text: "↑"
                    kind: "secondary"
                    Accessible.name: "自选股上移"
                    onClicked: page.watchlist.moveWatchlist(page.selectedItem.id, Math.max(0, Number(page.selectedItem.displayOrder) - 1))
                }
                AppButton {
                    text: "↓"
                    kind: "secondary"
                    Accessible.name: "自选股下移"
                    onClicked: page.watchlist.moveWatchlist(page.selectedItem.id, Number(page.selectedItem.displayOrder) + 1)
                }
            }
            Label { text: "波动阈值"; color: Theme.textPrimary; font.weight: Font.DemiBold }
            Repeater {
                model: [
                    {label: "20 分钟", key: "threshold_20m", value: page.selectedItem.threshold20m},
                    {label: "1 小时", key: "threshold_1h", value: page.selectedItem.threshold1h},
                    {label: "当日", key: "threshold_day", value: page.selectedItem.thresholdDay}
                ]
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    AppTextField {
                        id: thresholdField
                        Layout.fillWidth: true
                        text: modelData.value === null || typeof modelData.value === "undefined" ? "" : String(modelData.value)
                        placeholderText: modelData.label + "（默认）"
                        Accessible.name: modelData.label + "阈值"
                    }
                    AppButton {
                        text: "保存"
                        kind: "secondary"
                        onClicked: {
                            const payload = page.threshold(thresholdField.text, modelData.key)
                            if (payload !== null)
                                page.watchlist.updateWatchlist(page.selectedItem.id, payload)
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.minimumHeight: Space.sm }
            AppButton {
                Layout.fillWidth: true
                text: "从自选股删除"
                kind: "danger"
                onClicked: {
                    page.watchlist.removeWatchlist(page.selectedItem.id)
                    settingsSheet.close()
                }
            }
            }
        }
    }

    Popup {
        id: renameDialog
        property int groupId: 0
        property string originalName: ""
        function openFor(id, name) {
            groupId = id
            originalName = name
            renameField.text = name
            open()
            renameField.forceActiveFocus()
        }
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        anchors.centerIn: Overlay.overlay
        width: Math.min(380, Overlay.overlay ? Overlay.overlay.width - Space.xxxl * 2 : 380)
        padding: Space.xl
        background: GlassSurface { material: "elevated"; cornerRadius: Radius.panel }
        contentItem: ColumnLayout {
            spacing: Space.md
            Label { text: "重命名分区"; color: Theme.textPrimary; font.pixelSize: Type.title; font.weight: Font.DemiBold }
            AppTextField { id: renameField; Layout.fillWidth: true; placeholderText: "分区名称"; Accessible.name: "分区名称"; Keys.onReturnPressed: renameButton.clicked() }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AppButton { text: "取消"; kind: "secondary"; onClicked: renameDialog.close() }
                AppButton {
                    id: renameButton
                    text: "保存"
                    kind: "primary"
                    onClicked: {
                        page.watchlist.renameGroup(renameDialog.groupId, renameField.text)
                        renameDialog.close()
                    }
                }
            }
        }
    }
}
