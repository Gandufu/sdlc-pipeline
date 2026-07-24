/** 设备能力不支持（API 未实现或机型不支持） */
export class CapabilityUnsupportedException extends Error {
  public readonly capability: string;

  constructor(capability: string, message?: string) {
    super(message ?? `设备 API 不支持：${capability}`);
    this.name = 'CapabilityUnsupportedException';
    this.capability = capability;
  }
}
