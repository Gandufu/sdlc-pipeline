# 现有框架能力清单 (Existing Framework)

> **此文件会随 /init 拷贝到 工程/docs/existing-framework.md,并被追加 `@docs/existing-framework.md` 到 CLAUDE.md 常驻加载。**
> 全阶段(需求/设计/编码/测试)都要看这份清单,避免重造已有能力(设计文档 §3.2)。

## 已内置模块
- **鉴权模块** (`com.example.auth`)
  - 登录端点 `POST /api/auth/login`,返回 JWT。
  - `BCryptPasswordEncoder` 哈希、`@PreAuthorize` 声明式鉴权。
  - 样例:`AuthController`、`LoginRequest`/`LoginResponse` DTO。
- **统一返回体** `com.example.common.Result<T>`(code/message/data)。
- **异常处理** `@RestControllerAdvice`,业务异常 `BusinessException(ErrCode, msg)`。

## 已具备基础设施
- 分层骨架:api / service / repository / domain / config。
- `application.yml` 多环境配置(dev/prod)。

## 不要重造
- 登录/JWT/密码哈希 → 用 auth 模块。
- 统一响应封装 → 用 `Result<T>`。
- 异常转响应 → 用 `BusinessException` + advice。

## 待补充(开发中按需新增)
- [ ] 权限(RBAC)模型:D2 设计完成后落地。
