cmake_minimum_required(VERSION 3.24)

project(StockMonitorDesktop VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Network Sql Qml Quick QuickControls2 Test)
# Keyring storage for refresh tokens; fail-closed session-only without it.
find_package(Qt6Keychain QUIET)
if(Qt6Keychain_FOUND)
    message(STATUS "QtKeychain found: refresh tokens persist to the OS credential store")
else()
    message(WARNING "Qt6Keychain not found: token vault degrades to session-only memory")
endif()

qt_standard_project_setup(REQUIRES 6.8)

qt_add_library(stock-monitor-core STATIC
    src/app/AppEnvironment.cpp
    src/app/AppEnvironment.h
    src/app/SessionStore.cpp
    src/app/SessionStore.h
    src/app/TokenVault.cpp
    src/app/TokenVault.h
    src/cache/CacheStore.cpp
    src/cache/CacheStore.h
    src/network/ApiClient.cpp
    src/network/ApiClient.h
    src/network/ApiError.cpp
    src/network/ApiError.h
    src/network/RequestHandle.cpp
    src/network/RequestHandle.h
    src/network/SseParser.cpp
    src/network/SseParser.h
    src/network/SseStream.cpp
    src/network/SseStream.h
)
target_include_directories(stock-monitor-core PUBLIC src)
target_link_libraries(stock-monitor-core PUBLIC Qt6::Core Qt6::Network Qt6::Sql)
if(Qt6Keychain_FOUND)
    target_compile_definitions(stock-monitor-core PUBLIC STOCK_MONITOR_HAVE_QTKEYCHAIN)
    target_link_libraries(stock-monitor-core PRIVATE Qt6Keychain::Qt6Keychain)
endif()

qt_add_executable(stock-monitor-desktop src/main.cpp)
target_link_libraries(stock-monitor-desktop PRIVATE
    stock-monitor-core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2
)

set_source_files_properties(
    qml/StockMonitor/theme/Theme.qml
    qml/StockMonitor/theme/Type.qml
    qml/StockMonitor/theme/Space.qml
    qml/StockMonitor/theme/Radius.qml
    qml/StockMonitor/theme/Elevation.qml
    qml/StockMonitor/motion/Motion.qml
    PROPERTIES QT_QML_SINGLETON_TYPE TRUE
)

qt_add_qml_module(stock-monitor-desktop
    URI StockMonitor
    VERSION 1.0
    QML_FILES
        qml/StockMonitor/Main.qml
        qml/StockMonitor/Playground.qml
        qml/StockMonitor/Showcase.qml
        qml/StockMonitor/shell/AppShell.qml
        qml/StockMonitor/pages/ConnectionPage.qml
        qml/StockMonitor/theme/Theme.qml
        qml/StockMonitor/theme/Type.qml
        qml/StockMonitor/theme/Space.qml
        qml/StockMonitor/theme/Radius.qml
        qml/StockMonitor/theme/Elevation.qml
        qml/StockMonitor/motion/Motion.qml
        qml/StockMonitor/controls/AppButton.qml
        qml/StockMonitor/controls/AppCard.qml
        qml/StockMonitor/controls/AppMenu.qml
        qml/StockMonitor/controls/AppMenuItem.qml
        qml/StockMonitor/controls/AppNavButton.qml
        qml/StockMonitor/controls/AppSheet.qml
        qml/StockMonitor/controls/AppStateView.qml
        qml/StockMonitor/controls/AppSwitch.qml
        qml/StockMonitor/controls/AppTableRow.qml
        qml/StockMonitor/controls/AppTextField.qml
        qml/StockMonitor/controls/AppToolTip.qml
        qml/StockMonitor/controls/GlassSurface.qml
        qml/StockMonitor/controls/AppSegmentedControl.qml
        qml/StockMonitor/controls/AppSearchField.qml
        qml/StockMonitor/controls/WindowChrome.qml
)

install(TARGETS stock-monitor-desktop RUNTIME DESTINATION bin)

enable_testing()
add_subdirectory(tests/unit)
# Contract fixtures keep this suite honest about real server response shapes.
target_compile_definitions(stock-monitor-contract-tests PRIVATE
    STOCK_MONITOR_CONTRACT_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/contract/fixtures"
)

find_program(QMLTESTRUNNER_EXECUTABLE qmltestrunner HINTS /usr/lib/qt6/bin REQUIRED)
file(MAKE_DIRECTORY ${CMAKE_BINARY_DIR}/test-qml-imports/StockMonitor)
file(COPY ${CMAKE_CURRENT_SOURCE_DIR}/qml/StockMonitor/
    DESTINATION ${CMAKE_BINARY_DIR}/test-qml-imports/StockMonitor)
add_custom_target(stock-monitor-qml-test-imports ALL
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${CMAKE_CURRENT_SOURCE_DIR}/qml/StockMonitor
        ${CMAKE_BINARY_DIR}/test-qml-imports/StockMonitor
)
configure_file(
    tests/qml/StockMonitor.qmldir.in
    ${CMAKE_BINARY_DIR}/test-qml-imports/StockMonitor/qmldir
    @ONLY
)
add_test(
    NAME stock-monitor-qml-tests
    COMMAND ${CMAKE_COMMAND} -E env QT_QPA_PLATFORM=offscreen
        ${QMLTESTRUNNER_EXECUTABLE}
        -input ${CMAKE_CURRENT_SOURCE_DIR}/tests/qml
        -import ${CMAKE_BINARY_DIR}/test-qml-imports
)
add_test(
    NAME stock-monitor-visual-smoke
    COMMAND /bin/sh ${CMAKE_CURRENT_SOURCE_DIR}/tests/visual/capture.sh
        $<TARGET_FILE:stock-monitor-desktop> ${CMAKE_BINARY_DIR}/visual-output
)
