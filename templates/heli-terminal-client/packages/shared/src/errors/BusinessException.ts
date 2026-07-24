/** 业务规则违反（如输入校验失败） */
export class BusinessException extends Error {
  public readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'BusinessException';
    this.code = code;
  }
}
