# business-ideation-bot

毎朝自動で新規事業の機会仮説を調査し、メールで報告するbot。

## 仕組み

1. **テーマローテーション**: 32業界・領域をランダムに1日1テーマずつ巡回
2. **DeepSeek APIで調査**: 過去の失敗事例から現代で再起動可能な機会仮説を生成
3. **重複スキップ**: 過去の結果とハッシュ・仮説名で比較し、重複は送信しない
4. **Gmail送信**: 調査結果をメールで報告
5. **履歴保存**: リポジトリにauto-commitで保存（180日分保持）

## セットアップ

### 1. GitHub Secrets に以下を登録

| Secret | 内容 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek APIキー |
| `GMAIL_USERNAME` | Gmailアドレス |
| `GMAIL_APP_PASSWORD` | Gmailアプリパスワード |

### 2. 動作確認

Actions → "Daily business ideation research" → "Run workflow" で手動実行。

## ローカル実行

```bash
cd bot
npm install
DEEPSEEK_API_KEY=xxx node research.mjs --dry
```

## テーマ一覧

`bot/themes.json` を編集してテーマを追加・削除できます。
