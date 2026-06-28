# 株式投資AIアドバイザーダッシュボード
## Claude Code 引き継ぎドキュメント

作成日：2026年6月27日  
ステータス：Phase 1完了 → Phase 2開始待ち

---

## 📁 作業フォルダ

```
C:\Users\h034x\OneDrive\ドキュメント\claudcode\ai_stock_tool
```

---

## 🗺️ プロジェクト全体ロードマップ

| 弾 | 名称 | 状態 |
|---|---|---|
| 第1弾 | トランプ発言 株価影響スコアラー | 🔨 開発中（Phase 1完了） |
| 第2弾 | IPO・重要ニュース速報通知 | 📋 企画済 |
| 第3弾 | 井村式投資チェックリスト | 📋 企画済 |
| 第4弾 | 投資潮目チェンジャー（セクターローテーション検知） | 📋 企画済 |
| 第5弾 | アーニングコール音声テキスト化＋AI分析 | 📋 企画済 |
| 第6弾 | 潮目検知＋重要ニュース統合 おすすめ株提案AI（最終統合ツール） | 💡 最終目標 |

---

## 🎯 第1弾：トランプ発言 株価影響スコアラー

### 概要
トランプ大統領のSNS発言（Truth Social・X）をリアルタイム収集し、
株価への影響度を0〜100%でスコアリング。
閾値を超えた発言をスマホに通知するツール。

### スコアリングの段階的移行方針

#### フェーズA（人手スコアリング期）※現在ここから開始
- ダッシュボードにトランプ発言をリアルタイム表示
- ユーザーが0〜100%のスコアを手動入力・保存
- 影響セクター・メモも記録してデータ蓄積

#### フェーズB（AI学習期）
- 蓄積した「発言＋人間スコア」データをAIに学習させる
- Gemini API（無料枠）またはGroq APIを使用
- AIスコアと人間スコアを並列表示して精度を検証

#### フェーズC（AI自動化期）
- AIが新規発言を自動スコアリング
- 人間はAIスコアを修正（フィードバックループ）
- 修正データを再学習に活用して精度向上

### データ収集方法

| ソース | 方法 | 速度 | コスト |
|---|---|---|---|
| Truth Social | Mastodon互換 WebSocket Streaming API | 数秒以内 | 無料 |
| X（旧Twitter） | XRSS / RSS.app 30秒ポーリング | 〜30秒 | 無料 |

### 技術スタック

| レイヤー | 技術 | ホスティング |
|---|---|---|
| フロントエンド | React + Tailwind CSS | Vercel（無料・永続） |
| バックエンド | Python / FastAPI | Render（無料枠） |
| リアルタイム収集① | Truth Social Streaming API（WebSocket） | Render Cron Job |
| リアルタイム収集② | XRSS / RSS.app（30秒ポーリング） | Render Cron Job |
| データベース | PostgreSQL | Render（90日無料） |
| AIスコアリング | Gemini API / Groq API | 無料枠（フェーズB以降） |
| 通知 | LINE Notify / SMTP | 無料 |

### システム構成図

```
Truth Social（WebSocket）  X（30秒ポーリング）
        ↓                        ↓
   FastAPI バックエンド（Render）
        ↓
   PostgreSQL（発言・スコア保存）
        ↓
   閾値チェック → LINE/メール通知 → スマートフォン
        ↓
   React ダッシュボード（Vercel）
```

### DBテーブル設計

#### postsテーブル（発言）
```sql
CREATE TABLE posts (
    id UUID PRIMARY KEY,
    source VARCHAR NOT NULL,       -- 'truth_social' or 'x'
    post_id VARCHAR NOT NULL,      -- 元の投稿ID（重複排除用）
    content TEXT NOT NULL,         -- 発言テキスト
    posted_at TIMESTAMP NOT NULL,  -- 発言日時（UTC）
    fetched_at TIMESTAMP NOT NULL  -- 取得日時
);
```

#### scoresテーブル（スコア）
```sql
CREATE TABLE scores (
    id UUID PRIMARY KEY,
    post_id UUID REFERENCES posts(id),
    human_score INTEGER,           -- 人手スコア（0〜100）
    ai_score INTEGER,              -- AIスコア（フェーズB以降）
    sectors TEXT[],                -- 影響セクター配列
    memo TEXT,                     -- スコア理由メモ
    scored_at TIMESTAMP NOT NULL
);
```

### 推奨フォルダ構成

```
ai_stock_tool\
├── backend\
│   ├── main.py           ← FastAPI メインアプリ
│   ├── collector.py      ← 発言収集スクリプト（WebSocket・ポーリング）
│   ├── scorer.py         ← スコアリングロジック
│   ├── database.py       ← PostgreSQL接続・ORM
│   ├── notifier.py       ← LINE/メール通知
│   └── requirements.txt  ← Pythonパッケージ一覧
├── frontend\
│   ├── src\
│   │   └── App.jsx       ← デモ版を本番化（完成済みあり）
│   └── package.json
├── .env                  ← APIキー管理（Gitにコミットしない！）
├── .gitignore
└── README.md
```

### 環境変数（.env）
```
DATABASE_URL=postgresql://...
LINE_NOTIFY_TOKEN=...
GEMINI_API_KEY=...        # フェーズB以降
GROQ_API_KEY=...          # フェーズB以降
TRUTH_SOCIAL_INSTANCE=truthsocial.com
TRUMP_TRUTH_SOCIAL_ID=107780257626128497
```

---

## ✅ Phase 1 完了済み

- [x] 要件定義書 v1.1（Word形式）作成完了
- [x] デモ版ダッシュボード（React）作成完了
  - 発言フィード表示
  - 人手スコアリングUI（スライダー・セクター選択・メモ）
  - 通知シミュレーション
  - スコア履歴タブ
  - 設定タブ（閾値調整）

---

## 🚀 Phase 2 でやること（次のステップ）

### Step 1：GitHubリポジトリ作成
```bash
cd C:\Users\h034x\OneDrive\ドキュメント\claudcode\ai_stock_tool
git init
git remote add origin https://github.com/[ユーザー名]/ai_stock_tool.git
```

### Step 2：Pythonバックエンド構築
```bash
cd backend
pip install fastapi uvicorn psycopg2-binary python-dotenv websockets httpx
```

### Step 3：Truth Social WebSocket接続
- エンドポイント：`wss://truthsocial.com/api/v1/streaming`
- トランプのアカウントID：`107780257626128497`
- 認証不要（パブリックストリーム）

### Step 4：Renderデプロイ
1. render.com でアカウント作成（無料）
2. GitHubリポジトリを連携
3. PostgreSQL作成 → DATABASE_URLを環境変数に設定
4. Web Service作成（Python/FastAPI）
5. Cron Job作成（X 30秒ポーリング用）

### Step 5：Vercelデプロイ（フロントエンド）
1. vercel.com でアカウント作成（無料）
2. frontendフォルダをVercelに連携
3. VITE_API_URL環境変数にRenderのURLを設定

---

## 📝 技術的注意事項

- Renderの無料Webサービスはアイドル後にスリープ（初回レスポンス最大1分）
- RenderのPostgreSQLは無料枠で90日間有効（以降再作成または有料）
- Truth SocialのWebSocket：切断時は指数バックオフで自動再接続を実装
- `.env`ファイルは必ず`.gitignore`に追加すること
- AIスコアリング（フェーズB）はGemini API無料枠で対応（1日数十件なら十分）

---

## 👤 開発環境

- OS：Windows
- Python：インストール済み
- GitHub：アカウントあり
- 作業フォルダ：`C:\Users\h034x\OneDrive\ドキュメント\claudcode\ai_stock_tool`

