import { HttpClient } from '../device/HttpClient';
import { AuthService } from '../device/AuthService';
import { CapabilityProbe, ProbeResult } from '../device/CapabilityProbe';
import { DeviceAdapter } from '../adapters/DeviceAdapter';
import { createAdapterFor } from '../adapters';
import { CapabilitySet, DeviceModel } from '../device/CapabilityMatrix';

export interface DeviceServiceDeps {
  http: HttpClient;
  auth: AuthService;
  probe: CapabilityProbe;
  /** 阶段 1 默认 Adapter；可注入 mock 用于测试 */
  adapter: DeviceAdapter;
}

export interface UptimeFormatted {
  days: number;
  hours: number;
  minutes: number;
  totalMinutes: number;
}

export class DeviceService {
  constructor(private readonly deps: DeviceServiceDeps) {}

  private async authedToken(): Promise<string> {
    return this.deps.auth.getToken();
  }

  async getSystemVersion() {
    const token = await this.authedToken();
    return this.deps.adapter.getSystemVersion(token);
  }

  async getSystemStatus() {
    const token = await this.authedToken();
    return this.deps.adapter.getSystemStatus(token);
  }

  async getUptime(): Promise<UptimeFormatted> {
    const token = await this.authedToken();
    const { value } = await this.deps.adapter.getUptime(token);
    const days = Math.floor(value / (24 * 60));
    const hours = Math.floor((value % (24 * 60)) / 60);
    const minutes = value % 60;
    return { days, hours, minutes, totalMinutes: value };
  }

  async getCpuInfo() {
    const token = await this.authedToken();
    return this.deps.adapter.getCpuInfo(token);
  }

  async getMemoryInfo() {
    const token = await this.authedToken();
    return this.deps.adapter.getMemoryInfo(token);
  }

  async getCallState() {
    const token = await this.authedToken();
    return this.deps.adapter.getCallState(token);
  }

  async getCapability(): Promise<ProbeResult> {
    return this.deps.probe.probe();
  }

  async getNetworkInfo() {
    const token = await this.authedToken();
    return this.deps.adapter.getNetworkInfo(token);
  }

  async ping(ip: string, num?: number) {
    const token = await this.authedToken();
    return this.deps.adapter.networkDiagnostics(token, 'ping', ip, num);
  }

  async traceroute(ip: string, num?: number) {
    const token = await this.authedToken();
    return this.deps.adapter.networkDiagnostics(token, 'traceroute', ip, num);
  }

  async login(password: string): Promise<void> {
    const token = await this.deps.auth.login(password);
    // 登录后立即触发一次 probe 缓存能力（必须带 token，否则设备返回 10009）
    await this.deps.probe.probe(token);
  }

  logout(): void {
    this.deps.auth.logout();
  }

  isAuthenticated(): boolean {
    return this.deps.auth.isAuthenticated();
  }

  /** Adapter 暴露给 IPC 层（用于按能力启用 UI） */
  getCapabilities(): CapabilitySet {
    return this.deps.adapter.capabilities;
  }

  getModel(): DeviceModel {
    // 当前实现：从 probe 缓存中取；阶段 1 简化：未缓存时返回 UNKNOWN
    // 后续 stage 改为在 service 内部缓存 ProbeResult
    return DeviceModel.UNKNOWN;
  }
}

/** 工厂：组装默认 DeviceService（main 入口使用） */
export const createDeviceService = (opts: {
  http: HttpClient;
  auth: AuthService;
  probe: CapabilityProbe;
}): DeviceService => {
  const model = DeviceModel.UNKNOWN; // 首次构造时未 probe；后续 login 会刷新
  const adapter = createAdapterFor(model, opts.http);
  return new DeviceService({ ...opts, adapter });
};
