# Stock Monitor Qt Desktop — Phase 2.5 Liquid Glass Specification

日期：2026-08-18  
范围：仅 `desktop/` 的视觉基础、mock showcase 与实验性 window chrome；不接入业务 API，不进入 Phase 3。

## 1. Current Phase 2 visual problems

- **Structure**：固定实色 sidebar 与独立 content pane 并排，内容没有延伸到 functional layer 下方。
- **Materials**：`surface/elevated/chrome` 只是三种不透明色；没有 content、functional glass、transient 三层语义。
- **Hierarchy**：Playground 由同样的有边框 Card 纵向堆叠，组件而非金融内容成为视觉主角。
- **Typography**：只有 display/title/body/caption/numeric 五档；主资产数字、表格数字和说明文字缺少独立层级。
- **Geometry**：small/medium/large/pill 与容器嵌套关系无关，无法形成同心曲率。
- **Controls**：Button、输入、Card、Menu、Sheet 默认都有 1px border；选中、hover、focus 主要靠换背景色。
- **Motion**：以定时 fade/scale 为主；sidebar indicator、search expansion 与 inspector 缺少对象连续性。
- **Window chrome**：稳定 native decoration 与应用 header 视觉上割裂；尚无可选 CSD 原型。
- **Density**：控件和 row 只有单一尺寸，不能同时覆盖专业 compact 与 comfortable 工作流。

## 2. Adopted design principles

1. **Content first**：图表、数字、表格使用 clean canvas 和低装饰分组；Card 不默认 glass。
2. **One functional glass layer**：sidebar、toolbar、search 和关键 segmented control 浮在内容上方。
3. **Transient glass is heavier**：menu、popover、inspector 使用更强 separation；modal 才使用 scrim。
4. **Regular before clear**：大量文字的 sidebar/popover 用 regular；clear 只用于图表上的少量紧凑控制。
5. **Concentric geometry**：window/panel/control/compact/capsule 是语义曲率；内层半径由外层减 inset。
6. **Borders are exceptional**：先用 spacing、surface、type、separator；focus/high contrast 才使用明确边框。
7. **Typography carries hierarchy**：display/large title/title/headline/body/callout/caption/micro 与 numeric display/body/data 分开。
8. **Continuity over decoration**：selection indicator 移动、search 从 icon 连续扩成输入、popover 从 trigger origin 出现。
9. **Desktop remains desktop**：保留 hover、keyboard focus、dense tables、multi-pane 与 compact density。
10. **Accessibility is a material mode**：reduced transparency 使用高质量 opaque surface；high contrast 加强 separation；reduced motion 保留即时状态反馈。

## 3. Material system

| Layer | Material | Use | Fallback |
|---|---|---|---|
| Content | canvas / content surface | 数据、图表、表格、正文 | 原样 |
| Functional | glass regular | sidebar、toolbar、search | opaque chrome |
| Functional accent | glass clear | 富背景上的紧凑 segmented/icon control | regular/opaque |
| Transient | glass elevated | popover、menu、inspector、sheet | opaque elevated |

Qt Quick 原型允许使用小范围 `ShaderEffectSource + MultiEffect` 采样已知 backdrop。它不是 Apple renderer：不宣称具备真实 lensing/refraction。blur 仅在明确 backdrop、小面积、非 reduced-transparency 时启用；其余靠半透明基底、环境 tint、柔和 edge highlight 和分级 shadow 形成感知层级。

## 4. Motion rules

- 输入立即反馈，不添加 artificial delay；动画期间仍接受输入。
- selection indicator 与 search width 从当前 presentation value 重定向。
- transient surface 从 trigger 一侧 materialize，退出沿相同路径。
- hover 只改变亮度或 1px elevation；不做 card-wide 1.05 scale。
- reduced motion 将 spatial motion 降为短 opacity/state change。

## 5. Window chrome decision

默认继续使用 native decoration。`--custom-chrome` 只启用实验性 frameless prototype，通过 Qt 6.8+ `Window.startSystemMove()` 请求 compositor 移动，并保留 native fallback。进入默认路径前必须在 GNOME Wayland 完成 move、edge resize、maximize/restore、snap、fullscreen、多屏与 HiDPI 人工验收；任何失败都维持 native decoration。

## 6. Acceptance

- Full Dashboard Showcase 与 Component Playground 同时存在。
- Dark、Light、Compact、Comfortable、Reduced Transparency 与 High Contrast 可确定性截图。
- 截图覆盖 1920×1080 和 2560×1440 等效 HiDPI。
- `ctest` 全通过；Wayland frame benchmark 不比 Phase 2 基线明显退步。
- 不修改 backend/frontend，不部署生产，不打包，不使用 Apple 私有字体或资产。

## 7. Primary references

- Apple HIG — [Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- Apple HIG — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- WWDC25 — [Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/)
- WWDC25 — [Get to know the new design system](https://developer.apple.com/videos/play/wwdc2025/356/)
- Qt 6.8 — [Window QML Type](https://doc.qt.io/qt-6.8/qml-qtquick-window.html)
