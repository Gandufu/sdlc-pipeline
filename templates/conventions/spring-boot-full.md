# spring-boot-full 脚手架编码约定 (Conventions)

> **不拷进项目**。由 `/code` skill 派单时从 `${CLAUDE_PLUGIN_ROOT}` Read,塞进编码 agent 的 Agent prompt。
> 与 `rules/java.md`、`rules/spring.md`(通用栈规约)互补:rules 管"怎么写 Java/Spring",conventions 管"这个脚手架的本地约定"。

## 1. 目录约定
```
src/main/java/com/example/<module>/
  api/         # Controller(入参/出参 DTO 在 dto/)
  service/     # Service 接口 + Impl
  repository/  # Spring Data JPA Repository
  domain/      # Entity + 值对象
  config/      # 配置类(Security、Bean 装配)
src/main/resources/
  application.yml
```

## 2. 模块边界
- 一个功能模块(auth、order、user…)独立成包,模块内分层。
- 跨模块只通过 service 接口调用,不直接访问对方 repository。

## 3. 本脚手架的统一返回体
- 所有 Controller 返回 `Result<T>`,定义在 `com.example.common.Result`。
- 错误用 `BusinessException(ErrCode, message)`,由 `@RestControllerAdvice` 转 `Result`。

## 4. 鉴权模块(样例已内置)
- `com.example.auth` 模块已内置登录/鉴权样例;新增需要鉴权的接口加 `@PreAuthorize`。
- 密码哈希统一走 `BCryptPasswordEncoder`,不自实现。

## 5. 命名约定补充
- Service 接口:`<Module>Service`;实现:`<Module>ServiceImpl`。
- DTO:入参 `<Action>Request`(如 `LoginRequest`),出参 `<Action>Response`。
- 数据库表/字段:snake_case;Entity 字段驼峰,用 `@Column(name=...)` 映射。
