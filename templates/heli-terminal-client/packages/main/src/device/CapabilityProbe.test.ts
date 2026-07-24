import { describe, it, expect, vi } from 'vitest';
import { CapabilityProbe } from './CapabilityProbe';
import { DeviceModel } from './CapabilityMatrix';

describe('CapabilityProbe', () => {
  it('根据 model 字符串映射到 DeviceModel 枚举', () => {
    const mockGet = vi.fn().mockResolvedValue({
      model: 'MeetingEye 500',
      firmware: '1.0.0',
      hardware: '1.0.0',
      serialnumber: 'SN',
      macaddress: '00:11:22:33:44:55',
      'cc-version': '1.0.0',
    });

    const probe = new CapabilityProbe({ get: mockGet } as any);
    const result = probe.probe();

    return expect(result).resolves.toMatchObject({
      model: DeviceModel.MEETING_EYE_500,
      capabilities: expect.objectContaining({ supportsButton: true }),
    });
  });

  it('未识别 model 时返回 UNKNOWN 与保守能力集', async () => {
    const mockGet = vi.fn().mockResolvedValue({ model: 'HX-9000' });
    const probe = new CapabilityProbe({ get: mockGet } as any);

    const result = await probe.probe();

    expect(result.model).toBe(DeviceModel.UNKNOWN);
    expect(result.capabilities.supportsButton).toBe(false);
  });
});
