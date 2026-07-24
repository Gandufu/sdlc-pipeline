import { CapabilitySet } from '../device/CapabilityMatrix';
import { ProbeResult } from '../device/CapabilityProbe';

/**
 * 设备能力 Adapter 接口。
 *
 * Application 层（DeviceService）只依赖此接口，不直接接触 api/* 与 HttpClient。
 * 不同机型可实现不同 Adapter，按 CapabilityMatrix 选型。
 */
export interface DeviceAdapter {
  /** Adapter 标识（用于日志与诊断） */
  readonly name: string;

  /** 该 Adapter 当前支持的能力子集（来自 CapabilityMatrix） */
  readonly capabilities: CapabilitySet;

  // ---- 系统信息 ----
  getSystemVersion(token: string): Promise<{
    model: string;
    firmware: string;
    hardware: string;
    serialnumber: string;
    macaddress: string;
    'cc-version': string;
  }>;

  getSystemStatus(token: string): Promise<{ status: 'sleeping' | 'wake-up' }>;

  getUptime(token: string): Promise<{ value: number }>;

  getCpuInfo(token: string): Promise<{ 'cpu-usage': number; 'cpu-temp'?: number }>;

  getMemoryInfo(token: string): Promise<{
    usage: number;
    total: number;
    free: number;
    used: number;
  }>;

  getCallState(token: string): Promise<{
    'call-state': 'idle' | 'incoming' | 'incall';
    'call-app'?: string;
  }>;

  // ---- 网络 ----
  getNetworkInfo(token: string): Promise<{
    'network-list': Array<{
      type: 0 | 1;
      'port-type': 0 | 1 | 2 | 3;
      mode: 0 | 1 | 2;
      ip: string;
      mask: string;
      gateway: string;
      'primary-dns': string;
      'second-dns': string;
    }>;
  }>;

  networkDiagnostics(
    token: string,
    action: 'ping' | 'traceroute',
    ip: string,
    num?: number
  ): Promise<{ result: string }>;
}

export type { ProbeResult };
