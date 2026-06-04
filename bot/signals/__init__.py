"""
リアルタイム信号収集モジュール

各コレクターは共通フォーマットで信号を出力する:
{
  "source": "twitter|trends|producthunt|appreviews|reddit|jobs|regulation",
  "collected_at": "ISO8601",
  "signals": [
    {
      "raw_text": "元テキスト",
      "pain_point": "抽出された痛み",
      "who": "誰が困っているか",
      "industry": "業種",
      "urgency": "high|medium|low",
      "url": "ソースURL"
    }
  ]
}
"""
