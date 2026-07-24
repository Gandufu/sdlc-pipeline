import { HttpClient } from './HttpClient';
import { ExternalException } from '@heli/shared';
import { ERROR_CODE } from '@heli/shared';

/** token 有效期 2 小时（亿联 API 规定） */
const TOKEN_TTL_MS = 2 * 60 * 60 * 1000;

export interface AuthServiceOptions {
  /** 距过期多久时主动重鉴权，默认 5 分钟 */
  refreshBeforeExpiryMs?: number;
}

interface AuthResponse {
  token: string;
}

export class AuthService {
  private token: string | null = null;
  private issuedAt: number | null = null;
  /** 缓存密码以便自动重鉴权；C7 限制：仅内存，进程退出即清除 */
  private cachedPassword: string | null = null;
  private readonly refreshBeforeExpiryMs: number;
  private inflightLogin: Promise<string> | null = null;

  constructor(
    private readonly http: HttpClient,
    baseURL: string,
    opts: AuthServiceOptions = {}
  ) {
    // baseURL 暂未直接使用，预留给多设备切换场景
    if (!baseURL) {
      throw new Error('AuthService: baseURL 不能为空');
    }
    this.refreshBeforeExpiryMs = opts.refreshBeforeExpiryMs ?? 5 * 60 * 1000;
  }

  /**
   * 用 admin 密码换取 token。
   * 多次并发调用共享同一个 inflight Promise，避免重复鉴权。
   * 成功后缓存密码供 token 即将过期时静默重鉴权使用。
   */
  async login(password: string): Promise<string> {
    if (this.inflightLogin) {
      return this.inflightLogin;
    }
    this.inflightLogin = (async () => {
      try {
        const resp = await this.http.post<AuthResponse>(
          '/centralcontrol/authentication',
          { password },
          {}
        );
        this.token = resp.token;
        this.issuedAt = Date.now();
        this.cachedPassword = password;
        return this.token;
      } catch (err) {
        // 密码错误时不保留任何状态
        this.token = null;
        this.issuedAt = null;
        this.cachedPassword = null;
        throw err;
      }
    })();
    try {
      return await this.inflightLogin;
    } finally {
      this.inflightLogin = null;
    }
  }

  /** 获取当前 token，若即将过期则触发主动重鉴权 */
  async getToken(): Promise<string> {
    if (!this.token || !this.issuedAt) {
      throw new ExternalException(
        ERROR_CODE.AUTHENTICATION_REQUIRED,
        '未登录'
      );
    }
    const elapsed = Date.now() - this.issuedAt;
    const remaining = TOKEN_TTL_MS - elapsed;
    if (remaining <= this.refreshBeforeExpiryMs && this.cachedPassword) {
      // 即将过期：使用缓存密码静默重鉴权
      await this.login(this.cachedPassword);
    }
    return this.token as string;
  }

  logout(): void {
    this.token = null;
    this.issuedAt = null;
    this.cachedPassword = null;
  }

  isAuthenticated(): boolean {
    return this.token !== null;
  }
}
