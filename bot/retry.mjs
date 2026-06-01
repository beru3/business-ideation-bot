// 指数バックオフ付きリトライヘルパー（DeepSeek API 呼び出し用）
//
// retryWithBackoff(fn, { maxRetries, baseDelayMs })
//   fn: async () => result  — 成功で結果を返し、失敗で throw する関数
//   最大 maxRetries 回リトライ（初回含め最大 maxRetries+1 回実行）
//   リトライ間隔: baseDelayMs * 2^attempt（ジッター付き）

export async function retryWithBackoff(fn, { maxRetries = 3, baseDelayMs = 1000 } = {}) {
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt < maxRetries) {
        const delay = baseDelayMs * 2 ** attempt * (0.5 + Math.random() * 0.5);
        console.warn(`リトライ ${attempt + 1}/${maxRetries} (${Math.round(delay)}ms後): ${err.message}`);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }
  throw lastError;
}
