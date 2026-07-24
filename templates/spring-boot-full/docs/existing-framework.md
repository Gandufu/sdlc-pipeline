# 现有框架能力清单 (Existing Framework)

> 此文件随模板进入工程，由 runner 在相关 context pack 中按需提供，不做 SessionStart 常驻注入。

## 已内置模块
- **鉴权模块** (`com.example.auth`)
  - 登录端点 `POST /api/auth/login`，返回演示 token；不是生产 JWT 实现。
  - 样例:`AuthController`、`LoginRequest`/`LoginResponse` DTO。
- **统一返回体** `com.example.common.Result<T>`（success/data）。
- **健康检查** Spring Boot Actuator `/actuator/health`。

## 已具备基础设施
- 分层骨架:api / service / repository / domain / config。
- `application.properties` 基础配置。

## 不要重造
- 统一响应封装 → 用 `Result<T>`。
- 健康检查 → 使用 Actuator，不重复实现。

## 待补充(开发中按需新增)
- [ ] 生产鉴权/JWT/密码哈希必须通过新的 R/D/T 设计后落地。
