# Heli Conference Terminal — 运行手册

## 一、构建产物（目标 Windows 10 机器）

### 先决条件

- Node.js 20.11+ 与 pnpm 9+
- Git
- Windows 10 64-bit
- 目标设备 MeetingEye 500 在同一网段（已知 IP 与 admin 密码）

### 构建步骤

```bash
git clone <repo-url>
cd integrated-helicopter
git checkout main
cd heli-terminal-client
pnpm install
pnpm --filter @heli/renderer build
pnpm --filter @heli/main build
pnpm --filter @heli/main package
```

构建产物：`out/Heli Conference Terminal Setup 0.1.0.exe`

### 配置设备地址

主进程通过环境变量 `DEVICE_BASE_URL` 读取设备地址。开发模式下已在 main 的 `dev` 脚本中写死 `http://192.168.1.100`，生产模式需要在打包前修改 `packages/main/src/index.ts` 中的 fallback 或通过 NSIS 安装后修改 `package.json` 中的 build 配置。

> 后续工作（阶段 1 之后）：增加设置页让用户在 UI 内配置设备 IP，无需重新打包。

## 二、安装

1. 双击 `Heli Conference Terminal Setup 0.1.0.exe`
2. 选择安装目录（默认 `C:\Program Files\Heli Conference Terminal\`）
3. 完成安装，桌面与开始菜单会出现快捷方式

## 三、首次启动

1. 启动应用，弹出设备登录框
2. 输入设备 admin 密码（默认 `0000`），点击登录
3. 登录成功后进入 Dashboard

## 四、联调验收清单（请在真机上逐项打勾）

- [ ] 应用启动，弹出登录框
- [ ] 输入正确密码 → Dashboard 显示设备型号、固件、MAC、序列号
- [ ] Dashboard 实时刷新（5 秒轮询）：运行时间、CPU 使用率、内存使用、通话状态
- [ ] 进入设备 → 网络页：
  - [ ] 网络信息列表正确显示（含 DHCP/Static、IP、掩码、网关、DNS）
  - [ ] Ping `8.8.8.8` 返回结果文本
  - [ ] Traceroute 正常返回
- [ ] 关闭应用 → 重新打开 → 重新要求输入密码（验证 C1 零持久化）
- [ ] 输入错误密码 → Toast 提示「设备 admin 密码错误」（错误码 10007）
- [ ] 设备断网后操作 → Toast 提示「设备离线」

## 五、设备离线排查

1. 确认设备 IP 可达：在 cmd 执行 `ping <设备 IP>`
2. 确认 HTTPS 端口开放：`curl -k https://<设备 IP>/centralcontrol/system/version`
3. 检查客户端日志：`%PROGRAMDATA%\HeliConference\logs\app.log`（如果日志模块已实现）

> 当前阶段 1 未实现日志文件输出，仅控制台日志（开发模式 dev tools 可见）。生产模式日志输出是后续工作。

## 六、已知限制（阶段 1）

- **会议模块**降级：仅支持会议平台切换 + 通话状态查询 + `app/start` +（仅 ME500）遥控器按键模拟。不支持目标地址拨号、会议 ID 加入、预约会议、历史会议列表（API 不支持）。
- **网络写入**：UI 禁用。需修改 IP/网关/DNS 请到设备本地 UI。
- **时间设置 / 分辨率 / 帧率 / 白平衡 / 自动曝光**：UI 标注「设备 API 不支持」。
- **最大音量限制**：前端滑块软限制为 100，不下发设备。
- **零持久化**：关闭应用即清空所有登录态与运行时数据。下次启动需重新输入 admin 密码。

## 七、升级（未来）

当前未集成 electron-updater。后续阶段会接入 GitHub Releases 或内网 HTTP 分发。