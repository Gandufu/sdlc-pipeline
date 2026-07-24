import { describe, it, expect, vi } from 'vitest';
import { createNetworkApi } from './network.api';

describe('network.api', () => {
  it('getInfo 调用 GET /network/info', async () => {
    const http = { get: vi.fn().mockResolvedValue({ 'network-list': [] }) };
    const api = createNetworkApi(http as any);

    await api.getInfo('T');

    expect(http.get).toHaveBeenCalledWith('/centralcontrol/network/info', { token: 'T' });
  });

  it('ping 调用 POST /diagnostics/network action=ping', async () => {
    const http = { post: vi.fn().mockResolvedValue({ result: '...' }) };
    const api = createNetworkApi(http as any);

    await api.ping('T', '8.8.8.8', 4);

    expect(http.post).toHaveBeenCalledWith(
      '/centralcontrol/diagnostics/network',
      { action: 'ping', num: 4, ip: '8.8.8.8' },
      { token: 'T' }
    );
  });

  it('traceroute 调用 POST /diagnostics/network action=traceroute', async () => {
    const http = { post: vi.fn().mockResolvedValue({ result: '...' }) };
    const api = createNetworkApi(http as any);

    await api.traceroute('T', '8.8.8.8', 30);

    expect(http.post).toHaveBeenCalledWith(
      '/centralcontrol/diagnostics/network',
      { action: 'traceroute', num: 30, ip: '8.8.8.8' },
      { token: 'T' }
    );
  });
});
