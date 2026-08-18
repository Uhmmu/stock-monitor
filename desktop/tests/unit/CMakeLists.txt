qt_add_executable(stock-monitor-desktop-tests tst_foundation.cpp)
target_link_libraries(stock-monitor-desktop-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-desktop-tests COMMAND stock-monitor-desktop-tests)

qt_add_executable(stock-monitor-network-tests tst_network.cpp)
target_link_libraries(stock-monitor-network-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-network-tests COMMAND stock-monitor-network-tests)

qt_add_executable(stock-monitor-cache-tests tst_cache.cpp)
target_link_libraries(stock-monitor-cache-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-cache-tests COMMAND stock-monitor-cache-tests)

qt_add_executable(stock-monitor-auth-tests tst_auth.cpp)
target_link_libraries(stock-monitor-auth-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-auth-tests COMMAND stock-monitor-auth-tests)

qt_add_executable(stock-monitor-contract-tests tst_contracts.cpp)
target_link_libraries(stock-monitor-contract-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-contract-tests COMMAND stock-monitor-contract-tests)

qt_add_executable(stock-monitor-dashboard-tests tst_dashboard.cpp)
target_link_libraries(stock-monitor-dashboard-tests PRIVATE stock-monitor-core Qt6::Test)
add_test(NAME stock-monitor-dashboard-tests COMMAND stock-monitor-dashboard-tests)
