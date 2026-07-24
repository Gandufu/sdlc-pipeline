import { contextBridge, ipcRenderer } from 'electron';

/**
 * IPC channel 名称（与 @heli/shared 的 IPC 常量保持同步）。
 *
 * 这里刻意内联而不 import '@heli/shared'：preload 在 sandbox:true 下运行，
 * 沙箱预加载进程无法解析 node_modules 里的外部模块。channel 字符串稳定，
 * 在 preload 与 device.handlers 两处各自维护，保持一致即可。
 */
const IPC = {
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

const invoke = <T>(channel: string, ...args: unknown[]): Promise<T> =>
  ipcRenderer.invoke(channel, ...args);

contextBridge.exposeInMainWorld('heli', {
  auth: {
    login: (password: string) => invoke<{ authenticated: boolean }>(IPC.AUTH_LOGIN, password),
    logout: () => invoke<void>(IPC.AUTH_LOGOUT),
    getStatus: () => invoke<{ authenticated: boolean }>(IPC.AUTH_GET_STATUS),
  },
  device: {
    getSystemVersion: () => invoke(IPC.DEVICE_GET_VERSION),
    getSystemStatus: () => invoke(IPC.DEVICE_GET_STATUS),
    getUptime: () => invoke(IPC.DEVICE_GET_UPTIME),
    getCpuInfo: () => invoke(IPC.DEVICE_GET_CPU_INFO),
    getMemoryInfo: () => invoke(IPC.DEVICE_GET_MEMORY_INFO),
    getCallState: () => invoke(IPC.DEVICE_GET_CALL_STATE),
    getCapability: () => invoke(IPC.DEVICE_GET_CAPABILITY),
    getNetworkInfo: () => invoke(IPC.NETWORK_GET_INFO),
    networkDiagnostics: (action: 'ping' | 'traceroute', ip: string, num?: number) =>
      invoke(IPC.NETWORK_DIAGNOSTICS, action, ip, num),
  },
});
