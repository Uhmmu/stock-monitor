#include "app/AppEnvironment.h"
#include "app/SessionStore.h"
#include "app/TokenVault.h"
#include "cache/CacheStore.h"
#include "network/ApiClient.h"

#include <QGuiApplication>
#include <QElapsedTimer>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QQuickStyle>
#include <QScreen>
#include <QTimer>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <memory>

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("StockMonitor"));
    QCoreApplication::setApplicationName(QStringLiteral("StockMonitorDesktop"));
    QQuickStyle::setStyle(QStringLiteral("Basic"));

    AppEnvironment environment;
    ApiClient api;
    TokenVault vault(TokenVault::Backend::Keychain);
    CacheStore cache;
    SessionStore session(&environment, &api, &vault, &cache);

    QQmlApplicationEngine engine;
    const QStringList arguments = app.arguments();
    const bool playground = arguments.contains(QStringLiteral("--playground"));
    const bool showcase = arguments.contains(QStringLiteral("--showcase"));
    if (!playground && !showcase) {
        engine.setInitialProperties({
            {QStringLiteral("environment"), QVariant::fromValue(&environment)},
            {QStringLiteral("session"), QVariant::fromValue(&session)},
        });
        // Resume a remembered session once the shell is on screen.
        QTimer::singleShot(0, &session, &SessionStore::restoreSession);
    }
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app,
                     [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule(QStringLiteral("StockMonitor"), showcase ? QStringLiteral("Showcase")
                          : playground ? QStringLiteral("Playground") : QStringLiteral("Main"));

    const qsizetype screenshotIndex = arguments.indexOf(QStringLiteral("--screenshot"));
    if (arguments.contains(QStringLiteral("--frame-benchmark"))) {
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().value(0));
        if (!window)
            return 2;
        const auto screens = app.screens();
        auto fastest = std::max_element(screens.begin(), screens.end(), [](QScreen *left, QScreen *right) {
            return left->refreshRate() < right->refreshRate();
        });
        if (fastest != screens.end()) {
            window->setScreen(*fastest);
            const QRect area = (*fastest)->availableGeometry();
            window->setPosition(area.center() - QPoint(window->width() / 2, window->height() / 2));
        }
        auto samples = std::make_shared<QVector<double>>();
        auto elapsed = std::make_shared<QElapsedTimer>();
        auto previous = std::make_shared<qint64>(0);
        auto warmupFrames = std::make_shared<int>(20);
        elapsed->start();
        QObject::connect(window, &QQuickWindow::frameSwapped, &app,
                         [&app, window, samples, elapsed, previous, warmupFrames] {
            const qint64 now = elapsed->nsecsElapsed();
            if (*previous > 0) {
                if (*warmupFrames > 0)
                    --*warmupFrames;
                else
                    samples->append((now - *previous) / 1'000'000.0);
            }
            *previous = now;
            if (samples->size() >= 120) {
                std::sort(samples->begin(), samples->end());
                const qsizetype index = static_cast<qsizetype>(std::ceil(samples->size() * 0.95)) - 1;
                std::printf("frame_p95_ms=%.2f refresh_hz=%.2f\n", samples->at(index),
                            window->screen()->refreshRate());
                std::fflush(stdout);
                app.exit(0);
                return;
            }
        });
        auto *framePump = new QTimer(&app);
        framePump->setInterval(0);
        QObject::connect(framePump, &QTimer::timeout, window, &QQuickWindow::update);
        framePump->start();
        QTimer::singleShot(10000, &app, [&app] { app.exit(3); });
    } else if (screenshotIndex >= 0 && screenshotIndex + 1 < arguments.size()) {
        const QString output = arguments.at(screenshotIndex + 1);
        QTimer::singleShot(1200, &app, [&app, &engine, output] {
            auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().value(0));
            app.exit(window && window->grabWindow().save(output) ? 0 : 2);
        });
    } else if (arguments.contains(QStringLiteral("--smoke-test"))) {
        QTimer::singleShot(500, &app, &QCoreApplication::quit);
    }
    return app.exec();
}
