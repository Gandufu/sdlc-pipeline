import { describe, it, expect, vi, beforeEach } from 'vitest';
import axios from 'axios';
import { HttpClient } from './HttpClient';
import { ExternalException } from '@heli/shared';
import { ERROR_CODE } from '@heli/shared';

vi.mock('axios');
const mockedAxios = vi.mocked(axios, true);

describe('HttpClient', () => {
  let client: HttpClient;
  let mockAdapter: any;

  beforeEach(() => {
    mockAdapter = vi.fn();
    mockedAxios.create.mockReturnValue({ request: mockAdapter } as any);
    client = new HttpClient({
      baseURL: 'http://device.local',
      maxConcurrent: 10,
    });
  });

  it('GET 请求成功时返回 data 字段', async () => {
    mockAdapter.mockResolvedValueOnce({
      status: 200,
      data: { status: 200, data: { foo: 'bar' } },
    });

    const result = await client.get('/centralcontrol/system/version', {
      token: 'TOKEN',
    });

    expect(result).toEqual({ foo: 'bar' });
    expect(mockAdapter).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'GET',
        url: '/centralcontrol/system/version',
        headers: expect.objectContaining({
          Authorization: 'Bearer TOKEN',
        }),
      })
    );
  });

  it('业务 status=404 + error-code 应抛出 ExternalException', async () => {
    mockAdapter.mockResolvedValue({
      status: 200,
      data: {
        status: 404,
        data: { 'error-code': 10002, 'error-msg': 'not-support' },
      },
    });

    await expect(
      client.get('/centralcontrol/foo', { token: 'T' })
    ).rejects.toThrow(ExternalException);

    await expect(
      client.get('/centralcontrol/foo', { token: 'T' })
    ).rejects.toMatchObject({
      code: ERROR_CODE.NOT_SUPPORT,
      remoteMessage: 'not-support',
    });
  });

  it('业务 status=500 + error-code=10009 应触发 AUTHENTICATION_REQUIRED', async () => {
    mockAdapter.mockResolvedValueOnce({
      status: 200,
      data: {
        status: 500,
        data: { 'error-code': 10009, 'error-msg': 'authentication-required' },
      },
    });

    await expect(
      client.get('/centralcontrol/foo', { token: 'T' })
    ).rejects.toMatchObject({
      code: ERROR_CODE.AUTHENTICATION_REQUIRED,
    });
  });

  it('并发超过 maxConcurrent 时应排队等待', async () => {
    const startOrder: number[] = [];
    const endOrder: number[] = [];

    mockAdapter.mockImplementation(() => {
      const id = startOrder.length;
      startOrder.push(id);
      return new Promise((resolve) =>
        setTimeout(() => {
          endOrder.push(id);
          resolve({ status: 200, data: { status: 200, data: {} } });
        }, 10)
      );
    });

    const promises = Array.from({ length: 12 }, () =>
      client.get('/x', { token: 'T' })
    );
    await Promise.all(promises);

    // 前 10 个请求 0~9 同步拿到槽位并立即发起；11 和 12 必须排队等待
    expect(startOrder).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(endOrder.slice(0, 10).sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  });

  it('axios transport 失败（设备离线/超时）应归一为 ExternalException(UNKNOWN)', async () => {
    // 模拟 axios 抛出 AxiosError
    const axiosErr = Object.assign(new Error('Network Error'), { isAxiosError: true });
    mockAdapter.mockRejectedValueOnce(axiosErr);

    await expect(
      client.get('/centralcontrol/foo', { token: 'T' })
    ).rejects.toMatchObject({
      code: ERROR_CODE.UNKNOWN,
      remoteMessage: expect.stringContaining('设备离线'),
    });
  });
});
