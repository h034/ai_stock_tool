const STORAGE_KEY = "app_error_log";
const MAX_ENTRIES = 20;

// 画面が真っ白になるようなクラッシュはユーザー操作で消えてしまうため、
// 発生時点の詳細（メッセージ・スタック・発生箇所）をlocalStorageに残し、
// 設定画面から後から確認できるようにする。
export function recordError(error, componentStack) {
  const entry = {
    time: new Date().toISOString(),
    message: error?.message ?? String(error),
    stack: error?.stack ?? null,
    componentStack: componentStack ?? null,
    url: window.location.href,
  };

  console.error("[app-error]", entry);

  try {
    const log = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    log.push(entry);
    while (log.length > MAX_ENTRIES) log.shift();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(log));
  } catch {
    // localStorageが使えない環境では記録をあきらめる
  }
}

export function getErrorLog() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function clearErrorLog() {
  localStorage.removeItem(STORAGE_KEY);
}
