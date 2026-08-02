# iPhone 前端

`frontend-ios/` 是独立于桌面 `frontend/` 的 React/Vite 应用。两端共用后端、Bearer Token、API 请求层和基础领域类型，但不共用页面布局或交互组件。

## 本地运行

先启动后端，然后分别启动两套前端：

```sh
cd frontend && npm install && npm run dev
cd frontend-ios && npm install && npm run dev
```

桌面端默认使用 Vite 的 `5173` 端口，iPhone 端使用 `5174`。两者都把 `/api` 代理到 `http://localhost:8000`。

## 构建与部署

```sh
cd frontend && npm run build
cd frontend-ios && npm run build
docker compose build frontend frontend-ios
docker compose up -d frontend frontend-ios caddy
```

Compose 部署后：

- `/`：桌面端；
- `/mobile/`：iPhone 端；
- `/api`：两端共用的后端 API（继续由现有同域代理链路处理）。

iPhone 前端的 Service Worker scope 限定在 `/mobile/`，不会缓存或覆盖桌面端资源。用户可在“更多”切回桌面版。

## 代码边界

- `packages/shared/src/api.ts`：API、Token、登录和注册逻辑；
- `packages/shared/src/types.ts`：首批跨端响应类型；
- `packages/shared/src/format.ts`：金额、百分比、日期和涨跌格式化；
- `frontend-ios/src/`：iPhone 独立导航、页面、组件和 design tokens；
- `frontend/src/`：桌面 UI，保持独立维护。

当前移动端覆盖概览、持仓摘要与仓位详情、流式 AI Chat、全市场/个股新闻与 AI 总结、投资日历、异动报告、移动端估值、Yahoo 三大财务报表、SEC 重大事件/财务/内部人/13F、机会发现及候选详情、自选股只读列表和报告阅读。

底部一级导航固定为概览、持仓、Chat、基本面、更多。动态从概览进入；机会发现从“更多”进入，避免底栏超过五项。复杂技术图表、写入型交易操作、组合模拟优化和管理员设置仍使用桌面端。
