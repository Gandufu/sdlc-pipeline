import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DeviceService } from './DeviceService';
import { HttpClient } from '../device/HttpClient';
import { AuthService } from '../device/AuthService';
import { CapabilityProbe } from '../device/CapabilityProbe';
import { DeviceModel } from '../device/CapabilityMatrix';
import { DeviceAdapter } from '../adapters/DeviceAdapter';
import { ExternalException } from '@heli/shared';
import { ERROR_CODE } from '@heli/shared';

const fakeAdapter = (): DeviceAdapter => ({
  name: 'Fake',
  capabilities: { supportsButton: true } as any,
  getSystemVersion: vi.fn(),
  getSystemStatus: vi.fn(),
  getUptime: vi.fn(),
  getCpuInfo: vi.fn(),
  getMemoryInfo: vi.fn(),
  getCallState: vi.fn(),
  getNetworkInfo: vi.fn(),
  networkDiagnostics: vi.fn(),
});

describe('DeviceService', () => {
  let auth: AuthService;
  let probe: CapabilityProbe;
  let adapter: DeviceAdapter;
  let service: DeviceService;

  beforeEach(async () => {
    const http = {} as HttpClient;
    auth = new AuthService(http, 'http://x');
    probe = {
      probe: vi.fn().mockResolvedValue({
        model: DeviceModel.MEETING_EYE_500,
        raw: {} as any,
        capabilities: { supportsButton: true } as any,
      }),
    } as unknown as CapabilityProbe;
    adapter = fakeAdapter();
    service = new DeviceService({
      http: {} as HttpClient,
      auth,
      probe,
      adapter,
    });

    // 注入已登录状态
    (auth as any).token = 'TEST-TOKEN';
    (auth as any).issuedAt = Date.now();
  });

  it('未登录时调用任意读取方法应抛 AUTHENTICATION_REQUIRED', async () => {
    auth.logout();
    await expect(service.getSystemVersion()).rejects.toThrow(ExternalException);
    await expect(service.getSystemVersion()).rejects.toMatchObject({
      code: ERROR_CODE.AUTHENTICATION_REQUIRED,
    });
  });

  it('getSystemVersion 应注入 token 并返回 raw 数据', async () => {
    (adapter.getSystemVersion as any).mockResolvedValue({ model: 'MeetingEye 500' });

    const v = await service.getSystemVersion();

    expect(v.model).toBe('MeetingEye 500');
    expect(adapter.getSystemVersion).toHaveBeenCalledWith('TEST-TOKEN');
  });

  it('getUptime 分钟数应转换为天/时/分', async () => {
    (adapter.getUptime as any).mockResolvedValue({ value: 1500 }); // 25h

    const r = await service.getUptime();

    expect(r.days).toBe(1);
    expect(r.hours).toBe(1);
    expect(r.minutes).toBe(0);
  });

  it('getCapability 应返回 CapabilityProbe 结果', async () => {
    const caps = await service.getCapability();
    expect(caps.model).toBe(DeviceModel.MEETING_EYE_500);
  });
});
