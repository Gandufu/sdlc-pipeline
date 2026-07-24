# spring-boot-full 脚手架编码约定 (Conventions)

> 本文件由 runner 按受影响 extension point 放入 coder context pack。
> 与 `rules/java.md`、`rules/spring.md` 互补：rules 管通用 Java/Spring，conventions 管本模板。

## 1. 目录约定
```
src/main/java/com/example/<module>/
  api/         # Controller(入参/出参 DTO 在 dto/)
  service/     # Service 接口 + Impl
  repository/  # Spring Data JPA Repository
  domain/      # Entity + 值对象
  config/      # 配置类(Security、Bean 装配)
src/main/resources/
  application.properties
```

## 2. 模块边界
- 一个功能模块(auth、order、user…)独立成包,模块内分层。
- 跨模块只通过 service 接口调用,不直接访问对方 repository。

## 3. 本脚手架的统一返回体
- 所有 Controller 返回 `Result<T>`,定义在 `com.example.common.Result`。
- 扩展错误模型时统一在 `com.example.common` 定义，并由 `@RestControllerAdvice` 转 `Result`。

## 4. 鉴权模块(样例已内置)
- `com.example.auth` 内置可运行的登录端点形状，只作为 extension point 样例。
- 模板不内置真实 JWT、密码持久化或授权；安全需求必须走 standard spec 并显式设计。

## 5. 命名约定补充
- Service 接口:`<Module>Service`;实现:`<Module>ServiceImpl`。
- DTO:入参 `<Action>Request`(如 `LoginRequest`),出参 `<Action>Response`。
- 数据库表/字段:snake_case;Entity 字段驼峰,用 `@Column(name=...)` 映射。
