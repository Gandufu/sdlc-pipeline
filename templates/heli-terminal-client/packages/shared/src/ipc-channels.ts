/**
 * IPC channel 命名规范：`domain:resource:action`
 * 渲染进程通过 contextBridge 调用同名方法
 */
export const IPC = {
  AUTH_LOGIN: 'auth:login',
  AUTH_LOGOUT: 'auth:logout',
  AUTH_GET_STATUS: 'auth:getStatus',

  DEVICE_GET_VERSION: 'device:system:getVersion',
  DEVICE_GET_STATUS: 'device:system:getStatus',
  DEVICE_GET_UPTIME: 'device:system:getUptime',
  DEVICE_GET_CPU_INFO: 'device:system:getCpuInfo',
  DEVICE_GET_MEMORY_INFO: 'device:system:getMemoryInfo',
  DEVICE_GET_CALL_STATE: 'device:system:getCallState',
  DEVICE_GET_CAPABILITY: 'device:system:getCapability',

  NETWORK_GET_INFO: 'device:network:getInfo',
  NETWORK_DIAGNOSTICS: 'device:network:diagnostics',
} as const;

export type IpcChannel = (typeof IPC)[keyof typeof IPC];
