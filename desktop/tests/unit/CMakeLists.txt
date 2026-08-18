qt_add_executable(stock-monitor-desktop-tests tst_foundation.cpp)
target_link_libraries(stock-monitor-desktop-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-desktop-tests COMMAND stock-monitor-desktop-tests)
