# Java 栈规约

> 本文件为"怎么写 Java 代码"的栈级规约。由 `/design`、`/code`、`/test` 阶段按 manifest `stacks` 字段**按需 Read**,不常驻上下文。

## 1. 命名
- 类名 `UpperCamelCase`;方法名、变量名 `lowerCamelCase`;常量 `UPPER_SNAKE_CASE`。
- 包名全小写、不含下划线:`com.example.auth`。
- 接口名不加 `I` 前缀;实现类可用 `XxxImpl` 或更语义化的名称。

## 2. 分层
- 严格四层:`api/controller` → `service` → `repository` → `model/entity`。禁止跨层调用(如 controller 直接访问 repository)。
- DTO 与 Entity 分离:Controller 入参/出参用 DTO,Repository 用 Entity。
- 每个 public 方法有清晰的单一职责,业务逻辑收敛在 service 层。

## 3. 异常
- 业务异常用自定义 `BusinessException`,带错误码与消息。
- 不吞异常;`catch` 后必须记录或向上抛出。
- Controller 层统一异常处理(`@RestControllerAdvice`)。

## 4. 依赖与空值
- 公共 API 参数做前置校验(空值、边界)。
- 优先用 `Optional` 表达"可能不存在",不返回裸 `null`。
- 集合返回空集合而非 null。

## 5. 可测性
- 构造器注入,不用字段注入(`@Autowired` on field)。
- 业务逻辑与框架耦合分离,核心逻辑可脱离 Spring 容器单测。
