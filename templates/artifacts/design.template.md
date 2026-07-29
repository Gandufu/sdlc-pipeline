---
schema_version: "3.0"
template_version: "1.0"
type: "design"
id: "D-0001"
requirement_ids: ["R-0001"]
decision_ids: ["Q-0001"]
---
# D-0001 设计标题

## 模块

### module-name

#### 职责

描述模块拥有的职责。

#### Seam

填写模块边界。

## 接口

### interface-name

#### 输入

描述输入。

#### 输出

描述输出。

#### 错误

- 描述一种错误语义

## 数据契约

### ContractName

#### fieldName

- 类型：string
- 必填：true
- 来源：SRC-XXXXXXXXXXXX#text:1

## 扩展点

- scaffold-extension-point-id

## 设计决策

- 描述技术决策；阻塞决策通过 frontmatter 的 decision_ids 引用
