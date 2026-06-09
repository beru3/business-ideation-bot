// Xエンゲージメントbot
//   node engage.mjs --account aio-checker              … フォロー・いいね・リプライ・引用RT
//   node engage.mjs --account aio-checker auto-reply   … 自分の投稿への返信に自動で返す
//   node engage.mjs --account aio-checker follow-back  … フォローバック
//   node engage.mjs --account aio-checker unfollow     … フォロー解除
//
// 環境変数: {PREFIX}_X_*, DEEPSEEK_API_KEY
import OpenAI from 'openai';
import { loadContext, readJSON, writeJSON } from './lib/context.mjs';

const ctx = loadContext();
const { slug, config, client, paths } = ctx;

const args = process.argv.slice(process.argv.indexOf('--account') + 2);
const mode = args[0] || 'engage';

const me = await client.v2.me();
const myId = me.data.id;

// 台帳
let history = readJSON(paths.engageHistory, {});
if (!history.followed) history.followed = [];
if (!history.liked) history.liked = [];
if (!history.replyCandidateIds) history.replyCandidateIds = [];
if (!history.quotedTweetIds) history.quotedTweetIds = [];
if (!history.autoRepliedTweetIds) history.autoRepliedTweetIds = [];

const followedSet = new Set(history.followed.map(f => f.userId));
const likedSet = new Set(history.liked.map(l => l.tweetId));

// --- モード分岐 ---
if (mode === 'auto-reply') {
  await autoReplyToMentions();
  saveHistory();
  process.exit(0);
}

if (mode === 'follow-back') {
  await followBack();
  saveHistory();
  process.exit(0);
}

if (mode === 'unfollow') {
  await unfollowStale();
  saveHistory();
  process.exit(0);
}

// --- engage モード ---
const KEYWORDS = config.engageKeywords || [];
const FOLLOW_LIMIT = config.followLimit || 10;
const LIKE_LIMIT = config.likeLimit || 15;
const FOLLOW_PROFILE_KEYWORDS = config.followProfileKeywords || [];
const EXCLUDE_IDS = new Set([myId]);

// 1. キーワード検索
console.log(`[${slug}] === ツイート検索 ===`);
const allTweets = [];
for (const kw of KEYWORDS) {
  try {
    const res = await client.v2.search(kw + ' -is:retweet lang:ja', {
      max_results: 10,
      'tweet.fields': 'author_id,public_metrics,created_at,conversation_id',
      expansions: 'author_id',
      'user.fields': 'name,username,description,public_metrics',
    });
    const tweets = res.data?.data || [];
    const users = new Map((res.data?.includes?.users || []).map(u => [u.id, u]));
    for (const t of tweets) {
      allTweets.push({ ...t, _user: users.get(t.author_id), _keyword: kw });
    }
    console.log(`  "${kw}": ${tweets.length}件`);
  } catch (e) {
    console.log(`  "${kw}": エラー — ${e?.data?.detail || e.message}`);
  }
}

// 重複排除
const uniqueTweets = [];
const seenTweetIds = new Set();
for (const t of allTweets) {
  if (!seenTweetIds.has(t.id) && !EXCLUDE_IDS.has(t.author_id)) {
    seenTweetIds.add(t.id);
    uniqueTweets.push(t);
  }
}
console.log(`合計: ${uniqueTweets.length}件（重複除去後）\n`);

// 2. 自動フォロー
console.log(`[${slug}] === 自動フォロー ===`);
const uniqueAuthors = new Map();
for (const t of uniqueTweets) {
  if (t._user && !uniqueAuthors.has(t.author_id)) {
    uniqueAuthors.set(t.author_id, t._user);
  }
}

let followCount = 0;
let skippedCount = 0;
for (const [userId, user] of uniqueAuthors) {
  if (followCount >= FOLLOW_LIMIT) break;
  if (followedSet.has(userId)) continue;

  const desc = (user.description || '').toLowerCase() + (user.name || '').toLowerCase();
  const matchesProfile = FOLLOW_PROFILE_KEYWORDS.some(kw => desc.includes(kw.toLowerCase()));
  if (!matchesProfile) { skippedCount++; continue; }

  try {
    await client.v2.follow(myId, userId);
    console.log(`  + フォロー: @${user.username}（${user.name}）`);
    history.followed.push({
      userId, username: user.username, name: user.name,
      followedAt: new Date().toISOString(),
    });
    followedSet.add(userId);
    followCount++;
  } catch (e) {
    console.log(`  x @${user.username}: ${e?.data?.detail || e.message}`);
  }
}
console.log(`フォロー: ${followCount}件（スキップ: ${skippedCount}件）\n`);

// 3. 自動いいね（エンゲージメント高い順）
console.log(`[${slug}] === 自動いいね ===`);
const likeable = uniqueTweets
  .filter(t => !likedSet.has(t.id))
  .sort((a, b) => {
    const scoreA = (a.public_metrics?.like_count || 0) + (a.public_metrics?.retweet_count || 0) * 2;
    const scoreB = (b.public_metrics?.like_count || 0) + (b.public_metrics?.retweet_count || 0) * 2;
    return scoreB - scoreA;
  });

let likeCount = 0;
for (const t of likeable) {
  if (likeCount >= LIKE_LIMIT) break;
  try {
    await client.v2.like(myId, t.id);
    console.log(`  + いいね: @${t._user?.username || '?'} — ${t.text?.slice(0, 50)}…`);
    history.liked.push({
      tweetId: t.id, authorUsername: t._user?.username || '?',
      text: t.text?.slice(0, 80), likedAt: new Date().toISOString(),
    });
    likedSet.add(t.id);
    likeCount++;
  } catch (e) {
    if (e?.data?.detail?.includes('already')) { likedSet.add(t.id); }
    else { console.log(`  x ${t.id}: ${e?.data?.detail || e.message}`); }
  }
}
console.log(`いいね: ${likeCount}件\n`);

// 4. コメントリプライ（DeepSeekで生成）
console.log(`[${slug}] === コメントリプライ ===`);
const REPLY_LIMIT = config.replyLimit || 5;
const commentedSet = new Set(history.quotedTweetIds);

if (process.env.DEEPSEEK_API_KEY) {
  const ai = new OpenAI({
    baseURL: 'https://api.deepseek.com',
    apiKey: process.env.DEEPSEEK_API_KEY,
  });

  const candidates = uniqueTweets
    .filter(t => {
      const score = (t.public_metrics?.like_count || 0) + (t.public_metrics?.retweet_count || 0) * 3;
      return score >= 3 && !commentedSet.has(t.id);
    })
    .sort((a, b) => {
      const scoreA = (a.public_metrics?.like_count || 0) + (a.public_metrics?.retweet_count || 0) * 3;
      const scoreB = (b.public_metrics?.like_count || 0) + (b.public_metrics?.retweet_count || 0) * 3;
      return scoreB - scoreA;
    })
    .slice(0, REPLY_LIMIT);

  let replyCount = 0;
  for (const t of candidates) {
    const user = t._user;
    try {
      const res = await ai.chat.completions.create({
        model: 'deepseek-chat',
        messages: [
          {
            role: 'system',
            content: `あなたは${config.persona || 'Xユーザー'}としてリプライを書きます。
ルール:
- 50〜100文字の短いコメント
- 共感・補足・問いかけのいずれか。押し売りしない
- 返信本文のみ出力（@メンションは含めない）`,
          },
          {
            role: 'user',
            content: `以下のツイートにリプライを1つだけ書いてください。\n\n@${user?.username}: ${t.text}`,
          },
        ],
        temperature: 0.8,
        max_tokens: 200,
      });

      let comment = res.choices[0].message.content.trim();
      comment = comment.replace(/^["「『]|["」』]$/g, '');

      await client.v2.tweet(comment, {
        reply: { in_reply_to_tweet_id: t.id },
      });
      console.log(`  + リプライ: @${user?.username} → ${comment.slice(0, 50)}…`);
      history.quotedTweetIds.push(t.id);
      commentedSet.add(t.id);
      replyCount++;
    } catch (e) {
      console.log(`  x リプライ失敗 (@${user?.username}): ${e?.data?.detail || e.message}`);
    }
  }
  console.log(`コメントリプライ: ${replyCount}件\n`);
} else {
  console.log('DEEPSEEK_API_KEY未設定のためスキップ\n');
}

// 5. 引用RT
console.log(`[${slug}] === 引用RT ===`);
const QUOTE_LIMIT = config.quoteLimit || 2;
if (process.env.DEEPSEEK_API_KEY) {
  const ai = new OpenAI({
    baseURL: 'https://api.deepseek.com',
    apiKey: process.env.DEEPSEEK_API_KEY,
  });

  const quoteCandidates = uniqueTweets
    .filter(t => {
      const score = (t.public_metrics?.like_count || 0) + (t.public_metrics?.retweet_count || 0) * 3;
      return score >= 5 && !commentedSet.has(t.id);
    })
    .sort((a, b) => {
      const scoreA = (a.public_metrics?.like_count || 0) + (a.public_metrics?.retweet_count || 0) * 3;
      const scoreB = (b.public_metrics?.like_count || 0) + (b.public_metrics?.retweet_count || 0) * 3;
      return scoreB - scoreA;
    })
    .slice(0, QUOTE_LIMIT);

  let quoteCount = 0;
  for (const t of quoteCandidates) {
    const user = t._user;
    try {
      const res = await ai.chat.completions.create({
        model: 'deepseek-chat',
        messages: [
          {
            role: 'system',
            content: `あなたは${config.persona || 'Xユーザー'}として引用RTのコメントを書きます。
ルール:
- 50〜100文字の短いコメント
- 自分の視点を加える。補足、発展、問いかけのいずれか
- 返信本文のみ出力`,
          },
          {
            role: 'user',
            content: `以下のツイートを引用RTします。コメントを1つだけ書いてください。\n\n@${user?.username}: ${t.text}`,
          },
        ],
        temperature: 0.8,
        max_tokens: 200,
      });

      let comment = res.choices[0].message.content.trim();
      comment = comment.replace(/^["「『]|["」』]$/g, '');

      const quoteUrl = `https://x.com/${user?.username}/status/${t.id}`;
      await client.v2.tweet(`${comment}\n${quoteUrl}`);
      console.log(`  + 引用RT: @${user?.username} → ${comment.slice(0, 50)}…`);
      history.quotedTweetIds.push(t.id);
      quoteCount++;
    } catch (e) {
      console.log(`  x 引用RT失敗: ${e?.data?.detail || e.message}`);
    }
  }
  console.log(`引用RT: ${quoteCount}件\n`);
}

saveHistory();
console.log(`[${slug}] エンゲージメント完了`);

// --- ヘルパー関数 ---

function saveHistory() {
  // 直近90日分に刈り込み
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 90);
  const cutoffStr = cutoff.toISOString();
  history.followed = history.followed.filter(f => f.followedAt >= cutoffStr);
  history.liked = history.liked.filter(l => l.likedAt >= cutoffStr);
  if (history.replyCandidateIds.length > 500) {
    history.replyCandidateIds = history.replyCandidateIds.slice(-500);
  }
  if (history.quotedTweetIds.length > 500) {
    history.quotedTweetIds = history.quotedTweetIds.slice(-500);
  }
  if (history.autoRepliedTweetIds.length > 500) {
    history.autoRepliedTweetIds = history.autoRepliedTweetIds.slice(-500);
  }
  writeJSON(paths.engageHistory, history);
}

async function autoReplyToMentions() {
  console.log(`[${slug}] === 自動リプライ ===`);
  const AUTO_REPLY_LIMIT = config.autoReplyLimit || 10;
  const autoRepliedSet = new Set(history.autoRepliedTweetIds);

  if (!process.env.DEEPSEEK_API_KEY) {
    console.log('DEEPSEEK_API_KEY未設定のためスキップ');
    return;
  }
  const ai = new OpenAI({
    baseURL: 'https://api.deepseek.com',
    apiKey: process.env.DEEPSEEK_API_KEY,
  });

  let mentions;
  try {
    mentions = await client.v2.search(
      `to:${config.account} -from:${config.account} -is:retweet`,
      {
        max_results: 20,
        'tweet.fields': 'author_id,in_reply_to_user_id,conversation_id,text,created_at',
        expansions: 'author_id',
        'user.fields': 'username,name',
      },
    );
  } catch (e) {
    console.log('メンション取得エラー:', e?.data?.detail || e.message);
    return;
  }

  const tweets = mentions.data?.data || [];
  const users = new Map((mentions.data?.includes?.users || []).map(u => [u.id, u]));
  const targets = tweets.filter(t => t.in_reply_to_user_id === myId && !autoRepliedSet.has(t.id));
  console.log(`メンション: ${tweets.length}件 / 未返信: ${targets.length}件`);

  let replyCount = 0;
  for (const t of targets) {
    if (replyCount >= AUTO_REPLY_LIMIT) break;
    const user = users.get(t.author_id);
    const username = user?.username || '?';

    try {
      const res = await ai.chat.completions.create({
        model: 'deepseek-chat',
        messages: [
          {
            role: 'system',
            content: `あなたは${config.persona || 'Xユーザー'}としてリプライに返信します。
ルール:
- 50〜100文字の短い返信
- 感謝・共感・問いかけのいずれか。押し売りしない
- 返信本文のみ出力`,
          },
          {
            role: 'user',
            content: `@${username} からのリプライ: ${t.text}\n\n返信を1つだけ書いてください。`,
          },
        ],
        temperature: 0.8,
        max_tokens: 200,
      });

      let comment = res.choices[0].message.content.trim();
      comment = comment.replace(/^["「『]|["」『]$/g, '');

      await client.v2.tweet(comment, {
        reply: { in_reply_to_tweet_id: t.id },
      });
      console.log(`  + @${username} に返信: ${comment.slice(0, 60)}…`);
      history.autoRepliedTweetIds.push(t.id);
      autoRepliedSet.add(t.id);
      replyCount++;
    } catch (e) {
      console.log(`  x @${username} への返信失敗: ${e?.data?.detail || e.message}`);
    }
  }
  console.log(`自動リプライ: ${replyCount}件\n`);
}

async function followBack() {
  console.log(`[${slug}] === フォローバック ===`);
  try {
    const followers = await client.v2.followers(myId, { max_results: 100 });
    const following = await client.v2.following(myId, { max_results: 1000 });
    const followingIds = new Set((following.data?.data || []).map(u => u.id));

    let count = 0;
    for (const user of (followers.data?.data || [])) {
      if (followingIds.has(user.id)) continue;
      try {
        await client.v2.follow(myId, user.id);
        console.log(`  + フォロバ: @${user.username}`);
        history.followed.push({
          userId: user.id, username: user.username,
          followedAt: new Date().toISOString(), source: 'follow-back',
        });
        count++;
      } catch (e) {
        console.log(`  x @${user.username}: ${e?.data?.detail || e.message}`);
      }
    }
    console.log(`フォローバック: ${count}件\n`);
  } catch (e) {
    console.log(`フォロワー取得エラー: ${e?.data?.detail || e.message}`);
  }
}

async function unfollowStale() {
  console.log(`[${slug}] === フォロー解除 ===`);
  const UNFOLLOW_AFTER_DAYS = config.unfollowAfterDays || 14;
  const UNFOLLOW_LIMIT = 5;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - UNFOLLOW_AFTER_DAYS);

  try {
    const followers = await client.v2.followers(myId, { max_results: 1000 });
    const followerIds = new Set((followers.data?.data || []).map(u => u.id));

    const stale = history.followed.filter(f => {
      const followedDate = new Date(f.followedAt);
      return followedDate < cutoff && !followerIds.has(f.userId) && f.source !== 'follow-back';
    });

    let count = 0;
    for (const f of stale) {
      if (count >= UNFOLLOW_LIMIT) break;
      try {
        await client.v2.unfollow(myId, f.userId);
        console.log(`  - アンフォロー: @${f.username}（${UNFOLLOW_AFTER_DAYS}日以上フォロバなし）`);
        history.followed = history.followed.filter(h => h.userId !== f.userId);
        count++;
      } catch (e) {
        console.log(`  x @${f.username}: ${e?.data?.detail || e.message}`);
      }
    }
    console.log(`フォロー解除: ${count}件\n`);
  } catch (e) {
    console.log(`フォロワー取得エラー: ${e?.data?.detail || e.message}`);
  }
}
