import { describe, it, expect, vi } from 'vitest';
import { retryWithBackoff } from '../retry.mjs';

describe('retryWithBackoff', () => {
  it('should return result on first success', async () => {
    const fn = vi.fn().mockResolvedValue('ok');
    const result = await retryWithBackoff(fn, { maxRetries: 3, baseDelayMs: 1 });
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('should retry and succeed on second attempt', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('fail1'))
      .mockResolvedValue('ok');
    const result = await retryWithBackoff(fn, { maxRetries: 3, baseDelayMs: 1 });
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('should throw after all retries exhausted', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('persistent'));
    await expect(
      retryWithBackoff(fn, { maxRetries: 2, baseDelayMs: 1 })
    ).rejects.toThrow('persistent');
    expect(fn).toHaveBeenCalledTimes(3); // initial + 2 retries
  });

  it('should default to maxRetries=3 if not specified', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('fail'));
    await expect(
      retryWithBackoff(fn, { baseDelayMs: 1 })
    ).rejects.toThrow('fail');
    expect(fn).toHaveBeenCalledTimes(4); // initial + 3 retries
  });
});
