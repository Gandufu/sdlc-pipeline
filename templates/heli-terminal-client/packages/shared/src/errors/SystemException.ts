/** 客户端内部错误（IPC、配置缺失、序列化失败等） */
export class SystemException extends Error {
  public readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'SystemException';
    this.code = code;
  }
}
