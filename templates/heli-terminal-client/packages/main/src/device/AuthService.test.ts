import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AuthService } from './AuthService';
import { HttpClient } from './HttpClient';
import { ExternalException } from '@heli/shared';
import { ERROR_CODE } from '@heli/shared';

describe('AuthService', () => {
  let auth: AuthService;
  let mockAuthenticate: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    mockAuthenticate = vi.fn();
    const fakeHttp = {
      post: mockAuthenticate,
    } as unknown as HttpClient;
    auth = new AuthService(fakeHttp, 'http://device.local', {
      refreshBeforeExpiryMs: 5 * 60 * 1000,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('login 成功后内存中持有 token', async () => {
    mockAuthenticate.mockResolvedValueOnce({ token: 'TOKEN-A' });

    const token = await auth.login('0000');

    expect(token).toBe('TOKEN-A');
    expect(await auth.getToken()).toBe('TOKEN-A');
    expect(auth.isAuthenticated()).toBe(true);
  });

  it('login 失败时不应持有 token', async () => {
    mockAuthenticate.mockRejectedValueOnce(
      new ExternalException(ERROR_CODE.PASSWORD_INCORRECT, 'password-incorrect')
    );

    await expect(auth.login('wrong')).rejects.toThrow(ExternalException);
    expect(auth.isAuthenticated()).toBe(false);
    await expect(auth.getToken()).rejects.toThrow(ExternalException);
  });

  it('token 剩余有效期 < 5 分钟时下一次 getToken 应触发自动重鉴权', async () => {
    mockAuthenticate
      .mockResolvedValueOnce({ token: 'TOKEN-A' })
      .mockResolvedValueOnce({ token: 'TOKEN-B' });

    await auth.login('0000');

    // 把 issuedAt 设为 1h55m 前，剩余 5 分钟（等于阈值）
    const issuedAt = Date.now() - (2 * 60 * 60 * 1000 - 5 * 60 * 1000);
    (auth as any).issuedAt = issuedAt;

    const token = await auth.getToken();

    expect(token).toBe('TOKEN-B');
    expect(mockAuthenticate).toHaveBeenCalledTimes(2);
  });

  it('logout 清空 token 与时间戳', async () => {
    mockAuthenticate.mockResolvedValueOnce({ token: 'TOKEN-A' });
    await auth.login('0000');

    auth.logout();

    expect(auth.isAuthenticated()).toBe(false);
    await expect(auth.getToken()).rejects.toThrow(ExternalException);
  });
});
