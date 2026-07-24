import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';
import { ERROR_CODE, ErrorCode, ExternalException } from '@heli/shared';

export interface HttpClientOptions {
  baseURL: string;
  maxConcurrent: number; // 亿联 API 限制 ≤10
  requestTimeoutMs?: number;
}

interface ErrorPayload {
  'error-code'?: number;
  'error-msg'?: string;
}

interface ApiResponse<T> {
  status: number;
  data?: T;
}

export class HttpClient {
  private readonly axios: AxiosInstance;
  private readonly maxConcurrent: number;
  private readonly timeout: number;
  private activeCount = 0;
  private readonly waitQueue: Array<() => void> = [];

  constructor(opts: HttpClientOptions) {
    this.maxConcurrent = opts.maxConcurrent;
    this.timeout = opts.requestTimeoutMs ?? 10_000;
    this.axios = axios.create({
      baseURL: opts.baseURL,
      timeout: this.timeout,
    });
  }

  async get<T>(path: string, opts: { token?: string } = {}): Promise<T> {
    return this.request<T>({
      method: 'GET',
      url: path,
      ...(opts.token !== undefined ? { token: opts.token } : {}),
    });
  }

  async post<T>(
    path: string,
    body: unknown,
    opts: { token?: string } = {}
  ): Promise<T> {
    return this.request<T>({
      method: 'POST',
      url: path,
      data: body,
      ...(opts.token !== undefined ? { token: opts.token } : {}),
    });
  }

  private async request<T>(cfg: {
    method: 'GET' | 'POST';
    url: string;
    data?: unknown;
    token?: string;
  }): Promise<T> {
    await this.acquireSlot();

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (cfg.token) {
        headers.Authorization = `Bearer ${cfg.token}`;
      }

      const axiosCfg: AxiosRequestConfig = {
        method: cfg.method,
        url: cfg.url,
        headers,
        data: cfg.data,
      };

      const resp = await this.axios.request<ApiResponse<T>>(axiosCfg);
      return this.handleResponse(resp.data);
    } catch (err) {
      // axios transport 失败（设备离线 / TLS 错误 / 超时）归一为 ExternalException(UNKNOWN)
      if (err instanceof ExternalException) throw err;
      const msg = err instanceof Error ? err.message : String(err);
      throw new ExternalException(ERROR_CODE.UNKNOWN, `设备离线：${msg}`);
    } finally {
      this.releaseSlot();
    }
  }

  private handleResponse<T>(resp: ApiResponse<T>): T {
    if (resp.status === 200) {
      return resp.data as T;
    }

    // 业务错误（status=404/500 携带 error-code）
    if (resp.data && typeof resp.data === 'object') {
      const err = (resp.data as unknown as ErrorPayload) || {};
      const codeNum = err['error-code'];
      const msg = err['error-msg'] ?? 'unknown';
      if (typeof codeNum === 'number') {
        const code = codeNum as ErrorCode;
        const knownCodes: ReadonlyArray<number> = Object.values(ERROR_CODE);
        if (knownCodes.includes(code)) {
          throw new ExternalException(code, msg);
        }
      }
    }

    throw new ExternalException(ERROR_CODE.UNKNOWN, 'malformed response');
  }

  private async acquireSlot(): Promise<void> {
    if (this.activeCount < this.maxConcurrent) {
      this.activeCount += 1;
      return;
    }
    await new Promise<void>((resolve) => this.waitQueue.push(resolve));
    this.activeCount += 1;
  }

  private releaseSlot(): void {
    this.activeCount -= 1;
    const next = this.waitQueue.shift();
    if (next) next();
  }
}
