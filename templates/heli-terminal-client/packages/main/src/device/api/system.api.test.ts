import { describe, it, expect, vi } from 'vitest';
import { createSystemApi } from './system.api';

describe('system.api', () => {
  it('getVersion 调用 GET /system/version', async () => {
    const http = { get: vi.fn().mockResolvedValue({ model: 'M' }) };
    const api = createSystemApi(http as any);

    await api.getVersion('TOK');

    expect(http.get).toHaveBeenCalledWith('/centralcontrol/system/version', {
      token: 'TOK',
    });
  });

  it('getStatus 调用 GET /system/status', async () => {
    const http = { get: vi.fn().mockResolvedValue({ status: 'wake-up' }) };
    const api = createSystemApi(http as any);

    const r = await api.getStatus('TOK');

    expect(r.status).toBe('wake-up');
  });

  it('getUptime 调用 GET /system/uptime 返回 value 字段', async () => {
    const http = { get: vi.fn().mockResolvedValue({ value: 1234 }) };
    const api = createSystemApi(http as any);

    const r = await api.getUptime('TOK');

    expect(r.value).toBe(1234);
  });

  it('getCpuInfo 调用 GET /system/cpu-info', async () => {
    const http = { get: vi.fn().mockResolvedValue({ 'cpu-usage': 42 }) };
    const api = createSystemApi(http as any);

    const r = await api.getCpuInfo('TOK');

    expect(r['cpu-usage']).toBe(42);
  });

  it('getMemoryInfo 调用 GET /system/memory-info', async () => {
    const http = {
      get: vi.fn().mockResolvedValue({
        usage: 50,
        total: 4096,
        free: 2048,
        used: 2048,
      }),
    };
    const api = createSystemApi(http as any);

    const r = await api.getMemoryInfo('TOK');

    expect(r.total).toBe(4096);
  });

  it('getCallState 调用 GET /system/call-state', async () => {
    const http = { get: vi.fn().mockResolvedValue({ 'call-state': 'idle' }) };
    const api = createSystemApi(http as any);

    const r = await api.getCallState('TOK');

    expect(r['call-state']).toBe('idle');
  });
});
