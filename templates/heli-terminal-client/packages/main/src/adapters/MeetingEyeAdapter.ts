import { HttpClient } from '../device/HttpClient';
import { createSystemApi, SystemApi } from '../device/api/system.api';
import { createNetworkApi, NetworkApi } from '../device/api/network.api';
import { CapabilitySet } from '../device/CapabilityMatrix';
import { DeviceAdapter } from './DeviceAdapter';

/**
 * MeetingEye 500 Adapter。
 *
 * 当前阶段 1 的唯一目标机型。其他机型后续阶段实现各自的 Adapter。
 */
export class MeetingEyeAdapter implements DeviceAdapter {
  readonly name = 'MeetingEye 500';
  readonly capabilities: CapabilitySet;

  private readonly systemApi: SystemApi;
  private readonly networkApi: NetworkApi;

  constructor(http: HttpClient, capabilities: CapabilitySet) {
    this.capabilities = capabilities;
    this.systemApi = createSystemApi(http);
    this.networkApi = createNetworkApi(http);
  }

  // ---- 系统信息（直接转发到 system.api；后续机型可在此覆盖/适配字段） ----
  getSystemVersion(token: string) {
    return this.systemApi.getVersion(token);
  }
  getSystemStatus(token: string) {
    return this.systemApi.getStatus(token);
  }
  getUptime(token: string) {
    return this.systemApi.getUptime(token);
  }
  getCpuInfo(token: string) {
    return this.systemApi.getCpuInfo(token);
  }
  getMemoryInfo(token: string) {
    return this.systemApi.getMemoryInfo(token);
  }
  getCallState(token: string) {
    return this.systemApi.getCallState(token);
  }

  // ---- 网络 ----
  getNetworkInfo(token: string) {
    return this.networkApi.getInfo(token);
  }
  networkDiagnostics(token: string, action: 'ping' | 'traceroute', ip: string, num?: number) {
    return action === 'ping'
      ? this.networkApi.ping(token, ip, num)
      : this.networkApi.traceroute(token, ip, num);
  }
}
