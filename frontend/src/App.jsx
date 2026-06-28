import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const API_URL = import.meta.env.VITE_API_URL || "https://ai-stock-tool-api.onrender.com";

const SECTORS = [
  "エネルギー", "テクノロジー", "金融", "ヘルスケア",
  "素材", "輸送・物流", "防衛", "農業", "小売", "自動車",
];

const SOURCE_LABEL = { truth_social: "Truth Social", x: "X (旧Twitter)" };

export default function App() {
  const [tab, setTab] = useState("feed");
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedPost, setSelectedPost] = useState(null);
  const [score, setScore] = useState(50);
  const [sectors, setSectors] = useState([]);
  const [memo, setMemo] = useState("");
  const [saving, setSaving] = useState(false);
  const [threshold, setThreshold] = useState(70);
  const [notification, setNotification] = useState(null);

  const fetchPosts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/posts?limit=50`);
      setPosts(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPosts();
    const id = setInterval(fetchPosts, 30000);
    return () => clearInterval(id);
  }, [fetchPosts]);

  const selectPost = (post) => {
    setSelectedPost(post);
    setScore(post.human_score ?? 50);
    setSectors(post.sectors ?? []);
    setMemo(post.memo ?? "");
  };

  const saveScore = async () => {
    if (!selectedPost) return;
    setSaving(true);
    try {
      await axios.post(`${API_URL}/scores`, {
        post_id: selectedPost.id,
        human_score: score,
        sectors,
        memo,
      });
      if (score >= threshold) {
        setNotification(`スコア ${score}% — 通知送信済み`);
        setTimeout(() => setNotification(null), 4000);
      }
      await fetchPosts();
      setSelectedPost((p) => ({ ...p, human_score: score, sectors, memo }));
    } catch (e) {
      alert("保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const toggleSector = (s) =>
    setSectors((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]);

  const scoredPosts = posts.filter((p) => p.human_score != null);

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", color: "#e2e8f0", fontFamily: "sans-serif" }}>
      {/* ヘッダー */}
      <div style={{ background: "#1e293b", borderBottom: "1px solid #334155", padding: "16px 24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, color: "#f8fafc" }}>トランプ発言 株価影響スコアラー</h1>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748b" }}>リアルタイム収集 × 人手スコアリング</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ background: "#22c55e22", color: "#22c55e", padding: "2px 10px", borderRadius: 12, fontSize: 12 }}>● Live</span>
          <button onClick={fetchPosts} style={btnStyle("#334155")}>更新</button>
        </div>
      </div>

      {/* 通知バナー */}
      {notification && (
        <div style={{ background: "#dc2626", color: "#fff", textAlign: "center", padding: "8px", fontSize: 14 }}>
          🔔 {notification}
        </div>
      )}

      {/* タブ */}
      <div style={{ display: "flex", gap: 4, padding: "16px 24px 0", borderBottom: "1px solid #334155" }}>
        {[["feed", "発言フィード"], ["history", "スコア履歴"], ["settings", "設定"]].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{ ...tabStyle, ...(tab === key ? tabActiveStyle : {}) }}>
            {label}
          </button>
        ))}
      </div>

      <div style={{ padding: 24 }}>
        {/* 発言フィード */}
        {tab === "feed" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20 }}>
            {/* 投稿リスト */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                <span style={{ fontSize: 14, color: "#94a3b8" }}>{posts.length} 件の発言</span>
                {loading && <span style={{ fontSize: 12, color: "#64748b" }}>読み込み中...</span>}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {posts.map((post) => (
                  <div key={post.id} onClick={() => selectPost(post)}
                    style={{ ...cardStyle, border: selectedPost?.id === post.id ? "1px solid #3b82f6" : "1px solid #334155", cursor: "pointer" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <span style={{ fontSize: 11, color: "#64748b" }}>{SOURCE_LABEL[post.source] || post.source}</span>
                      <span style={{ fontSize: 11, color: "#64748b" }}>{formatTime(post.posted_at)}</span>
                    </div>
                    <p style={{ margin: "0 0 8px", fontSize: 14, lineHeight: 1.5 }}>{post.content}</p>
                    {post.human_score != null ? (
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <ScoreBadge score={post.human_score} />
                        {post.sectors?.map((s) => (
                          <span key={s} style={{ background: "#1e3a5f", color: "#93c5fd", fontSize: 11, padding: "1px 6px", borderRadius: 4 }}>{s}</span>
                        ))}
                      </div>
                    ) : (
                      <span style={{ fontSize: 11, color: "#475569" }}>未スコアリング</span>
                    )}
                  </div>
                ))}
                {posts.length === 0 && !loading && (
                  <div style={{ textAlign: "center", color: "#475569", padding: 40 }}>
                    発言データがありません。<br />バックエンドが起動するとデータが表示されます。
                  </div>
                )}
              </div>
            </div>

            {/* スコアリングパネル */}
            <div>
              <div style={{ ...cardStyle, border: "1px solid #334155", position: "sticky", top: 20 }}>
                <h3 style={{ margin: "0 0 16px", fontSize: 15, color: "#f8fafc" }}>スコアリング</h3>
                {selectedPost ? (
                  <>
                    <div style={{ background: "#0f172a", borderRadius: 8, padding: 12, marginBottom: 16 }}>
                      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>{SOURCE_LABEL[selectedPost.source]}</div>
                      <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>{selectedPost.content}</p>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                        <label style={{ fontSize: 13, color: "#94a3b8" }}>株価影響スコア</label>
                        <ScoreBadge score={score} />
                      </div>
                      <input type="range" min={0} max={100} value={score} onChange={(e) => setScore(Number(e.target.value))}
                        style={{ width: "100%", accentColor: scoreColor(score) }} />
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#475569" }}>
                        <span>0% 影響なし</span><span>50% 中程度</span><span>100% 非常に大</span>
                      </div>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <label style={{ fontSize: 13, color: "#94a3b8", display: "block", marginBottom: 8 }}>影響セクター</label>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {SECTORS.map((s) => (
                          <button key={s} onClick={() => toggleSector(s)}
                            style={{ ...btnStyle(sectors.includes(s) ? "#1e3a5f" : "#0f172a"), color: sectors.includes(s) ? "#93c5fd" : "#64748b", border: `1px solid ${sectors.includes(s) ? "#3b82f6" : "#334155"}`, fontSize: 12 }}>
                            {s}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div style={{ marginBottom: 16 }}>
                      <label style={{ fontSize: 13, color: "#94a3b8", display: "block", marginBottom: 6 }}>メモ</label>
                      <textarea value={memo} onChange={(e) => setMemo(e.target.value)}
                        placeholder="スコアの根拠や影響予測を記入..."
                        style={{ width: "100%", background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", padding: 10, fontSize: 13, resize: "vertical", minHeight: 80, boxSizing: "border-box" }} />
                    </div>

                    <button onClick={saveScore} disabled={saving}
                      style={{ ...btnStyle("#3b82f6"), width: "100%", padding: "10px", fontWeight: "bold", opacity: saving ? 0.6 : 1 }}>
                      {saving ? "保存中..." : "スコアを保存"}
                    </button>
                  </>
                ) : (
                  <div style={{ textAlign: "center", color: "#475569", padding: 24 }}>
                    左の発言をクリックして<br />スコアリングを開始
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* スコア履歴 */}
        {tab === "history" && (
          <div>
            <h3 style={{ margin: "0 0 16px", fontSize: 15, color: "#f8fafc" }}>スコア履歴 ({scoredPosts.length}件)</h3>
            {scoredPosts.length === 0 ? (
              <div style={{ textAlign: "center", color: "#475569", padding: 40 }}>まだスコアリングされた発言がありません</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {scoredPosts.map((post) => (
                  <div key={post.id} style={{ ...cardStyle, border: "1px solid #334155" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
                          {SOURCE_LABEL[post.source]} · {formatTime(post.posted_at)}
                        </div>
                        <p style={{ margin: "0 0 8px", fontSize: 14, lineHeight: 1.5 }}>{post.content}</p>
                        {post.sectors?.length > 0 && (
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            {post.sectors.map((s) => (
                              <span key={s} style={{ background: "#1e3a5f", color: "#93c5fd", fontSize: 11, padding: "1px 6px", borderRadius: 4 }}>{s}</span>
                            ))}
                          </div>
                        )}
                        {post.memo && <p style={{ margin: "6px 0 0", fontSize: 12, color: "#94a3b8" }}>{post.memo}</p>}
                      </div>
                      <ScoreBadge score={post.human_score} large />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 設定 */}
        {tab === "settings" && (
          <div style={{ maxWidth: 480 }}>
            <div style={{ ...cardStyle, border: "1px solid #334155" }}>
              <h3 style={{ margin: "0 0 20px", fontSize: 15, color: "#f8fafc" }}>通知設定</h3>
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <label style={{ fontSize: 14, color: "#94a3b8" }}>通知閾値スコア</label>
                  <ScoreBadge score={threshold} />
                </div>
                <input type="range" min={0} max={100} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}
                  style={{ width: "100%", accentColor: "#3b82f6" }} />
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "#64748b" }}>
                  スコアが {threshold}% 以上の発言でLINE/メール通知が送信されます
                </p>
              </div>
              <div style={{ background: "#0f172a", borderRadius: 8, padding: 12, fontSize: 13, color: "#94a3b8", lineHeight: 1.8 }}>
                <p style={{ margin: "0 0 6px" }}>通知の設定はRenderの環境変数で管理しています：</p>
                <div><code style={{ color: "#22d3ee" }}>LINE_NOTIFY_TOKEN</code> — LINE通知トークン</div>
                <div><code style={{ color: "#22d3ee" }}>SCORE_THRESHOLD</code> — 閾値（現在: {threshold}%）</div>
                <div><code style={{ color: "#22d3ee" }}>SMTP_*</code> — メール通知設定</div>
              </div>
            </div>

            <div style={{ ...cardStyle, border: "1px solid #334155", marginTop: 16 }}>
              <h3 style={{ margin: "0 0 12px", fontSize: 15, color: "#f8fafc" }}>API情報</h3>
              <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.8 }}>
                <div>バックエンドURL：<code style={{ color: "#22d3ee" }}>{API_URL}</code></div>
                <div>ヘルスチェック：<code style={{ color: "#22d3ee" }}>{API_URL}/health</code></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ScoreBadge({ score, large }) {
  const color = scoreColor(score);
  return (
    <span style={{ background: color + "22", color, padding: large ? "4px 12px" : "2px 8px", borderRadius: 12, fontSize: large ? 18 : 12, fontWeight: "bold", whiteSpace: "nowrap" }}>
      {score}%
    </span>
  );
}

function scoreColor(score) {
  if (score >= 70) return "#ef4444";
  if (score >= 40) return "#f59e0b";
  return "#22c55e";
}

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const cardStyle = { background: "#1e293b", borderRadius: 10, padding: 16 };
const btnStyle = (bg) => ({ background: bg, border: "none", borderRadius: 6, color: "#e2e8f0", padding: "6px 12px", cursor: "pointer", fontSize: 13 });
const tabStyle = { background: "transparent", border: "none", borderBottom: "2px solid transparent", color: "#64748b", padding: "8px 16px", cursor: "pointer", fontSize: 14 };
const tabActiveStyle = { color: "#f8fafc", borderBottom: "2px solid #3b82f6" };
