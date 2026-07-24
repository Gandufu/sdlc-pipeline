import '@heli/shared';

declare global {
  interface Window {
    heli: {
      auth: {
        login: (password: string) => Promise<{ authenticated: boolean }>;
        logout: () => Promise<void>;
        getStatus: () => Promise<{ authenticated: boolean }>;
      };
      device: {
        getSystemVersion: () => Promise<{
          model: string;
          firmware: string;
          hardware: string;
          serialnumber: string;
          macaddress: string;
          'cc-version': string;
        }>;
        getSystemStatus: () => Promise<{ status: 'sleeping' | 'wake-up' }>;
        getUptime: () => Promise<{ days: number; hours: number; minutes: number; totalMinutes: number }>;
        getCpuInfo: () => Promise<{ 'cpu-usage': number; 'cpu-temp'?: number }>;
        getMemoryInfo: () => Promise<{ usage: number; total: number; free: number; used: number }>;
        getCallState: () => Promise<{ 'call-state': 'idle' | 'incoming' | 'incall'; 'call-app'?: string }>;
        getCapability: () => Promise<{ model: string; capabilities: { supportsButton: boolean; supportsCameraActive: boolean; supportsCameraLayout: boolean; supportsScreenBrightness: boolean; supportsInputSource: boolean } }>;
        getNetworkInfo: () => Promise<{ 'network-list': Array<{ type: number; 'port-type': number; mode: number; ip: string; mask: string; gateway: string; 'primary-dns': string; 'second-dns': string }> }>;
        networkDiagnostics: (
          action: 'ping' | 'traceroute',
          ip: string,
          num?: number
        ) => Promise<{ result: string }>;
      };
    };
  }
}

export {};