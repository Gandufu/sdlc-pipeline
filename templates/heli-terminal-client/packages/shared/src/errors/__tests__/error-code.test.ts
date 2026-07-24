import { describe, it, expect } from 'vitest';
import { ERROR_CODE } from '../../types/error-code';
import { ExternalException } from '../ExternalException';

describe('ErrorCode mapping', () => {
  it('已知错误码 10002 应映射为 not-support', () => {
    expect(ERROR_CODE.NOT_SUPPORT).toBe(10002);
  });

  it('10010 应映射为 exceed-maximum-concurrency', () => {
    expect(ERROR_CODE.EXCEED_MAX_CONCURRENCY).toBe(10010);
  });

  it('10007 应映射为 password-incorrect', () => {
    expect(ERROR_CODE.PASSWORD_INCORRECT).toBe(10007);
  });

  it('ExternalException 携带原始 code 与 message', () => {
    const err = new ExternalException(10002, 'not-support');
    expect(err.code).toBe(10002);
    expect(err.message).toBe('not-support');
    expect(err.name).toBe('ExternalException');
  });
});
