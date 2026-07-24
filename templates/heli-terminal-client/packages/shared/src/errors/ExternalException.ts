import { ErrorCode } from '../types/error-code';

/** 来自设备 HTTP API 的错误（10001~10011） */
export class ExternalException extends Error {
  public readonly code: ErrorCode;
  public readonly remoteMessage: string;

  constructor(code: ErrorCode, remoteMessage: string) {
    super(remoteMessage);
    this.name = 'ExternalException';
    this.code = code;
    this.remoteMessage = remoteMessage;
  }
}
