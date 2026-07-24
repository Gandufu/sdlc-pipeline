import { ipcMain } from 'electron';
import { DeviceService } from '../services/DeviceService';
import { ExternalException, IPC } from '@heli/shared';

export interface IpcError {
  code: string; // ExternalException.code (numeric as string) | 'UNKNOWN' | 'IPC_ERROR'
  message: string;
}

const safeHandle = <TArgs extends unknown[], TResult>(
  channel: string,
  fn: (...args: TArgs) => Promise<TResult>
): void => {
  ipcMain.handle(channel, async (_e, ...args: TArgs): Promise<TResult | IpcError> => {
    try {
      return await fn(...args);
    } catch (err) {
      if (err instanceof ExternalException) {
        const payload: IpcError = { code: String(err.code), message: err.message };
        return payload as unknown as TResult;
      }
      const msg = err instanceof Error ? err.message : String(err);
      const payload: IpcError = { code: 'IPC_ERROR', message: msg };
      return payload as unknown as TResult;
    }
  });
};

export const registerDeviceHandlers = (service: DeviceService) => {
  safeHandle(IPC.AUTH_LOGIN, async (password: string) => {
    await service.login(password);
    return { authenticated: true };
  });

  safeHandle(IPC.AUTH_LOGOUT, async () => {
    service.logout();
  });

  ipcMain.handle(IPC.AUTH_GET_STATUS, () => {
    return { authenticated: service.isAuthenticated() };
  });

  safeHandle(IPC.DEVICE_GET_VERSION, () => service.getSystemVersion());
  safeHandle(IPC.DEVICE_GET_STATUS, () => service.getSystemStatus());
  safeHandle(IPC.DEVICE_GET_UPTIME, () => service.getUptime());
  safeHandle(IPC.DEVICE_GET_CPU_INFO, () => service.getCpuInfo());
  safeHandle(IPC.DEVICE_GET_MEMORY_INFO, () => service.getMemoryInfo());
  safeHandle(IPC.DEVICE_GET_CALL_STATE, () => service.getCallState());
  safeHandle(IPC.DEVICE_GET_CAPABILITY, () => service.getCapability());

  safeHandle(IPC.NETWORK_GET_INFO, () => service.getNetworkInfo());
  safeHandle(IPC.NETWORK_DIAGNOSTICS, (action: 'ping' | 'traceroute', ip: string, num?: number) =>
    action === 'ping' ? service.ping(ip, num) : service.traceroute(ip, num)
  );
};
