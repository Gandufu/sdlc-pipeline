# 独立模板与插件数据源合约

## 所有权

- 模板仓库拥有项目资产：源码、依赖锁、构建配置、测试、项目约定和 SDLC 合约。
- 插件仓库只拥有通用 runner、schema、规则与 `templates/manifest.json` 数据源注册表。
- 插件发布包不得内嵌模板源码、锁文件、wrapper、图片或模板专属 conventions。

## 模板仓库

根目录必须是可独立 clone、安装、运行和测试的 Git 仓库，并包含：

```text
.sdlc-pipeline/
  lifecycle.json
  scaffold.json
docs/existing-framework.md
```

`.sdlc-pipeline` 在模板仓库中只能包含上述两个合约；runner、安装现场和运行日志由插件写入。

## 数据源注册表

每条元数据至少包含：

```json
{
  "id": "sdlc-electron-scaffold",
  "name": "SDLC Electron 脚手架",
  "description": "可用于需求匹配的说明",
  "stacks": ["typescript", "electron", "react"],
  "capabilities": ["desktop", "typed-ipc"],
  "source": {
    "kind": "git",
    "repository": "https://github.com/example/sdlc-electron-scaffold.git",
    "ref": "main"
  }
}
```

init 根据用户需求选择 `id`，再解析 `repository/ref`，clone 后记录实际 commit SHA。发布稳定模板时优先把 `ref` 固定到 release tag 或 commit；开发期可使用 `main`。

## 验收

- 数据源 ID 可解析，未知 ID 返回可用列表。
- 注册模板与显式 `--github` 使用相同远程导入实现。
- 导入保留模板 Git 历史和 remote provenance。
- 初始化失败后，仅在 scaffold 无漂移且 Git 历史完整时允许续跑。
- 安装插件后只能发现注册表元数据，不能发现任何内嵌模板源码。
