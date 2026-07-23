# Vue 栈规约

> 占位栈规约。manifest 当前注册的脚手架为 spring-boot-full,未启用 vue 栈;此文件演示"新增栈"扩展路径(见设计文档 §6)。

## 1. 命名
- 组件 `PascalCase`;props/events `camelCase`;CSS 类 `kebab-case`。

## 2. 组件
- 单文件组件(SFC),`<script setup>` 组合式 API。
- props 用 `defineProps` + 类型;events 用 `defineEmits`。

## 3. 状态与副作用
- 跨组件状态用 Pinia;组件内状态用 `ref`/`reactive`。
- 副作用集中在 `onMounted`/`onUnmounted` 或 `watch`,清理副作用。

> 当 manifest 引入 Vue 脚手架时,本文件内容由相应脚手架补充完整。
