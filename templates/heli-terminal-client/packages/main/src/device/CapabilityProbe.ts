import { CapabilityMatrix, CapabilitySet, DeviceModel } from './CapabilityMatrix';
import { HttpClient } from './HttpClient';

export interface SystemVersionResponse {
  model: string;
  firmware: string;
  hardware: string;
  serialnumber: string;
  macaddress: string;
  'cc-version': string;
}

export interface ProbeResult {
  model: DeviceModel;
  raw: SystemVersionResponse;
  capabilities: CapabilitySet;
}

export class CapabilityProbe {
  constructor(private readonly http: HttpClient) {}

  async probe(token?: string): Promise<ProbeResult> {
    // token 可选：未登录时（如 LoginDialog 还没成功）也能 probe，
    // 部分机型允许匿名访问 /system/version；若设备要求鉴权则会抛 ExternalException(10009)
    const raw = await this.http.get<SystemVersionResponse>(
      '/centralcontrol/system/version',
      token ? { token } : {}
    );
    const known = (Object.values(DeviceModel) as string[]).includes(raw.model);
    const model = known ? (raw.model as DeviceModel) : DeviceModel.UNKNOWN;
    return {
      model,
      raw,
      capabilities: CapabilityMatrix.for(raw.model),
    };
  }
}
