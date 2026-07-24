# 直升机会议终端控制客户端 (Heli Conference Terminal)

基于 Electron + React + TypeScript 的 Windows 10 桌面控制客户端，通过亿联中控 HttpApi 控制会议终端设备（系统信息、网络诊断、音视频、会议平台切换等）。

> 阶段 1（基础控制）版本。会议控制、网络写入、时间/分辨率等 API 不支持项已降级或标注。

---

## 一、环境要求

| 项 | 版本 / 要求 |
|---|---|
| 操作系统 | Windows 10 64-bit（目标机器） |
| Node.js | **20.11+** |
| 包管理器 | **pnpm 9+**（`npm i -g pnpm`） |
| Git | 任意 |
| **Windows 开发者模式** | **打包前必须开启**（见第三节「为什么需要」） |

---

## 二、安装依赖

```bash
cd heli-terminal-client
pnpm install
```

---

## 三、打包（生成 NSIS 安装包）

### 3.1 前置：开启 Windows 开发者模式（**仅打包需要，且每台打包机做一次**）

electron-builder 打 NSIS 包时会下载 `winCodeSign` 工具链，其归档里的两个 macOS 符号链接在 Windows 上还原需要 `SeCreateSymbolicLinkPrivilege` 权限。普通账户开启开发者模式即可获得该权限，否则报错：

```
ERROR: Cannot create symbolic link : 客户端没有所需的特权
```

开启方式（任选其一）：

- **GUI**：设置 → 更新和安全 → 开发者选项 → 打开「开发者模式」
- **管理员 PowerShell**：
  ```powershell
  reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowDevelopmentWithoutDevLicense /t REG_DWORD /d 1 /f
  ```

> 已预置 `scripts/prepackage-wincode-sign.cjs`，会在每次打包前尝试用 `-snl` 预解压已缓存的 winCodeSign 归档，进一步降低命中概率。

### 3.2 执行打包

```bash
cd heli-terminal-client
pnpm --filter @heli/main package
```

该命令依次执行：
1. `tsc` 编译主进程到 `packages/main/dist/`
2. `vite build` 构建渲染进程到 `packages/renderer/dist/`
3. `electron-builder` 打包

产物位置（见 `packages/main/package.json` 的 `build.directories.output`）：

```
heli-terminal-client/out/
├─ Heli Conference Terminal Setup 0.1.0.exe   ← NSIS 安装包（交付给运维/客户）
└─ win-unpacked/                                ← 解包目录（开发调试用）
```

> 修改版本号：编辑 `packages/main/package.json` 的 `version` 字段。

### 3.3 配置默认设备地址（可选）

主进程通过环境变量 `DEVICE_BASE_URL` 读取设备地址，默认 `https://192.168.1.100`。

- **打包进安装包的默认值**：修改 `packages/main/src/index.ts` 里的 fallback，或运行 `package` 前导出环境变量。
- **运行时覆盖**：见第五节。

> 自签名证书：若设备 HTTPS 证书不被信任，需在 `HttpClient.ts` 配 `rejectUnauthorized: false`（生产前请评估安全影响）。

---

## 四、开发模式

热重载启动 Vite Dev Server + Electron：

```bash
cd heli-terminal-client
pnpm --filter @heli/main dev
```

指定设备地址：

```bash
# PowerShell
$env:DEVICE_BASE_URL="https://10.50.149.143"; pnpm --filter @heli/main dev

# Git Bash
DEVICE_BASE_URL=https://10.50.149.143 pnpm --filter @heli/main dev
```

开发者工具：Electron 窗口内 `Ctrl+Shift+I`。

---

## 五、安装与使用

### 5.1 安装

1. 把 `Heli Conference Terminal Setup 0.1.0.exe` 拷到目标 Windows 10 机器。
2. 双击运行，选择安装目录（默认 `C:\Program Files\Heli Conference Terminal\`）。
3. 安装完成会在桌面与开始菜单生成快捷方式。

### 5.2 首次使用

1. 确保目标机器与会议终端（MeetingEye 500）在同一网段。
2. 启动应用 → 弹出「设备登录」对话框。
3. 输入设备 admin 密码（**默认 `0000`**）→ 点击登录。
4. 登录成功后进入「设备总览」Dashboard。

> **零持久化**：应用关闭即清空所有登录态与运行时状态，下次启动需重新输入密码。

### 5.3 主要功能（阶段 1）

| 模块 | 能力 |
|---|---|
| 设备总览 | 型号 / 固件 / MAC / SN / 运行时间，实时刷新 CPU / 内存 / 通话状态（5 秒轮询） |
| 设备管理 → 网络 | 读取网络信息（DHCP/Static、IP、掩码、网关、DNS）+ Ping / Traceroute 诊断 |
| 会议 | 占位（阶段 2 实现：会议平台切换 + 通话状态 + 遥控器按键） |
| 日志 | 占位（阶段 3 实现：设备日志下载 + Syslog + 告警） |

### 5.4 运行时改设备地址

当前版本设备地址在打包时固定。如需不改代码切换设备，可通过快捷方式追加环境变量，或在阶段 2 引入的「设置页」中配置（待实现）。

---

## 六、工程结构

```
heli-terminal-client/
├─ packages/
│  ├─ shared/        # 类型 / IPC 契约 / 错误码 / 异常类（零依赖）
│  ├─ main/          # Electron 主进程（Node.js 服务层）
│  │  └─ src/
│  │     ├─ device/       # Infrastructure: HttpClient / AuthService / Capability*
│  │     ├─ device/api/   # system.api / network.api（与 HTTPS_API.md 一一对应）
│  │     ├─ adapters/     # DeviceAdapter 接口 + MeetingEyeAdapter（分层隔离）
│  │     ├─ services/     # Application: DeviceService（渲染进程唯一入口）
│  │     ├─ ipc/          # IPC handler + safeHandle 错误码透传
│  │     ├─ window.ts     # BrowserWindow（contextIsolation=true 等）
│  │     ├─ preload.ts    # contextBridge 暴露 window.heli.*
│  │     └─ index.ts      # 主进程入口 / bootstrap
│  └─ renderer/      # React + Ant Design 渲染进程
│     └─ src/
│        ├─ pages/        # Dashboard / Network / Login / 占位页
│        ├─ hooks/        # useDeviceQuery（轮询，fetcher 引用稳定）
│        ├─ store/        # 运行时 store（无持久化）
│        └─ layout/       # AppLayout + LoginDialog
├─ scripts/          # 打包辅助脚本
├─ docs/             # RUNBOOK.md
└─ tsconfig.base.json
```

分层（遵循 `ARCHITECTURE.md` / `AGENTS.md`）：

```
Renderer ──IPC/contextBridge──▶ DeviceService (Application)
                                  │
                                  ▼
                              DeviceAdapter (Interface)
                                  │
                                  ▼
                          api/* (Infrastructure)
                                  │
                                  ▼
                              HttpClient ──HTTPS──▶ 设备 HttpApi
```

---

## 七、常用命令速查

| 命令 | 作用 |
|---|---|
| `pnpm install` | 安装全部依赖 |
| `pnpm --filter @heli/main dev` | 开发模式（热重载） |
| `pnpm --filter @heli/main package` | 打 NSIS 安装包 |
| `pnpm -r run typecheck` | 全包 TypeScript 类型检查 |
| `pnpm test` | 先构建 shared 包，再运行全包单元测试 |
| `pnpm -r run build` | 全包编译（不含 electron-builder） |

---

## 八、常见问题排查

### Q1 打包报 `Cannot create symbolic link : 客户端没有所需的特权`

→ 没开 Windows 开发者模式。见 **3.1**。

### Q2 打包报 `remove .../app.asar: 正由另一进程使用`

→ 有残留进程或杀软在扫描。先任务管理器结束 `Heli Conference Terminal.exe` 与 `electron.exe`（残留实例会锁住 `out/win-unpacked/resources/app.asar`），再删除 `out/`。若删除仍报「正由另一进程使用」，是系统级句柄（Defender/索引器或已杀进程泄漏），需**重启机器**后重试。

### Q3 启动后窗口空白 / 找不到 index.html

→ 主进程找不到 renderer 产物。确认 `pnpm --filter @heli/renderer build` 已执行且 `packages/renderer/dist/index.html` 存在。

### Q4 登录提示「密码错误 (10007)」

→ 输入的 admin 密码与设备不一致。设备默认 `0000`，可在设备本地 UI 修改。

### Q5 操作提示「设备离线」

→ 设备 IP 不可达或 HTTPS 端口不通。在 cmd 执行 `ping <设备IP>` 与 `curl -k https://<设备IP>/centralcontrol/system/version` 排查。

### Q6 设备证书自签导致连接失败

→ `HttpClient.ts` 临时配 `rejectUnauthorized: false`（仅内网可信环境）。

---

## 九、更多文档

- 运行手册与真机验收清单：[`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- 设计规范与 API 覆盖矩阵：仓库根 `HTTPS_API.md`、`直升机会议终端控制客户端.MD`

---

## 十、阶段 1 已知限制

- **会议模块**：仅占位。阶段 2 实现「会议平台切换 + 通话状态 + 遥控器按键（仅 ME500）」。不支持目标地址拨号 / 会议 ID 加入 / 预约会议 / 历史列表（API 不支持）。
- **网络写入**：UI 禁用（API 无写入接口）。改 IP/网关/DNS 请到设备本地 UI。
- **时间设置 / 分辨率 / 帧率 / 白平衡 / 自动曝光**：设备 API 不支持，UI 已标注。
- **最大音量限制**：前端软限制，不下发设备。
- **设备地址**：打包期固定，运行时切换待阶段 2 设置页实现。
