// Wordi frontend — vanilla JS, no build step. All user-provided text is rendered via textContent.

const $ = (id) => document.getElementById(id);
const LS = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(`wordi:${key}`);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(`wordi:${key}`, JSON.stringify(value));
    } catch {
      /* storage unavailable: the server still has the game */
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(`wordi:${key}`);
    } catch {}
  },
};

// --- player identity ---------------------------------------------------------

// crypto.randomUUID only exists in secure contexts (HTTPS / localhost); an iPhone opening
// http://<computer-ip>:8000 on the home network doesn't have it.
function uuid4() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function playerId() {
  let pid = LS.get("pid");
  if (!pid || !/^[0-9a-f-]{36}$/i.test(pid)) {
    const cookie = document.cookie.match(/(?:^|;\s*)wordi_pid=([0-9a-f-]{36})/i);
    pid = cookie ? cookie[1] : uuid4();
    LS.set("pid", pid);
  }
  document.cookie = `wordi_pid=${pid}; max-age=31536000; path=/; samesite=lax`;
  return pid;
}
const PID = playerId();

// --- API ---------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-Player-Id": PID },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "אין חיבור לשרת. נסו שוב.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail && typeof data.detail === "object" && !Array.isArray(data.detail) ? data.detail : data;
    throw new ApiError(res.status, d.error || "error", d.message || "משהו השתבש. נסו שוב.");
  }
  return data;
}

// --- formatting --------------------------------------------------------------

function formatDuration(ms) {
  if (ms == null) return "—";
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
const fmtSim = (x) => (x == null ? "—" : x.toFixed(2));

function el(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}

// --- state -------------------------------------------------------------------

const state = {
  mode: LS.get("mode", "daily") === "free" ? "free" : "daily",
  daily: null, // /api/daily-info
  session: null, // SessionState from the server
  latestSeq: null,
  busy: false,
  lbScope: "today",
  lbSort: "wins",
};

function storageKey(sess) {
  return sess.mode === "daily" ? `daily:${sess.puzzle_number}` : "free:current";
}

function saveSession() {
  const s = state.session;
  if (!s) return;
  LS.set(storageKey(s), { ...s, latestSeq: state.latestSeq, savedAt: Date.now() });
}

// --- personal stats (daily only) ---------------------------------------------

function recordDailyResult(sess) {
  const history = LS.get("history", {});
  if (history[sess.puzzle_number]) return;
  history[sess.puzzle_number] = {
    won: sess.solved,
    guesses: sess.guess_count,
    hint: sess.used_hint,
    ms: sess.duration_ms,
  };
  LS.set("history", history);
}

function computeStats() {
  const history = LS.get("history", {});
  const nums = Object.keys(history).map(Number).sort((a, b) => a - b);
  const wins = nums.filter((n) => history[n].won);
  const avg = wins.length ? wins.reduce((t, n) => t + history[n].guesses, 0) / wins.length : 0;
  let maxStreak = 0;
  let run = 0;
  let prev = null;
  for (const n of nums) {
    if (history[n].won) run = prev === n - 1 && run > 0 ? run + 1 : 1;
    else run = 0;
    maxStreak = Math.max(maxStreak, run);
    prev = n;
  }
  // current streak: consecutive wins ending today, or yesterday if today isn't finished yet
  const today = state.daily?.puzzle_number;
  let streak = 0;
  if (today) {
    let n = history[today] ? today : today - 1;
    while (history[n]?.won) {
      streak += 1;
      n -= 1;
    }
  }
  return {
    played: nums.length,
    winRate: nums.length ? Math.round((wins.length / nums.length) * 100) : 0,
    avg: avg ? avg.toFixed(1) : "—",
    streak,
    maxStreak,
    wins: wins.length,
  };
}

function renderStats() {
  const s = computeStats();
  const grid = $("stats-grid");
  grid.replaceChildren();
  for (const [label, value] of [
    ["שוחקו", s.played],
    ["ניצחונות", `${s.winRate}%`],
    ["ממוצע ניחושים", s.avg],
    ["רצף נוכחי", s.streak],
    ["רצף שיא", s.maxStreak],
    ["פתרונות", s.wins],
  ]) {
    const box = el("div", "stat");
    box.append(el("dt", "", label), el("dd", "", String(value)));
    grid.append(box);
  }
}

// --- rendering ---------------------------------------------------------------

function setMessage(text, tone = "info") {
  const m = $("message");
  m.textContent = text || "";
  m.className = `mt-2 min-h-[1.5rem] text-sm font-medium ${
    tone === "error" ? "text-rose-600 dark:text-rose-400" : tone === "ok" ? "text-emerald-600 dark:text-emerald-400" : "text-slate-600 dark:text-slate-300"
  }`;
}

function closenessCell(g, secret) {
  const td = el("td", "py-2 pe-3");
  if (secret && g.word === secret) {
    td.append(el("span", "font-bold text-emerald-600 dark:text-emerald-400", "🎯 נמצאה!"));
    return td;
  }
  if (g.rank == null) {
    td.append(el("span", "text-xs text-slate-400", g.similarity > 0 ? "רחוק" : "🥶 קר"));
    return td;
  }
  const wrap = el("div", "flex items-center gap-2");
  const bar = el("div", "h-2 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700");
  const fill = el("div", "h-full rounded-full");
  fill.style.width = `${Math.max(2, g.rank / 10)}%`;
  fill.style.background = g.rank >= 990 ? "#dc2626" : g.rank >= 900 ? "#f97316" : g.rank >= 500 ? "#eab308" : "#22c55e";
  bar.append(fill);
  wrap.append(bar, el("span", "w-14 shrink-0 text-start text-xs tabular-nums text-slate-500 dark:text-slate-400", `${g.rank}/1000`));
  td.append(wrap);
  return td;
}

function guessRow(g, { highlight, secret }) {
  const tr = el("tr", `border-t border-slate-100 dark:border-slate-800 ${highlight ? "bg-indigo-50 dark:bg-indigo-950/60" : ""}`);
  tr.append(el("td", "py-2 text-center text-xs tabular-nums text-slate-400", String(g.seq)));
  const word = el("td", `truncate py-2 ${highlight ? "font-bold" : "font-medium"}`);
  word.textContent = g.word;
  if (g.is_hint) word.append(el("span", "ms-1 text-xs", "💡"));
  const sim = el("td", "py-2 text-center tabular-nums");
  sim.append(el("bdi", "", fmtSim(g.similarity)));
  sim.firstChild.dir = "ltr"; // keep the minus sign of negative scores on the left
  tr.append(word, sim, closenessCell(g, secret));
  return tr;
}

function renderGuesses() {
  const sess = state.session;
  const guesses = sess ? sess.guesses : [];
  const secret = sess?.secret ?? null;
  // the latest guess is pinned above the sorted list (once there is a list to pin it above)
  const latest = guesses.length > 1 ? guesses.find((g) => g.seq === state.latestSeq) : undefined;
  $("latest-body").replaceChildren(...(latest ? [guessRow(latest, { highlight: true, secret })] : []));
  const sorted = [...guesses].sort((a, b) => b.similarity - a.similarity || a.seq - b.seq);
  $("guesses-body").replaceChildren(...sorted.map((g) => guessRow(g, { highlight: g.seq === state.latestSeq, secret })));
  if (latest) {
    $("latest-body").lastChild.classList.add("border-b-4", "border-b-indigo-200", "dark:border-b-indigo-900");
  }
  $("empty-state").classList.toggle("hidden", guesses.length > 0);
}

function renderHeader() {
  const sess = state.session;
  const title = $("puzzle-title");
  if (state.mode === "daily") {
    title.textContent = state.daily ? `אתגר יומי #${state.daily.puzzle_number}` : "אתגר יומי";
  } else {
    title.textContent = "משחק חופשי";
  }
  const stats = sess?.stats ?? (state.mode === "daily" ? state.daily?.stats : null);
  $("puzzle-stats").textContent = stats
    ? `המילה הקרובה ביותר: ${fmtSim(stats.top1)} · העשירית: ${fmtSim(stats.top10)} · האלף: ${fmtSim(stats.top1000)}`
    : "";
  for (const tab of document.querySelectorAll(".mode-tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.mode === state.mode));
  }
}

function renderControls() {
  const sess = state.session;
  const finished = !sess || sess.solved || sess.gave_up;
  $("guess-input").disabled = finished || state.busy;
  $("guess-btn").disabled = finished || state.busy;
  $("hint-btn").disabled = finished || state.busy;
  $("giveup-btn").disabled = finished || state.busy;
  $("hint-btn").classList.toggle("hidden", Boolean(sess?.solved || sess?.gave_up));
  $("giveup-btn").classList.toggle("hidden", Boolean(sess?.solved || sess?.gave_up));
  $("new-game-btn").classList.toggle("hidden", state.mode !== "free");

  const banner = $("finished-banner");
  if (sess && (sess.solved || sess.gave_up)) {
    banner.replaceChildren();
    banner.append(
      el("span", "", sess.solved ? "🎉 פתרתם! המילה: " : "המילה הייתה: "),
      el("b", "", sess.secret ?? ""),
      el("span", "", state.mode === "daily" ? " · חידה חדשה בחצות" : ""),
    );
    const more = el("button", "ms-2 underline", "לתוצאה");
    more.addEventListener("click", showResult);
    banner.append(more);
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

function render() {
  renderHeader();
  renderGuesses();
  renderControls();
}

// --- countdown ---------------------------------------------------------------

let resetAt = null;
function tickCountdown() {
  const c = $("countdown");
  if (state.mode !== "daily" || !resetAt) {
    c.textContent = "";
    return;
  }
  const left = resetAt - Date.now();
  if (left <= 0) {
    c.textContent = "יש חידה חדשה!";
    resetAt = null;
    loadDaily();
    return;
  }
  c.textContent = `חידה חדשה בעוד ${formatDuration(left)}`;
}
setInterval(tickCountdown, 1000);

// --- game loading ------------------------------------------------------------

async function loadDailyInfo() {
  state.daily = await api("/daily-info");
  resetAt = Date.now() + state.daily.seconds_to_reset * 1000;
}

async function loadDaily() {
  await loadDailyInfo();
  const cached = LS.get(`daily:${state.daily.puzzle_number}`);
  if (cached && state.mode === "daily") {
    state.session = cached;
    state.latestSeq = cached.latestSeq ?? null;
    render();
  }
  const sess = await api("/daily/session", { method: "POST" });
  if (state.mode !== "daily") return;
  state.session = sess;
  if (state.latestSeq == null && sess.guesses.length) state.latestSeq = sess.guesses.at(-1).seq;
  if (sess.solved || sess.gave_up) recordDailyResult(sess);
  saveSession();
  render();
}

async function loadFree({ fresh = false } = {}) {
  const cached = LS.get("free:current");
  let sess = null;
  if (cached && !fresh) {
    try {
      sess = await api(`/session/${encodeURIComponent(cached.session_id)}`);
      state.latestSeq = cached.latestSeq ?? null;
    } catch (e) {
      if (e.status !== 404) throw e;
    }
  }
  if (!sess) {
    sess = await api("/free/new", { method: "POST" });
    state.latestSeq = null;
  }
  if (state.mode !== "free") return;
  state.session = sess;
  saveSession();
  render();
}

async function switchMode(mode) {
  state.mode = mode;
  LS.set("mode", mode);
  state.session = null;
  state.latestSeq = null;
  setMessage("");
  render();
  tickCountdown();
  try {
    if (mode === "daily") await loadDaily();
    else await loadFree();
  } catch (e) {
    setMessage(e.message, "error");
  }
}

// --- actions -----------------------------------------------------------------

async function withBusy(fn) {
  if (state.busy) return;
  state.busy = true;
  renderControls();
  try {
    await fn();
  } catch (e) {
    setMessage(e.message, "error");
  } finally {
    state.busy = false;
    renderControls();
  }
}

function applyGuess(r) {
  const sess = state.session;
  sess.session_id = r.session_id;
  sess.guesses.push({ seq: r.seq, word: r.word, similarity: r.similarity, rank: r.rank, is_hint: r.is_hint });
  sess.guess_count = r.guess_count;
  state.latestSeq = r.seq;
  if (r.solved) {
    sess.solved = true;
    sess.secret = r.secret;
    sess.duration_ms = r.duration_ms;
    sess.leaderboard_eligible = sess.mode === "daily" && !sess.used_hint && !sess.submitted;
  }
}

async function submitGuess(word) {
  await withBusy(async () => {
    const r = await api("/guess", {
      method: "POST",
      body: { mode: state.mode, session_id: state.session?.session_id ?? null, word },
    });
    if (!r.valid) {
      if (r.error === "duplicate" && r.seq) state.latestSeq = r.seq;
      setMessage(r.message, "error");
      renderGuesses();
      return;
    }
    applyGuess(r);
    $("guess-input").value = "";
    // the server may have stripped niqqud or a prefix (והבית → בית)
    setMessage(r.word !== r.input.trim() ? `נספר כ„${r.word}”.` : "", "info");
    if (r.solved) {
      setMessage("🎉 מצאתם את המילה!", "ok");
      if (state.mode === "daily") recordDailyResult(state.session);
    }
    saveSession();
    renderGuesses();
    if (r.solved) {
      render();
      showResult();
    }
  });
}

async function requestHint() {
  if (state.mode === "daily" && !state.session?.used_hint) {
    if (!confirm("שימוש ברמז יוציא את הפתרון שלכם מטבלת המובילים של היום. להמשיך?")) return;
  }
  await withBusy(async () => {
    const r = await api(`/hint?session_id=${encodeURIComponent(state.session.session_id)}`);
    state.session.used_hint = true;
    state.session.leaderboard_eligible = false;
    applyGuess(r);
    setMessage(`💡 רמז: „${r.word}” (${r.rank}/1000)`, "info");
    saveSession();
    renderGuesses();
  });
}

async function giveUp() {
  if (!confirm("לוותר ולחשוף את המילה?")) return;
  await withBusy(async () => {
    const r = await api("/giveup", { method: "POST", body: { session_id: state.session.session_id } });
    Object.assign(state.session, { gave_up: true, secret: r.secret, leaderboard_eligible: false });
    if (state.mode === "daily") recordDailyResult(state.session);
    saveSession();
    render();
    showResult();
  });
}

// --- result dialog -----------------------------------------------------------

function showResult() {
  const sess = state.session;
  if (!sess || !(sess.solved || sess.gave_up)) return;
  $("result-title").textContent = sess.solved ? "🎉 כל הכבוד!" : "אולי בפעם הבאה";
  $("result-word").textContent = sess.secret ?? "";
  $("result-guesses").textContent = String(sess.guess_count);
  $("result-time").textContent = sess.solved ? formatDuration(sess.duration_ms) : "—";
  let note = "";
  if (sess.mode === "daily") {
    if (sess.gave_up) note = "ויתור לא נכנס לטבלת המובילים.";
    else if (sess.used_hint) note = "💡 נפתר בעזרת רמז — לא נכנס לטבלת המובילים.";
    else if (sess.submitted) note = "התוצאה שלכם כבר בטבלה.";
  } else {
    note = "משחק חופשי לא נכנס לטבלת המובילים.";
  }
  $("result-note").textContent = note;
  const form = $("name-form");
  form.classList.toggle("hidden", !(sess.mode === "daily" && sess.leaderboard_eligible));
  $("name-input").value = LS.get("name", "");
  $("name-error").textContent = "";
  $("result-leaderboard-btn").classList.toggle("hidden", sess.mode !== "daily");
  $("result-dialog").showModal();
}

function shareText() {
  const sess = state.session;
  const lines = [];
  const header = sess.mode === "daily" ? `וורדי #${sess.puzzle_number}` : "וורדי (משחק חופשי)";
  if (sess.solved) {
    lines.push(`${header} 🧩 פתרתי ב־${sess.guess_count} ניחושים ⏱️ ${formatDuration(sess.duration_ms)}${sess.used_hint ? " 💡" : ""}`);
  } else {
    lines.push(`${header} 🏳️ ויתרתי אחרי ${sess.guess_count} ניחושים`);
  }
  const ordered = [...sess.guesses].filter((g) => !g.is_hint).sort((a, b) => a.seq - b.seq);
  if (ordered.length) lines.push(`ניחוש ראשון: קרבה ${fmtSim(ordered[0].similarity)}`);
  const firstIn = (min) => ordered.find((g) => g.rank != null && g.rank > 1000 - min);
  const t1000 = firstIn(1000);
  const t10 = firstIn(10);
  if (t1000) lines.push(`כניסה ראשונה ל־1000 הקרובות: ניחוש ${t1000.seq}`);
  if (t10) lines.push(`כניסה ראשונה ל־10 הקרובות: ניחוש ${t10.seq}`);
  lines.push(location.origin);
  return lines.join("\n");
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  // fallback for plain-HTTP pages, where the Clipboard API is unavailable
  const ta = el("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:0;opacity:0";
  $("result-dialog").append(ta);
  ta.select();
  ta.setSelectionRange(0, text.length); // iOS ignores select() alone
  const ok = document.execCommand("copy");
  ta.remove();
  return ok ? Promise.resolve() : Promise.reject(new Error("copy failed"));
}

async function share() {
  const text = shareText();
  if (navigator.share && matchMedia("(pointer: coarse)").matches) {
    try {
      await navigator.share({ text });
      return;
    } catch (e) {
      if (e.name === "AbortError") return; // user closed the share sheet
    }
  }
  try {
    await copyText(text);
    $("share-btn").textContent = "הועתק ✓";
  } catch {
    $("share-btn").textContent = "ההעתקה נכשלה";
  }
  setTimeout(() => ($("share-btn").textContent = "שיתוף 📤"), 2000);
}

async function submitName(ev) {
  ev.preventDefault();
  const name = $("name-input").value.trim().replace(/\s+/g, " ");
  if (!/^[א-תA-Za-z0-9 ]{2,20}$/.test(name)) {
    $("name-error").textContent = "2–20 תווים: אותיות בעברית או באנגלית, ספרות ורווחים.";
    return;
  }
  try {
    const row = await api("/leaderboard", { method: "POST", body: { session_id: state.session.session_id, name } });
    LS.set("name", name);
    Object.assign(state.session, { submitted: true, leaderboard_eligible: false });
    saveSession();
    $("result-dialog").close();
    setMessage(`נרשמתם לטבלה במקום ${row.rank}! 🏆`, "ok");
    openLeaderboard("today");
  } catch (e) {
    $("name-error").textContent = e.message;
    if (e.code === "already_submitted") Object.assign(state.session, { submitted: true, leaderboard_eligible: false });
  }
}

// --- leaderboard -------------------------------------------------------------

async function openLeaderboard(scope = state.lbScope) {
  state.lbScope = scope;
  const dlg = $("leaderboard-dialog");
  if (!dlg.open) dlg.showModal();
  for (const tab of document.querySelectorAll(".lb-tab")) tab.setAttribute("aria-selected", String(tab.dataset.scope === scope));
  for (const b of document.querySelectorAll(".lb-sort")) b.setAttribute("aria-selected", String(b.dataset.sort === state.lbSort));
  $("lb-sort").classList.toggle("hidden", scope !== "alltime");
  $("lb-sort").classList.toggle("flex", scope === "alltime");
  $("lb-caption").textContent = "טוען…";
  $("lb-body").replaceChildren();
  try {
    const data = await api(`/leaderboard?scope=${scope}&sort=${state.lbSort}`);
    if (state.lbScope !== scope) return;
    renderLeaderboard(data);
  } catch (e) {
    $("lb-caption").textContent = e.message;
  }
}

function renderLeaderboard(data) {
  const wins = data.sort === "wins";
  const fastest = data.sort === "fastest";
  const cols = ["#", "שם", ...(wins ? ["ניצחונות", "ממוצע", "הכי מהיר"] : ["ניחושים", "זמן"]), ...(fastest ? ["חידה"] : [])];
  $("lb-head").replaceChildren(...cols.map((c, i) => el("th", `py-2 font-medium ${i === 1 ? "text-start" : "text-center"}`, c)));
  const cells = (r) => [
    String(r.rank),
    r.name,
    ...(wins ? [String(r.wins), String(r.avg_guesses), formatDuration(r.duration_ms)] : [String(r.guesses), formatDuration(r.duration_ms)]),
    ...(fastest ? [`#${r.puzzle_number}`] : []),
  ];
  const row = (r, extra = "") => {
    const tr = el("tr", `border-t border-slate-100 dark:border-slate-800 ${r.is_me ? "bg-amber-50 font-bold dark:bg-amber-950/40" : ""} ${extra}`);
    cells(r).forEach((text, i) => {
      const td = el("td", `py-2 tabular-nums ${i === 1 ? "truncate text-start" : "text-center"}`);
      td.textContent = i === 0 && r.rank <= 3 ? ["🥇", "🥈", "🥉"][r.rank - 1] : text;
      tr.append(td);
    });
    return tr;
  };
  const rows = data.rows.map((r) => row(r));
  if (data.me && !data.rows.some((r) => r.is_me)) rows.push(row(data.me, "border-t-4"));
  $("lb-body").replaceChildren(...rows);
  const caption =
    data.scope === "alltime"
      ? wins
        ? "דירוג לפי מספר הפתרונות בטבלה, ואז ממוצע ניחושים"
        : "הפתרונות המהירים ביותר בכל החידות"
      : `חידה #${data.puzzle_number} · ${data.total} פותרים · דירוג לפי ניחושים, ואז זמן`;
  $("lb-caption").textContent = data.rows.length ? caption : `${caption} — עדיין אין תוצאות`;
}

// --- yesterday ---------------------------------------------------------------

async function showYesterday() {
  try {
    const y = await api("/yesterday");
    $("yesterday-title").textContent = `המילה של חידה #${y.puzzle_number}`;
    $("yesterday-word").textContent = y.word;
    $("yesterday-list").replaceChildren(
      ...y.nearest.map((g) => {
        const li = el("li", "flex justify-between gap-2");
        const sim = el("bdi", "tabular-nums text-slate-500", fmtSim(g.similarity));
        sim.dir = "ltr";
        li.append(el("span", "", g.word), sim);
        return li;
      }),
    );
    $("yesterday-dialog").showModal();
  } catch (e) {
    setMessage(e.message, "error");
  }
}

// --- wiring ------------------------------------------------------------------

$("guess-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const word = $("guess-input").value.trim();
  if (!word) return;
  if (/\s/.test(word)) {
    setMessage("מילה אחת בכל פעם 🙂", "error");
    return;
  }
  submitGuess(word).then(() => $("guess-input").focus());
});
$("hint-btn").addEventListener("click", requestHint);
$("giveup-btn").addEventListener("click", giveUp);
$("new-game-btn").addEventListener("click", () => {
  const sess = state.session;
  if (sess && !sess.solved && !sess.gave_up && sess.guesses.length && !confirm("להתחיל משחק חדש? המשחק הנוכחי ייזנח.")) return;
  withBusy(async () => {
    setMessage("");
    await loadFree({ fresh: true });
  });
});
$("yesterday-btn").addEventListener("click", showYesterday);
$("share-btn").addEventListener("click", share);
$("name-form").addEventListener("submit", submitName);
$("open-leaderboard").addEventListener("click", () => openLeaderboard());
$("result-leaderboard-btn").addEventListener("click", () => {
  $("result-dialog").close();
  openLeaderboard("today");
});
for (const tab of document.querySelectorAll(".mode-tab")) {
  tab.addEventListener("click", () => tab.dataset.mode !== state.mode && switchMode(tab.dataset.mode));
}
for (const tab of document.querySelectorAll(".lb-tab")) tab.addEventListener("click", () => openLeaderboard(tab.dataset.scope));
for (const b of document.querySelectorAll(".lb-sort")) {
  b.addEventListener("click", () => {
    state.lbSort = b.dataset.sort;
    openLeaderboard("alltime");
  });
}
for (const b of document.querySelectorAll("[data-open]")) {
  b.addEventListener("click", () => {
    if (b.dataset.open === "stats-dialog") renderStats();
    $(b.dataset.open).showModal();
  });
}
// close dialogs when tapping the backdrop
for (const dlg of document.querySelectorAll("dialog")) {
  dlg.addEventListener("click", (ev) => ev.target === dlg && dlg.close());
}

(async function init() {
  render();
  try {
    if (state.mode === "free") {
      await loadDailyInfo();
      await loadFree();
    } else {
      await loadDaily();
    }
    tickCountdown();
    if (!LS.get("seen-help")) {
      LS.set("seen-help", true);
      $("help-dialog").showModal();
    }
  } catch (e) {
    setMessage(e.message, "error");
  }
})();
