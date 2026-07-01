import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import "./responsive.css";

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const handler = (e) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

const API_URL = import.meta.env.VITE_API_URL || "https://ai-stock-tool-api.onrender.com";

const SECTORS = [
  "エネルギー", "テクノロジー", "金融", "ヘルスケア",
  "素材", "輸送・物流", "防衛", "農業", "小売", "自動車",
];
const SOURCE_LABEL = { truth_social: "Truth Social", x: "X (旧Twitter)" };

// ── Auth utilities ────────────────────────────────────────────────────────

function getToken() { return localStorage.getItem("auth_token"); }
function setToken(t) { localStorage.setItem("auth_token", t); }
function removeToken() { localStorage.removeItem("auth_token"); }

function parseJWT(token) {
  const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(atob(b64));
}

function getUser() {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = parseJWT(token);
    if (payload.exp * 1000 < Date.now()) { removeToken(); return null; }
    return payload;
  } catch { removeToken(); return null; }
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function avatarUrl(discordId, avatar) {
  if (!avatar) return `https://cdn.discordapp.com/embed/avatars/0.png`;
  return `https://cdn.discordapp.com/avatars/${discordId}/${avatar}.png`;
}

// ── Login Page ────────────────────────────────────────────────────────────

function LoginPage() {
  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <h1 style={{ color: "#f8fafc", fontSize: 24, marginBottom: 8, textAlign: "center" }}>
        トランプ発言影響スコアラー
      </h1>
      <p style={{ color: "#64748b", fontSize: 14, marginBottom: 40, textAlign: "center" }}>
        リアルタイム収集 × 人手スコアリング
      </p>
      <a href={`${API_URL}/auth/discord`} style={{ textDecoration: "none" }}>
        <button style={{
          background: "#5865F2", color: "#fff", border: "none", borderRadius: 10,
          padding: "14px 32px", fontSize: 16, fontWeight: "bold", cursor: "pointer",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <svg width="24" height="24" viewBox="0 0 127.14 96.36" fill="#fff">
            <path d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z" />
          </svg>
          Discordでログイン
        </button>
      </a>
      <p style={{ color: "#334155", fontSize: 12, marginTop: 24 }}>
        Discordアカウントでチームメンバーとしてアクセスできます
      </p>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────

export default function App() {
  const [user, setUser] = useState(null);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    if (urlToken) {
      setToken(urlToken);
      window.history.replaceState({}, "", window.location.pathname);
    }
    const urlError = params.get("error");
    if (urlError) {
      window.history.replaceState({}, "", window.location.pathname);
    }
    setUser(getUser());
    setInitialized(true);
  }, []);

  const logout = () => { removeToken(); setUser(null); };

  if (!initialized) return null;
  if (!user) return <LoginPage />;
  return <Dashboard user={user} onLogout={logout} />;
}

// ── Dashboard ─────────────────────────────────────────────────────────────

function Dashboard({ user, onLogout }) {
  const isMobile = useIsMobile();
  const [tab, setTab] = useState("feed");
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedPost, setSelectedPost] = useState(null);
  const [score, setScore] = useState(50);
  const [sectors, setSectors] = useState([]);
  const [memo, setMemo] = useState("");
  const [saving, setSaving] = useState(false);
  const [threshold, setThreshold] = useState(() => Number(localStorage.getItem("score_threshold") ?? 70));
  const [notification, setNotification] = useState(null);
  const [activityLogs, setActivityLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [myStats, setMyStats] = useState(null);
  const [myActivity, setMyActivity] = useState([]);
  const [contentCollapsed, setContentCollapsed] = useState(true);
  const [sourceFilter, setSourceFilter] = useState("all");
  const thresholdBubbleRef = useRef(null);

  const fetchPosts = useCallback(async (src) => {
    setLoading(true);
    try {
      const filter = src ?? sourceFilter;
      const params = filter !== "all" ? `?limit=100&source=${filter}` : `?limit=100`;
      const res = await axios.get(`${API_URL}/posts${params}`, { headers: authHeaders() });
      setPosts(prev => {
        const next = res.data;
        // データに変化がなければ同じ参照を返してReactの再描画をスキップ
        if (prev.length === next.length &&
            prev.every((p, i) => p.id === next[i]?.id &&
                                 p.human_score === next[i]?.human_score &&
                                 p.ai_score === next[i]?.ai_score)) {
          return prev;
        }
        return next;
      });
    } catch (e) {
      if (e.response?.status === 401) onLogout();
    } finally {
      setLoading(false);
    }
  }, [onLogout, sourceFilter]);

  const fetchActivityLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const res = await axios.get(`${API_URL}/activity-logs?limit=100`, { headers: authHeaders() });
      setActivityLogs(res.data);
    } catch (e) {
      if (e.response?.status === 401) onLogout();
    } finally {
      setLogsLoading(false);
    }
  }, [onLogout]);

  const fetchMe = useCallback(async () => {
    try {
      const res = await axios.get(`${API_URL}/me`, { headers: authHeaders() });
      setMyStats(res.data.stats);
      setMyActivity(res.data.recent_activity);
    } catch (e) {
      if (e.response?.status === 401) onLogout();
    }
  }, [onLogout]);

  useEffect(() => {
    fetchPosts(sourceFilter);
    const id = setInterval(() => fetchPosts(sourceFilter), 30000);
    return () => clearInterval(id);
  }, [fetchPosts, sourceFilter]);

  useEffect(() => {
    if (tab === "logs") fetchActivityLogs();
    if (tab === "mypage") fetchMe();
  }, [tab, fetchActivityLogs, fetchMe]);

  useEffect(() => {
    localStorage.setItem("score_threshold", threshold);
  }, [threshold]);

  const selectPost = (post) => {
    setSelectedPost(post);
    setScore(post.human_score ?? post.ai_score ?? 50);
    setSectors(post.sectors ?? []);
    setMemo(post.memo ?? "");
    setContentCollapsed(true);
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
      }, { headers: authHeaders() });
      if (score >= threshold) {
        setNotification(`スコア ${score}% — 通知送信済み`);
        setTimeout(() => setNotification(null), 4000);
      }
      await fetchPosts();
      setSelectedPost((p) => ({ ...p, human_score: score, sectors, memo }));
    } catch (e) {
      if (e.response?.status === 401) onLogout();
      else alert("保存に失敗しました");
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
      <div className="main-header" style={{ background: "#1e293b", borderBottom: "1px solid #334155", padding: "12px 24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 className="header-title" style={{ margin: 0, fontSize: 18, color: "#f8fafc" }}>トランプ発言影響スコアラー</h1>
          <p className="header-subtitle" style={{ margin: "2px 0 0", fontSize: 11, color: "#64748b" }}>リアルタイム収集 × 人手スコアリング</p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ background: "#22c55e22", color: "#22c55e", padding: "2px 8px", borderRadius: 12, fontSize: 11 }}>● Live</span>
          <button className="header-update-btn" onClick={fetchPosts} style={btnStyle("#334155")}>更新</button>
          <div style={{ display: "flex", alignItems: "center", gap: 6, background: "#0f172a", borderRadius: 20, padding: "4px 10px 4px 4px" }}>
            <img
              src={avatarUrl(user.discord_id, user.avatar)}
              alt={user.username}
              style={{ width: 26, height: 26, borderRadius: "50%", border: "1px solid #334155" }}
            />
            <span className="header-username" style={{ fontSize: 13, color: "#e2e8f0" }}>{user.username}</span>
            {user.is_admin && <span className="header-admin-badge" style={{ background: "#7c3aed22", color: "#a78bfa", fontSize: 10, padding: "1px 6px", borderRadius: 4 }}>Admin</span>}
            <button onClick={onLogout} style={{ ...btnStyle("#1e293b"), fontSize: 11, padding: "2px 8px", color: "#64748b" }}>ログアウト</button>
          </div>
        </div>
      </div>

      {/* 通知バナー */}
      {notification && (
        <div style={{ background: "#dc2626", color: "#fff", textAlign: "center", padding: "8px", fontSize: 14 }}>
          🔔 {notification}
        </div>
      )}

      {/* タブ */}
      <div className="tab-bar" style={{ display: "flex", gap: 0, padding: "16px 24px 0", borderBottom: "1px solid #334155", overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
        {[
          ["feed", isMobile ? "フィード" : "発言フィード"],
          ["history", isMobile ? "履歴" : "スコア履歴"],
          ["mypage", isMobile ? "マイページ" : "マイページ"],
          ["logs", isMobile ? "ログ" : "操作ログ"],
          ["settings", "設定"],
          ...(user.is_admin ? [["admin", "🛠 管理"]] : []),
        ].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            style={{ ...tabStyle, ...(tab === key ? tabActiveStyle : {}), fontSize: isMobile ? 12 : 14, padding: isMobile ? "6px 10px" : "8px 16px", whiteSpace: "nowrap" }}>
            {label}
          </button>
        ))}
      </div>

      <div className="main-content" style={{ padding: 24 }}>

        {/* 発言フィード */}
        {tab === "feed" && (
          <div className="feed-grid" style={{ display: "grid", gridTemplateColumns: user.is_scorer ? "1fr 380px" : "1fr", gap: 20 }}>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
                <div style={{ display: "flex", gap: 6 }}>
                  {[["all","全て"], ["truth_social","Truth Social"], ["x","X"]].map(([val, label]) => (
                    <button key={val} onClick={() => { setSourceFilter(val); fetchPosts(val); }}
                      style={{ ...btnStyle(sourceFilter === val ? "#1e3a5f" : "#0f172a"), color: sourceFilter === val ? "#93c5fd" : "#64748b", border: `1px solid ${sourceFilter === val ? "#3b82f6" : "#334155"}`, fontSize: 12, padding: "4px 10px" }}>
                      {label}
                    </button>
                  ))}
                </div>
                <span style={{ fontSize: 12, color: "#475569" }}>
                  {posts.filter(p => sourceFilter === "all" || p.source === sourceFilter).length} 件
                  {loading && " 読み込み中..."}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {posts.filter(p => sourceFilter === "all" || p.source === sourceFilter).map((post) => (
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
                        {post.scored_by_username && (
                          <span style={{ fontSize: 11, color: "#64748b" }}>by {post.scored_by_username}</span>
                        )}
                        {post.sectors?.map((s) => (
                          <span key={s} style={{ background: "#1e3a5f", color: "#93c5fd", fontSize: 11, padding: "1px 6px", borderRadius: 4 }}>{s}</span>
                        ))}
                      </div>
                    ) : post.ai_score != null ? (
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <span style={{ fontSize: 11, color: "#a78bfa" }}>🤖 AI</span>
                        <ScoreBadge score={post.ai_score} />
                        {post.sectors?.map((s) => (
                          <span key={s} style={{ background: "#2e1a5f", color: "#c4b5fd", fontSize: 11, padding: "1px 6px", borderRadius: 4 }}>{s}</span>
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

            {/* スコアリングパネル（scorerのみ） */}
            {user.is_scorer && <div>
              <div className="scoring-panel" style={{ ...cardStyle, border: "1px solid #334155", position: "sticky", top: 20 }}>
                <h3 style={{ margin: "0 0 16px", fontSize: 15, color: "#f8fafc" }}>スコアリング</h3>
                {selectedPost ? (
                  <>
                    <div style={{ background: "#0f172a", borderRadius: 8, padding: 12, marginBottom: 16, position: "relative" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <span style={{ fontSize: 11, color: "#64748b" }}>{SOURCE_LABEL[selectedPost.source]}</span>
                        <button
                          onClick={() => setContentCollapsed(c => !c)}
                          style={{ background: "none", border: "none", color: "#475569", fontSize: 11, cursor: "pointer", padding: "0 4px" }}
                        >
                          {contentCollapsed ? "▼ 展開" : "▲ 閉じる"}
                        </button>
                      </div>
                      <div style={{
                        maxHeight: contentCollapsed ? "72px" : "none",
                        overflow: "hidden",
                        position: "relative",
                      }}>
                        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>{selectedPost.content}</p>
                        {contentCollapsed && (
                          <div style={{
                            position: "absolute", bottom: 0, left: 0, right: 0, height: 28,
                            background: "linear-gradient(transparent, #0f172a)",
                          }} />
                        )}
                      </div>
                    </div>
                    <div style={{ display: selectedPost.ai_score != null ? "flex" : "none", background: "#1a0e3a", border: "1px solid #4c1d95", borderRadius: 8, padding: "8px 12px", marginBottom: 12, alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 12, color: "#a78bfa" }}>🤖 AI参考スコア:</span>
                      <span style={{ fontSize: 14, fontWeight: "bold", color: scoreColor(selectedPost.ai_score ?? 0) }}>{selectedPost.ai_score}%</span>
                      {selectedPost.human_score == null && (
                        <span style={{ fontSize: 11, color: "#6d28d9", marginLeft: 4 }}>← スライダーに反映済み</span>
                      )}
                    </div>
                    <div style={{ marginBottom: 16 }}>
                      <label style={{ fontSize: 13, color: "#94a3b8", display: "block", marginBottom: 10 }}>株価影響スコア</label>
                      {/* スライダー＋追従ラベル */}
                      <div style={{ position: "relative", paddingTop: 28 }}>
                        {/* スコア値がスライダーのつまみに追従 */}
                        <div style={{
                          position: "absolute",
                          top: 0,
                          left: `calc(${score}% + ${(8 - score * 0.16).toFixed(1)}px)`,
                          transform: "translateX(-50%)",
                          background: scoreColor(score),
                          color: "#fff",
                          padding: "2px 9px",
                          borderRadius: 12,
                          fontSize: 14,
                          fontWeight: "bold",
                          pointerEvents: "none",
                          whiteSpace: "nowrap",
                          boxShadow: "0 2px 6px rgba(0,0,0,0.4)",
                        }}>
                          {score}%
                        </div>
                        <input type="range" min={0} max={100} value={score}
                          onChange={(e) => setScore(Number(e.target.value))}
                          style={{ width: "100%", accentColor: scoreColor(score), cursor: "pointer" }} />
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#475569", marginTop: 4 }}>
                        <span>低影響</span><span>中程度</span><span>高影響</span>
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
            </div>}
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
                          {post.scored_by_username && <span style={{ marginLeft: 8 }}>· by <strong style={{ color: "#94a3b8" }}>{post.scored_by_username}</strong></span>}
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

        {/* マイページ */}
        {tab === "mypage" && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
              <img src={avatarUrl(user.discord_id, user.avatar)} alt={user.username}
                style={{ width: 56, height: 56, borderRadius: "50%", border: "2px solid #3b82f6" }} />
              <div>
                <h2 style={{ margin: 0, fontSize: 20, color: "#f8fafc" }}>{user.username}</h2>
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>Discord ID: {user.discord_id}</p>
                <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  {user.is_admin && <span style={{ background: "#7c3aed22", color: "#a78bfa", fontSize: 11, padding: "2px 8px", borderRadius: 4 }}>Admin</span>}
                  {user.is_scorer && <span style={{ background: "#052e1622", color: "#4ade80", fontSize: 11, padding: "2px 8px", borderRadius: 4 }}>スコアラー</span>}
                </div>
              </div>
            </div>

            {/* 初回セットアップ（自分がまだ管理者でない場合のみ表示） */}
            {!user.is_admin && <BootstrapButton onSuccess={onLogout} />}

            {myStats && (
              <div className="stats-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 24 }}>
                <StatCard label="スコアリング数" value={myStats.total_scored} unit="件" />
                <StatCard label="平均スコア" value={myStats.avg_score?.toFixed(1) ?? "—"} unit="%" />
                <StatCard label="高インパクト発言" value={myStats.high_impact_count} unit="件 (70%+)" color="#ef4444" />
              </div>
            )}

            <h3 style={{ margin: "0 0 12px", fontSize: 15, color: "#f8fafc" }}>最近の操作</h3>
            {myActivity.length === 0 ? (
              <div style={{ color: "#475569", fontSize: 14 }}>まだ操作記録がありません</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {myActivity.map((log) => (
                  <ActivityRow key={log.id} log={log} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* 操作ログ */}
        {tab === "logs" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 15, color: "#f8fafc" }}>操作ログ（全ユーザー）</h3>
              <button onClick={fetchActivityLogs} style={btnStyle("#334155")}>
                {logsLoading ? "読み込み中..." : "更新"}
              </button>
            </div>
            {activityLogs.length === 0 && !logsLoading ? (
              <div style={{ textAlign: "center", color: "#475569", padding: 40 }}>ログがありません</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {activityLogs.map((log) => (
                  <div key={log.id} style={{ ...cardStyle, border: "1px solid #1e293b", display: "flex", alignItems: "center", gap: 12, padding: "10px 14px" }}>
                    <img src={avatarUrl(log.discord_id || "", log.avatar)} alt={log.username}
                      style={{ width: 32, height: 32, borderRadius: "50%", border: "1px solid #334155", flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                        <span style={{ fontSize: 13, color: "#e2e8f0", fontWeight: "bold" }}>{log.username}</span>
                        <ActionBadge action={log.action} />
                        {log.detail?.score != null && (
                          <ScoreBadge score={log.detail.score} />
                        )}
                      </div>
                      {log.detail?.memo && (
                        <p style={{ margin: 0, fontSize: 12, color: "#64748b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {log.detail.memo}
                        </p>
                      )}
                    </div>
                    <span style={{ fontSize: 11, color: "#475569", flexShrink: 0 }}>{formatTime(log.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 管理パネル（adminのみ） */}
        {tab === "admin" && user.is_admin && (
          <AdminPanel onRefresh={fetchPosts} />
        )}

        {/* 設定 */}
        {tab === "settings" && (
          <div className="settings-container" style={{ maxWidth: 480 }}>
            <div style={{ ...cardStyle, border: "1px solid #334155" }}>
              <h3 style={{ margin: "0 0 20px", fontSize: 15, color: "#f8fafc" }}>通知設定</h3>
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <label style={{ fontSize: 14, color: "#94a3b8" }}>通知閾値スコア</label>
                  <span ref={thresholdBubbleRef} style={{ background: scoreColor(threshold), color: "#fff", padding: "3px 12px", borderRadius: 12, fontSize: 15, fontWeight: "bold", minWidth: 52, textAlign: "center" }}>{threshold}%</span>
                </div>
                <div style={{ position: "relative" }}>
                  <input type="range" min={0} max={100} value={threshold}
                    onInput={(e) => {
                      const v = Number(e.target.value);
                      setThreshold(v);
                      if (thresholdBubbleRef.current) {
                        thresholdBubbleRef.current.textContent = v + "%";
                        thresholdBubbleRef.current.style.background = scoreColor(v);
                      }
                    }}
                    onChange={(e) => setThreshold(Number(e.target.value))}
                    style={{ width: "100%", accentColor: scoreColor(threshold), cursor: "pointer" }} />
                </div>
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "#64748b" }}>
                  スコアが {threshold}% 以上の発言でLINE/メール通知が送信されます
                </p>
              </div>
              <div style={{ background: "#0f172a", borderRadius: 8, padding: 12, fontSize: 13, color: "#94a3b8", lineHeight: 1.8 }}>
                <p style={{ margin: "0 0 6px" }}>通知の設定はRenderの環境変数で管理しています：</p>
                <div><code style={{ color: "#22d3ee" }}>DISCORD_WEBHOOK_URL</code> — Discord Webhook URL</div>
                <div><code style={{ color: "#22d3ee" }}>SCORE_THRESHOLD</code> — 閾値（現在: {threshold}%）</div>
                <div><code style={{ color: "#22d3ee" }}>SMTP_*</code> — メール通知設定（任意）</div>
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

// ── Sub components ─────────────────────────────────────────────────────────

function BootstrapButton({ onSuccess }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/setup/bootstrap`, {}, { headers: authHeaders() });
      setStatus(`✅ ${res.data.username} を管理者＆スコアラーに設定しました。再ログインしてください。`);
      setTimeout(onSuccess, 3000);
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      if (msg.includes("すでに存在")) setStatus(null);
      else setStatus(`❌ ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  if (status === null && !loading) {
    return (
      <div style={{ ...cardStyle, border: "1px solid #7c3aed55", marginBottom: 24, padding: "12px 16px" }}>
        <p style={{ margin: "0 0 10px", fontSize: 13, color: "#94a3b8" }}>
          まだ管理者が設定されていません。あなたが最初の管理者になりますか？
        </p>
        <button onClick={run} style={{ ...btnStyle("#7c3aed"), fontWeight: "bold" }}>
          自分を管理者＆スコアラーに設定する
        </button>
      </div>
    );
  }
  if (status) return <div style={{ ...cardStyle, border: "1px solid #334155", marginBottom: 24, fontSize: 13, color: "#4ade80" }}>{status}</div>;
  return <div style={{ color: "#64748b", fontSize: 13, marginBottom: 24 }}>設定中...</div>;
}

function AdminPanel({ onRefresh }) {
  const isMobile = useIsMobile();
  const [text, setText] = useState("");
  const [source, setSource] = useState("truth_social");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [users, setUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);

  const fetchUsers = async () => {
    setUsersLoading(true);
    try {
      const res = await axios.get(`${API_URL}/admin/users`, { headers: authHeaders() });
      setUsers(res.data);
    } catch {}
    finally { setUsersLoading(false); }
  };

  useEffect(() => { fetchUsers(); }, []);

  const toggleScorer = async (userId, current) => {
    try {
      await axios.patch(`${API_URL}/admin/users/${userId}/role`, { is_scorer: !current }, { headers: authHeaders() });
      fetchUsers();
    } catch (e) { alert("更新失敗: " + (e.response?.data?.detail || e.message)); }
  };

  const submit = async () => {
    const lines = text.split("\n").map(l => l.trim()).filter(l => l.length > 0);
    if (lines.length === 0) return;
    setSubmitting(true);
    setResult(null);
    try {
      const posts = lines.map(content => ({ source, content }));
      const res = await axios.post(`${API_URL}/admin/posts`, { posts }, { headers: authHeaders() });
      setResult(`✅ ${res.data.inserted} 件追加（${res.data.total} 件中）`);
      setText("");
      onRefresh();
    } catch (e) {
      setResult(`❌ エラー: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: isMobile ? "100%" : 640 }}>
      <div style={{ ...cardStyle, border: "1px solid #7c3aed55", marginBottom: 16 }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 15, color: "#a78bfa" }}>🛠 管理者パネル</h3>
        <p style={{ margin: "0 0 20px", fontSize: 12, color: "#64748b" }}>
          Truth SocialのAPIはクラウドサーバーからブロックされているため、手動で発言を追加できます。
        </p>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, color: "#94a3b8", display: "block", marginBottom: 8 }}>ソース</label>
          <div style={{ display: "flex", gap: 8 }}>
            {[["truth_social", "Truth Social"], ["x", "X (旧Twitter)"]].map(([val, label]) => (
              <button key={val} onClick={() => setSource(val)}
                style={{ ...btnStyle(source === val ? "#7c3aed" : "#1e293b"), border: `1px solid ${source === val ? "#7c3aed" : "#334155"}`, color: source === val ? "#fff" : "#94a3b8" }}>
                {label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, color: "#94a3b8", display: "block", marginBottom: 6 }}>
            発言テキスト（1行1投稿）
          </label>
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder={"例：\nWe are going to put tremendous tariffs on China!\nGreat news for American steel workers!"}
            style={{ width: "100%", background: "#0f172a", border: "1px solid #334155", borderRadius: 8, color: "#e2e8f0", padding: 12, fontSize: 13, resize: "vertical", minHeight: 160, boxSizing: "border-box", fontFamily: "monospace" }}
          />
          <div style={{ fontSize: 11, color: "#475569", marginTop: 4 }}>
            {text.split("\n").filter(l => l.trim()).length} 件入力中
          </div>
        </div>

        {result && (
          <div style={{ background: result.startsWith("✅") ? "#052e16" : "#450a0a", border: `1px solid ${result.startsWith("✅") ? "#166534" : "#991b1b"}`, borderRadius: 8, padding: "10px 14px", fontSize: 13, color: result.startsWith("✅") ? "#4ade80" : "#fca5a5", marginBottom: 16 }}>
            {result}
          </div>
        )}

        <button onClick={submit} disabled={submitting || text.trim().length === 0}
          style={{ ...btnStyle("#7c3aed"), padding: "10px 24px", fontWeight: "bold", opacity: submitting || !text.trim() ? 0.5 : 1 }}>
          {submitting ? "追加中..." : "発言を追加"}
        </button>
      </div>

      <div style={{ ...cardStyle, border: "1px solid #334155", marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: "#f8fafc" }}>ユーザー管理</h3>
          <button onClick={fetchUsers} style={btnStyle("#334155")}>{usersLoading ? "読込中..." : "更新"}</button>
        </div>
        {users.length === 0 ? (
          <div style={{ color: "#475569", fontSize: 13 }}>ユーザーがいません</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {users.map(u => (
              <div key={u.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", background: "#0f172a", borderRadius: 8 }}>
                <img src={avatarUrl(u.discord_id, u.avatar)} alt={u.username}
                  style={{ width: 32, height: 32, borderRadius: "50%", border: "1px solid #334155", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: "#e2e8f0" }}>{u.username}</div>
                  <div style={{ fontSize: 10, color: "#475569" }}>{u.discord_id}</div>
                </div>
                {u.is_admin && <span style={{ background: "#7c3aed22", color: "#a78bfa", fontSize: 10, padding: "1px 6px", borderRadius: 4 }}>Admin</span>}
                <button
                  onClick={() => toggleScorer(u.id, u.is_scorer)}
                  style={{
                    ...btnStyle(u.is_scorer ? "#052e16" : "#1e293b"),
                    border: `1px solid ${u.is_scorer ? "#166534" : "#334155"}`,
                    color: u.is_scorer ? "#4ade80" : "#64748b",
                    fontSize: 12, padding: "3px 10px",
                  }}
                >
                  {u.is_scorer ? "✓ スコアラー" : "スコアラーにする"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ ...cardStyle, border: "1px solid #334155" }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 14, color: "#f8fafc" }}>Truth Social 収集状況</h3>
        <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 2 }}>
          <div>状態：<span style={{ color: "#22c55e" }}>●</span> <span style={{ color: "#4ade80" }}>自動収集中（CNNアーカイブ経由）</span></div>
          <div>ソース：CNN公開アーカイブ JSON（5分ごと更新）</div>
          <div>備考：Truth Social直接アクセスは403のため、CNNの全投稿アーカイブを使用</div>
        </div>
        <div style={{ marginTop: 12, background: "#0f172a", borderRadius: 6, padding: 10, fontSize: 12, color: "#64748b" }}>
          <code style={{ color: "#22d3ee" }}>ix.cnn.io/data/truth-social/truth_archive.json</code>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, unit, color }) {
  return (
    <div style={{ ...cardStyle, border: "1px solid #334155", textAlign: "center" }}>
      <div style={{ fontSize: 28, fontWeight: "bold", color: color || "#f8fafc" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{unit}</div>
      <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>{label}</div>
    </div>
  );
}

function ActivityRow({ log }) {
  return (
    <div style={{ ...cardStyle, border: "1px solid #1e293b", display: "flex", alignItems: "center", gap: 10, padding: "8px 12px" }}>
      <ActionBadge action={log.action} />
      <span style={{ fontSize: 12, color: "#94a3b8", flex: 1 }}>
        {log.action === "SCORE_SAVED" && log.detail?.score != null
          ? `スコア ${log.detail.score}% を保存`
          : log.action === "LOGIN"
          ? "ログイン"
          : log.action}
      </span>
      <span style={{ fontSize: 11, color: "#475569" }}>{formatTime(log.created_at)}</span>
    </div>
  );
}

function ActionBadge({ action }) {
  const map = {
    LOGIN: ["ログイン", "#22c55e"],
    SCORE_SAVED: ["スコア保存", "#3b82f6"],
    SCORE_UPDATED: ["スコア更新", "#f59e0b"],
  };
  const [label, color] = map[action] || [action, "#64748b"];
  return (
    <span style={{ background: color + "22", color, fontSize: 10, padding: "1px 6px", borderRadius: 4, whiteSpace: "nowrap" }}>
      {label}
    </span>
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
  return new Date(iso).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
}

const cardStyle = { background: "#1e293b", borderRadius: 10, padding: 16 };
const btnStyle = (bg) => ({ background: bg, border: "none", borderRadius: 6, color: "#e2e8f0", padding: "6px 12px", cursor: "pointer", fontSize: 13 });
const tabStyle = { background: "transparent", border: "none", borderBottom: "2px solid transparent", color: "#64748b", padding: "8px 16px", cursor: "pointer", fontSize: 14 };
const tabActiveStyle = { color: "#f8fafc", borderBottom: "2px solid #3b82f6" };
