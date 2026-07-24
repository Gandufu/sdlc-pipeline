# Spring 栈规约

> runner 在 code/test context pack 中按 manifest `stacks` 按需提供。与 `java.md` 配合使用（Java 管语言，Spring 管框架）。

## 1. 分层与注解
- Controller:`@RestController` + `@RequestMapping("/api/<resource>")`,方法用 `@GetMapping`/`@PostMapping` 等。
- Service:接口 + 实现;实现类标 `@Service`;事务边界标在 service 层(`@Transactional`)。
- Repository:继承 `JpaRepository` 或等价物;复杂查询用 `@Query` 或 Specification,不拼字符串 SQL。

## 2. REST 约定
- 资源路径用复数名词:`/api/users`、`/api/orders`。
- HTTP 动词语义化:GET 查、POST 增、PUT/PATCH 改、DELETE 删。
- 统一响应体封装(如 `Result<T>`),含 code/message/data。
- 校验用 `@Valid` + Bean Validation 注解(`@NotBlank`、`@Size` 等)。

## 3. 安全(鉴权/鉴权相关)
- 认证走 Spring Security;密码用 `BCryptPasswordEncoder`,不自实现哈希。
- 权限用 `@PreAuthorize` 声明式控制,不在业务代码里硬编码角色判断。
- 敏感配置(密钥、token)走外部化配置,不硬编码。

## 4. 配置
- `application.yml` 分环境(`application-dev.yml`、`application-prod.yml`)。
- 数据库连接、外部服务地址等走 `@ConfigurationProperties`,不散落 `@Value`。

## 5. 测试(Spring 侧,本版 defer)
- 集成测试用 `@SpringBootTest`;切片测试用 `@WebMvcTest`、`@DataJpaTest`。
- 本版(MVP)不跑测试执行,以上为后续接口测试落地时的约定。
