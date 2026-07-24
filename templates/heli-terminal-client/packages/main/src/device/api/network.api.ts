import { HttpClient } from '../HttpClient';

export interface NetworkInfoItem {
  type: 0 | 1; // 0=DHCP, 1=Static
  'port-type': 0 | 1 | 2 | 3;
  mode: 0 | 1 | 2;
  ip: string;
  mask: string;
  gateway: string;
  'primary-dns': string;
  'second-dns': string;
}

export interface NetworkInfo {
  'network-list': NetworkInfoItem[];
}

export interface DiagnosticsResult {
  result: string;
}

export interface NetworkApi {
  getInfo(token: string): Promise<NetworkInfo>;
  ping(token: string, ip: string, num?: number): Promise<DiagnosticsResult>;
  traceroute(token: string, ip: string, num?: number): Promise<DiagnosticsResult>;
}

export const createNetworkApi = (http: HttpClient): NetworkApi => ({
  async getInfo(token) {
    return http.get<NetworkInfo>('/centralcontrol/network/info', { token });
  },
  async ping(token, ip, num = 4) {
    return http.post<DiagnosticsResult>(
      '/centralcontrol/diagnostics/network',
      { action: 'ping', num, ip },
      { token }
    );
  },
  async traceroute(token, ip, num = 30) {
    return http.post<DiagnosticsResult>(
      '/centralcontrol/diagnostics/network',
      { action: 'traceroute', num, ip },
      { token }
    );
  },
});
