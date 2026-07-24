import { HttpClient } from '../HttpClient';

export interface SystemVersion {
  model: string;
  firmware: string;
  hardware: string;
  serialnumber: string;
  macaddress: string;
  'cc-version': string;
}

export interface SystemStatus {
  status: 'sleeping' | 'wake-up';
}

export interface Uptime {
  value: number; // 分钟
}

export interface CpuInfo {
  'cpu-usage': number; // 百分之一为单位（API 文档）
  'cpu-temp'?: number;
}

export interface MemoryInfo {
  usage: number; // 使用率 0~100
  total: number; // MB
  free: number;
  used: number;
}

export interface CallState {
  'call-state': 'idle' | 'incoming' | 'incall';
  'call-app'?: string;
}

export interface SystemApi {
  getVersion(token: string): Promise<SystemVersion>;
  getStatus(token: string): Promise<SystemStatus>;
  getUptime(token: string): Promise<Uptime>;
  getCpuInfo(token: string): Promise<CpuInfo>;
  getMemoryInfo(token: string): Promise<MemoryInfo>;
  getCallState(token: string): Promise<CallState>;
}

export const createSystemApi = (http: HttpClient): SystemApi => ({
  async getVersion(token) {
    return http.get<SystemVersion>('/centralcontrol/system/version', {
      token,
    });
  },
  async getStatus(token) {
    return http.get<SystemStatus>('/centralcontrol/system/status', {
      token,
    });
  },
  async getUptime(token) {
    return http.get<Uptime>('/centralcontrol/system/uptime', { token });
  },
  async getCpuInfo(token) {
    return http.get<CpuInfo>('/centralcontrol/system/cpu-info', { token });
  },
  async getMemoryInfo(token) {
    return http.get<MemoryInfo>('/centralcontrol/system/memory-info', {
      token,
    });
  },
  async getCallState(token) {
    return http.get<CallState>('/centralcontrol/system/call-state', {
      token,
    });
  },
});
