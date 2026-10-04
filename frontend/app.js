/* 实验室玻璃器皿领用与破损登记系统 —— Vue 3 (global build) */
const { createApp, reactive, ref, computed, onMounted, watch, nextTick } = Vue;

const STATUS_NAMES = {
  available: "可借", lent: "借出中", to_check: "待检查", to_clean: "待清洗",
  washing: "清洗中", damaged: "破损", missing: "缺失", scrapped: "已核销",
};
const RETURN_NAMES = { intact: "完整", cracked: "裂纹", missing: "缺失", dirty: "待清洗" };
const ROLE_NAMES = { admin: "管理员", teacher: "任课老师", washer: "清洗质检员" };

async function api(path, opts = {}) {
  const token = localStorage.getItem("token");
  const res = await fetch("/api" + path, {
    headers: {
      ...(opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...(opts.headers || {}),
    },
    ...opts,
    body: opts.body instanceof FormData ? opts.body
      : opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  const txt = await res.text();
  if (txt) { try { data = JSON.parse(txt); } catch { data = { detail: txt }; } }
  if (!res.ok) {
    let msg = data?.detail || `请求失败 (${res.status})`;
    if (Array.isArray(msg)) msg = msg.map(e => e.msg).join("；");
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

const fmt = (d) => d ? new Date(d).toLocaleString("zh-CN", { hour12: false }) : "";

createApp({
  setup() {
    const st = reactive({
      user: null,
      tab: "dashboard",
      loading: false,
      toast: null,
      // 库存
      items: [], itemQuery: { code: "", status: "", location: "" },
      itemDetail: null, itemHistory: [], itemModal: null,
      // 课程/领用
      courses: [], loans: [], loanDetail: null, loanModal: null,
      newLoan: { course_id: "", group_id: "", codes: "", note: "" },
      retForm: { code: "", status: "intact", note: "" },
      // 清洗
      washQueue: { to_check: [], to_clean: [], washing: [] },
      pollTimer: null,
      inspectNote: "",
      // 破损
      damages: [], dmgModal: null, dmgForm: { note: "", photo: null },
      reviewForm: { note: "", approve: true },
      // 盘点
      stocktakes: [], stockDetail: null, stockModal: null,
      stScan: "", newStockName: "",
      resolveTarget: null, resolveForm: { resolution: "", report_loss: false },
      // 统计
      stats: null,
    });

    let toastTimer = null;
    function showToast(msg, kind = "ok") {
      st.toast = { msg, kind };
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => (st.toast = null), 4200);
    }

    // ---------- 登录 ----------
    async function login(username) {
      const r = await api("/auth/login", { method: "POST", body: { username } });
      localStorage.setItem("token", r.token);
      st.user = r.user;
      st.tab = "dashboard";
      await loadAll();
    }
    function logout() {
      localStorage.removeItem("token");
      location.reload();
    }
    async function restore() {
      if (!localStorage.getItem("token")) return;
      try {
        st.user = await api("/me");
        st.tab = "dashboard";
        await loadAll();
      } catch { localStorage.removeItem("token"); }
    }

    const can = {
      teacher: () => st.user && (st.user.role === "teacher" || st.user.role === "admin"),
      washer: () => st.user && (st.user.role === "washer" || st.user.role === "admin"),
      admin: () => st.user?.role === "admin",
    };

    const tabs = computed(() => {
      if (!st.user) return [];
      const r = st.user.role;
      const base = [
        { k: "dashboard", t: "工作台" },
        { k: "inventory", t: "柜位查询" },
      ];
      if (r === "teacher" || r === "admin") base.push({ k: "loans", t: "领用归还" });
      if (r === "washer" || r === "admin") base.push({ k: "cleaning", t: "检查清洗" });
      base.push({ k: "damages", t: "破损免赔" });
      if (r === "admin") base.push({ k: "stocktake", t: "盘点" });
      return base;
    });

    async function loadAll() {
      await Promise.allSettled([
        loadStats(), loadItems(), loadCourses(), loadLoans(),
        loadDamages(), loadStocktakes(),
      ]);
    }

    async function switchTab(k) {
      st.tab = k;
      try {
        if (k === "dashboard") await loadStats();
        if (k === "inventory") await loadItems();
        if (k === "loans") { await Promise.all([loadCourses(), loadLoans()]); }
        if (k === "cleaning") await loadWashQueue();
        if (k === "damages") await loadDamages();
        if (k === "stocktake") await loadStocktakes();
      } catch (e) { showToast(e.message, "err"); }
    }

    // ---------- 工作台 ----------
    async function loadStats() { st.stats = await api("/stats"); }

    // ---------- 柜位 / 库存 ----------
    async function loadItems() {
      const q = new URLSearchParams();
      if (st.itemQuery.code) q.set("code", st.itemQuery.code);
      if (st.itemQuery.status) q.set("status", st.itemQuery.status);
      if (st.itemQuery.location) q.set("location", st.itemQuery.location);
      st.items = await api("/items?" + q.toString());
    }
    async function openItem(code) {
      st.itemDetail = await api("/items/" + encodeURIComponent(code));
      st.itemHistory = await api(`/items/${encodeURIComponent(code)}/history`);
      st.itemModal = true;
    }
    function kitCompRows() { return st.itemDetail?.components || []; }

    // ---------- 课程 / 领用 ----------
    async function loadCourses() {
      try { st.courses = await api("/courses"); } catch { st.courses = []; }
    }
    async function loadLoans() {
      try { st.loans = await api("/loans"); } catch { st.loans = []; }
    }
    const courseGroups = computed(() => {
      const c = st.courses.find(x => x.id === Number(st.newLoan.course_id));
      return c?.groups || [];
    });
    async function submitLoan() {
      const codes = [...new Set(st.newLoan.codes.split(/[\s,，;；\n]+/).map(s => s.trim()).filter(Boolean))];
      if (!st.newLoan.course_id || !st.newLoan.group_id)
        return showToast("请选择课程与学生组", "err");
      if (!codes.length) return showToast("请扫入至少一个器皿编号", "err");
      try {
        const loan = await api("/loans", {
          method: "POST",
          body: { course_id: Number(st.newLoan.course_id), group_id: Number(st.newLoan.group_id),
                  item_codes: codes, note: st.newLoan.note },
        });
        showToast(`领用单 #${loan.id} 已配发：${loan.course_name} ${loan.group_name}（套件已自动带出全部部件）`);
        st.newLoan.codes = ""; st.newLoan.note = "";
        await loadLoans(); await loadItems(); await loadStats();
        await openLoan(loan.id);
      } catch (e) { showToast(e.message, "err"); }
    }
    async function openLoan(id) {
      st.loanDetail = await api("/loans/" + id);
      st.loanModal = true;
      st.retForm = { code: "", status: "intact", note: "" };
    }
    async function submitReturn() {
      if (!st.retForm.code.trim()) return showToast("请扫码或输入器皿编号", "err");
      try {
        const r = await api(`/loans/${st.loanDetail.loan.id}/return`, {
          method: "POST",
          body: { item_code: st.retForm.code.trim(),
                  return_status: st.retForm.status, note: st.retForm.note },
        });
        showToast(`${r.line.item_code} 归还登记成功：${RETURN_NAMES[r.line.return_status]} → ${r.item_status_name}`
          + (r.kit_warning ? `；⚠ ${r.kit_warning}` : ""), r.kit_warning ? "warn" : "ok");
        st.retForm.code = ""; st.retForm.note = "";
        st.loanDetail = await api("/loans/" + st.loanDetail.loan.id);
        await Promise.all([loadItems(), loadStats(), loadDamages()]);
      } catch (e) { showToast(e.message, e.status === 409 ? "warn" : "err"); }
    }
    async function finishLoan() {
      try {
        const r = await api(`/loans/${st.loanDetail.loan.id}/finish`, { method: "POST" });
        showToast(`领用单 #${r.id} 已结清（${r.status === "issue" ? "含破损/缺失，转破损处理" : "全部完好"}）`);
        st.loanDetail = await api("/loans/" + r.id);
        await Promise.all([loadLoans(), loadStats()]);
      } catch (e) { showToast(e.message, "err"); }
    }

    // ---------- 检查 / 清洗 ----------
    async function loadWashQueue() {
      st.washQueue = await api("/cleaning/queue");
    }
    async function inspect(code, passed) {
      try {
        const r = await api("/inspect", {
          method: "POST",
          body: { item_code: code, passed, note: passed ? "" : (st.inspectNote || "目检发现裂纹") },
        });
        if (passed) showToast(`${code} 目检合格，转入待清洗`);
        else showToast(`${code} 目检发现裂纹，已登记破损并追溯上一节课（领用单 #${r.traced_loan_id ?? "无"}）`, "warn");
        st.inspectNote = "";
        await Promise.all([loadWashQueue(), loadDamages(), loadStats()]);
      } catch (e) { showToast(e.message, "err"); }
    }
    async function startWash(code) {
      try {
        const r = await api("/cleaning/start", { method: "POST", body: { item_code: code } });
        showToast(`已送入清洗设备，任务号 ${r.device_job.job_id}（设备处理约需 6 秒）`);
        await loadWashQueue();
      } catch (e) { showToast(e.message, "err"); }
    }
    async function completeWash(jobId, result) {
      try {
        const r = await api("/cleaning/complete", {
          method: "POST",
          body: { device_job_id: jobId, result,
                  note: result === "fail" ? "清洗后目检发现瓶口裂纹" : "" },
        });
        if (result === "pass") showToast(`${r.item_code} 清洗合格，回到可借库存`);
        else showToast(`${r.item_code} 清洗后才发现破损，已追溯上一节课：${r.traced_course}`, "warn");
        await Promise.all([loadWashQueue(), loadItems(), loadDamages(), loadStats()]);
      } catch (e) { showToast(e.message, e.status === 409 ? "warn" : "err"); }
    }
    function startPoll() {
      clearInterval(st.pollTimer);
      st.pollTimer = setInterval(() => {
        if (st.tab === "cleaning" && st.user && st.washQueue.washing.length) loadWashQueue();
      }, 4000);
    }

    // ---------- 破损 / 免赔 ----------
    async function loadDamages() {
      try { st.damages = await api("/damages"); } catch { st.damages = []; }
    }
    function openDmg(d) {
      st.dmgModal = d;
      st.dmgForm = { note: "", photo: null };
      st.reviewForm = { note: "", approve: true };
    }
    async function requestWaiver() {
      try {
        const r = await api(`/damages/${st.dmgModal.id}/waiver/request`, {
          method: "POST", body: { note: st.dmgForm.note },
        });
        showToast(`已提交免赔申请，等待非本节任课老师/管理员审核`);
        st.dmgModal = r;
        await loadDamages(); await loadStats();
      } catch (e) { showToast(e.message, "err"); }
    }
    async function reviewWaiver() {
      try {
        const r = await api(`/damages/${st.dmgModal.id}/waiver/review`, {
          method: "POST", body: st.reviewForm,
        });
        showToast(`审核完成：${st.reviewForm.approve ? "批准免赔" : "不予免赔"}`);
        st.dmgModal = r;
        await Promise.all([loadDamages(), loadStats()]);
      } catch (e) { showToast(e.message, "err"); }
    }
    function onPhoto(e) { st.dmgForm.photo = e.target.files[0] || null; }
    async function uploadPhoto() {
      if (!st.dmgForm.photo) return showToast("请先选择照片文件", "err");
      const fd = new FormData();
      fd.append("file", st.dmgForm.photo);
      try {
        const r = await api(`/damages/${st.dmgModal.id}/photo`, { method: "POST", body: fd });
        showToast("照片已存本地：" + r.photo_path);
        st.dmgModal = { ...st.dmgModal, photo_path: r.photo_path };
        await loadDamages();
      } catch (e) { showToast(e.message, "err"); }
    }
    async function scrapItem(code) {
      if (!confirm(`确认核销 ${code}？核销不影响其领用/归还记录。`)) return;
      try {
        await api(`/items/${encodeURIComponent(code)}/scrap`, { method: "POST" });
        showToast(`${code} 已核销，历史领用记录保留`);
        await Promise.all([loadItems(), loadDamages(), loadStats()]);
      } catch (e) { showToast(e.message, "err"); }
    }

    // ---------- 盘点 ----------
    async function loadStocktakes() {
      try { st.stocktakes = await api("/stocktakes"); } catch { st.stocktakes = []; }
    }
    async function createStock() {
      if (!st.newStockName.trim()) return showToast("请填写盘点单名称", "err");
      try {
        const r = await api("/stocktakes", {
          method: "POST", body: { name: st.newStockName.trim() },
        });
        st.newStockName = "";
        await loadStocktakes();
        showStock(r);
        showToast("盘点单已建立，系统台账数量与状态已冻结为快照");
      } catch (e) { showToast(e.message, "err"); }
    }
    async function showStock(r) {
      st.stockDetail = r?.id ? await api("/stocktakes/" + r.id) : r;
      st.stockModal = true;
      st.stScan = "";
    }
    async function openStock(id) { await showStock(await api("/stocktakes/" + id)); }
    async function refreshStock() {
      if (st.stockDetail) st.stockDetail = await api("/stocktakes/" + st.stockDetail.stocktake.id);
    }
    async function stockScan(counted = true) {
      if (!st.stScan.trim()) return;
      try {
        const r = await api(`/stocktakes/${st.stockDetail.stocktake.id}/count`, {
          method: "POST", body: { item_code: st.stScan.trim(), counted },
        });
        if (r.surplus) showToast(r.message, "warn");
        else showToast(`${r.line.item_code} 已盘点：账实相符`);
        st.stScan = "";
        await refreshStock();
      } catch (e) { showToast(e.message, "err"); }
    }
    function openResolve(line) {
      st.resolveTarget = line;
      st.resolveForm = { resolution: line.resolution || "", report_loss: false };
    }
    async function submitResolve() {
      if (!st.resolveForm.resolution.trim()) return showToast("请填写差异查明说明", "err");
      try {
        await api(`/stocktake-lines/${st.resolveTarget.id}/resolve`, {
          method: "POST", body: st.resolveForm,
        });
        showToast("差异说明已保存" + (st.resolveForm.report_loss
          ? "，已登记缺失并追溯上一节课；领用记录保持原样未改" : "；领用记录保持原样未改"));
        st.resolveTarget = null;
        await Promise.all([refreshStock(), loadDamages(), loadItems(), loadStats()]);
      } catch (e) { showToast(e.message, "err"); }
    }
    async function closeStock() {
      if (!confirm("关闭后未点到的实物保留为盘亏差异，不会冲改任何领用记录。确认关闭？")) return;
      try {
        await api(`/stocktakes/${st.stockDetail.stocktake.id}/close`, { method: "POST" });
        showToast("盘点单已关闭，差异保留备查");
        await refreshStock(); await loadStocktakes();
      } catch (e) { showToast(e.message, "err"); }
    }

    onMounted(async () => {
      await restore();
      startPoll();
    });

    return {
      st, STATUS_NAMES, RETURN_NAMES, ROLE_NAMES, fmt, can, tabs,
      login, logout, switchTab,
      loadItems, openItem, kitCompRows,
      courseGroups, submitLoan, openLoan, submitReturn, finishLoan,
      loadWashQueue, inspect, startWash, completeWash,
      loadDamages, openDmg, requestWaiver, reviewWaiver, onPhoto, uploadPhoto, scrapItem,
      createStock, openStock, showStock, stockScan, openResolve,
      submitResolve, closeStock,
    };
  },

  template: `
  <div v-if="!st.user" class="login-wrap">
    <div class="login-card">
      <h1>🧪 玻璃器皿领用与破损登记</h1>
      <div class="sub">中学实验室管理系统 · 请选择岗位身份登录（演示免密）</div>
      <button class="role-btn" @click="login('admin')">
        <span><span class="rn">周敏</span><div class="rd">账号 admin</div></span>
        <span class="role-tag">管理员</span>
      </button>
      <button class="role-btn" @click="login('wang')">
        <span><span class="rn">王磊</span><div class="rd">账号 wang · 初二(3)班《水的蒸馏》任课</div></span>
        <span class="role-tag">任课老师</span>
      </button>
      <button class="role-btn" @click="login('zhao')">
        <span><span class="rn">赵静</span><div class="rd">账号 zhao · 非本节任课老师，可审核免赔</div></span>
        <span class="role-tag">任课老师</span>
      </button>
      <button class="role-btn" @click="login('sun')">
        <span><span class="rn">孙师傅</span><div class="rd">账号 sun · 清洗质检员</div></span>
        <span class="role-tag">清洗质检</span>
      </button>
    </div>
  </div>

  <template v-else>
  <div class="topbar">
    <span class="brand">🧪 玻璃器皿管理</span>
    <nav>
      <button v-for="t in tabs" :key="t.k" :class="{active: st.tab===t.k}" @click="switchTab(t.k)">{{t.t}}</button>
    </nav>
    <span class="who"><b>{{st.user.name}}</b><span :class="'pill-role r-'+st.user.role">{{ROLE_NAMES[st.user.role]}}</span></span>
    <button class="logout" @click="logout">退出</button>
  </div>

  <div v-if="st.toast" :class="'alert ' + (st.toast.kind||'ok')" style="margin:12px 20px 0;max-width:1240px;margin-left:auto;margin-right:auto">
    {{st.toast.msg}}
  </div>

  <div class="page">

    <!-- ========== 工作台 ========== -->
    <template v-if="st.tab==='dashboard'">
      <div class="card">
        <h2>库存实物状态</h2>
        <div class="stat-grid" v-if="st.stats">
          <div class="stat" v-for="(n,k) in st.stats.status_counts" :key="k">
            <div class="n">{{n}}</div><div class="l">{{STATUS_NAMES[k]}}</div>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>待办</h2>
        <div class="stat-grid" v-if="st.stats">
          <div class="stat"><div class="n">{{st.stats.active_loans}}</div><div class="l">进行中的领用单</div></div>
          <div class="stat"><div class="n">{{st.stats.pending_waivers}}</div><div class="l">待审核免赔申请</div></div>
          <div class="stat"><div class="n">{{st.stats.open_loss_lines}}</div><div class="l">盘点盘亏待查明</div></div>
        </div>
        <div class="alert info" style="margin-top:14px">
          业务规则：同一件器皿不能借给两个组；归还逐件扫码、重复扫码只记一次；套件按部件逐件核对，缺件明确提示；
          检查与清洗合格后才回可借库存；清洗后发现破损仍追溯上一节课；免赔由非本节任课老师或管理员审核；
          盘点差异保留，不回改领用记录。
        </div>
      </div>
    </template>

    <!-- ========== 柜位查询 ========== -->
    <template v-if="st.tab==='inventory'">
      <div class="card">
        <h2>柜位 / 实物查询</h2>
        <div class="row">
          <div class="grow"><label>实物编号</label><input v-model="st.itemQuery.code" placeholder="如 DST-01-T" @keyup.enter="loadItems"></div>
          <div><label>状态</label>
            <select v-model="st.itemQuery.status" @change="loadItems">
              <option value="">全部</option>
              <option v-for="(n,k) in STATUS_NAMES" :key="k" :value="k">{{n}}</option>
            </select>
          </div>
          <div class="grow"><label>柜位</label><input v-model="st.itemQuery.location" placeholder="如 A柜-1层" @keyup.enter="loadItems"></div>
          <button class="btn" @click="loadItems">查询</button>
        </div>
      </div>
      <div class="card">
        <table>
          <thead><tr><th>编号</th><th>品种 / 规格</th><th>柜位</th><th>状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="i in st.items" :key="i.id">
              <td class="code">{{i.code}}</td>
              <td>{{i.template_name}} <span class="muted">{{i.spec}}</span>
                  <span v-if="i.is_kit" class="badge b-surplus">套件</span></td>
              <td>{{i.location}}</td>
              <td><span :class="'badge b-'+i.status">{{STATUS_NAMES[i.status]}}</span></td>
              <td><button class="btn sec sm" @click="openItem(i.code)">查实物 / 履历</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!st.items.length" class="no-data">没有符合条件的实物</div>
      </div>
    </template>

    <!-- ========== 领用归还 ========== -->
    <template v-if="st.tab==='loans'">
      <div class="card" v-if="can.teacher()">
        <h2>按课程给学生组配发器皿</h2>
        <div class="row">
          <div class="grow"><label>课程</label>
            <select v-model="st.newLoan.course_id">
              <option value="" disabled>请选择课程</option>
              <option v-for="c in st.courses" :key="c.id" :value="c.id">
                {{c.name}} · {{c.class_name}} · {{c.lesson_at}}（{{c.teacher_name}}）
              </option>
            </select>
          </div>
          <div><label>学生组</label>
            <select v-model="st.newLoan.group_id">
              <option value="" disabled>请选择组</option>
              <option v-for="g in courseGroups" :key="g.id" :value="g.id">{{g.name}}</option>
            </select>
          </div>
        </div>
        <h3>扫码配发（每行/空格一个编号；扫套件任一部件自动带出整套）</h3>
        <textarea v-model="st.newLoan.codes" rows="2" style="width:100%" class="scan-input"
          placeholder="例如：DST-01&#10;BK-250-001"></textarea>
        <div class="row" style="margin-top:10px">
          <div class="grow"><label>备注</label><input v-model="st.newLoan.note"></div>
          <button class="btn" @click="submitLoan">确认配发</button>
        </div>
      </div>

      <div class="card">
        <h2>领用单（实验结束逐件核对归还）</h2>
        <table>
          <thead><tr><th>#</th><th>课程</th><th>班级/节次</th><th>学生组</th><th>任课老师</th><th>配发时间</th><th>状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="l in st.loans" :key="l.id">
              <td>#{{l.id}}</td><td>{{l.course_name}}</td><td>{{l.class_name}} {{l.lesson_at}}</td>
              <td>{{l.group_name}}</td><td>{{l.teacher_name}}</td><td>{{fmt(l.lent_at)}}</td>
              <td>
                <span v-if="l.status==='active'" class="badge b-lent">核对中</span>
                <span v-else-if="l.status==='done'" class="badge b-approved">已结清</span>
                <span v-else class="badge b-cracked">有破损/缺失</span>
              </td>
              <td><button class="btn sec sm" @click="openLoan(l.id)">逐件归还</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!st.loans.length" class="no-data">暂无领用单</div>
      </div>
    </template>

    <!-- ========== 检查清洗 ========== -->
    <template v-if="st.tab==='cleaning'">
      <div class="alert info">模拟清洗设备：送入后约 6 秒完成程序；设备结束后由质检员判定合格/破损。页面每 4 秒自动刷新队列。</div>
      <div class="card">
        <h2>① 归还完整 · 待目检（{{st.washQueue.to_check.length}}）</h2>
        <table>
          <thead><tr><th>编号</th><th>柜位</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="i in st.washQueue.to_check" :key="i.id">
              <td class="code">{{i.code}}</td><td>{{i.location}}</td>
              <td>
                <input v-model="st.inspectNote" placeholder="裂纹描述（发现问题时填写）" style="width:240px">
                <button class="btn sm" style="margin-left:8px" @click="inspect(i.code,true)">目检合格 → 待清洗</button>
                <button class="btn warn sm" @click="inspect(i.code,false)">发现裂纹 → 登记破损</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!st.washQueue.to_check.length" class="no-data">暂无待检查件</div>
      </div>
      <div class="card">
        <h2>② 待清洗（{{st.washQueue.to_clean.length}}）</h2>
        <table>
          <thead><tr><th>编号</th><th>柜位</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="i in st.washQueue.to_clean" :key="i.id">
              <td class="code">{{i.code}}</td><td>{{i.location}}</td>
              <td><button class="btn sm" @click="startWash(i.code)">送入清洗设备</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!st.washQueue.to_clean.length" class="no-data">暂无待清洗件</div>
      </div>
      <div class="card">
        <h2>③ 设备处理中 / 待判定（{{st.washQueue.washing.length}}）</h2>
        <table>
          <thead><tr><th>编号</th><th>柜位</th><th>设备任务</th><th>合格判定（检查+清洗合格才回库）</th></tr></thead>
          <tbody>
            <tr v-for="i in st.washQueue.washing" :key="i.id">
              <td class="code">{{i.code}}</td><td>{{i.location}}</td>
              <td>
                <span class="code">{{i.device_job_id}}</span>
                <span v-if="!i.device_ready" class="badge b-to_clean">设备程序进行中…</span>
                <span v-else class="badge b-intact">设备已完成，待目检判定</span>
              </td>
              <td>
                <button class="btn sm" :disabled="!i.device_ready"
                  @click="completeWash(i.device_job_id,'pass')">清洗合格 → 回可借库存</button>
                <button class="btn warn sm" :disabled="!i.device_ready"
                  @click="completeWash(i.device_job_id,'fail')">清洗后发现破损</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!st.washQueue.washing.length" class="no-data">暂无清洗中件</div>
      </div>
    </template>

    <!-- ========== 破损免赔 ========== -->
    <template v-if="st.tab==='damages'">
      <div class="card">
        <h2>破损 / 缺失登记与免赔审核</h2>
        <table>
          <thead><tr><th>#</th><th>器皿编号</th><th>类型</th><th>发现环节</th><th>追溯课程 / 组</th><th>登记人</th><th>时间</th><th>免赔</th><th></th></tr></thead>
          <tbody>
            <tr v-for="d in st.damages" :key="d.id">
              <td>{{d.id}}</td><td class="code">{{d.item_code}}</td>
              <td><span :class="'badge b-'+(d.damage_type==='missing'?'missing':'cracked')">
                {{d.damage_type==='missing'?'缺失':'裂纹/破损'}}</span></td>
              <td>{{ {return:'归还时',cleaning:'清洗后',inspection:'目检',stocktake:'盘点'}[d.source] }}</td>
              <td>{{d.course_name? d.course_name+' · '+d.class_name+' '+d.lesson_at+' · '+d.group_name : '无在借课程'}}</td>
              <td>{{d.reporter_name}}</td><td>{{fmt(d.reported_at)}}</td>
              <td>
                <span v-if="d.waiver_status==='none'" class="badge b-none">未申请</span>
                <span v-else-if="d.waiver_status==='pending'" class="badge b-pending">待审核</span>
                <span v-else-if="d.waiver_status==='approved'" class="badge b-approved">已批准</span>
                <span v-else class="badge b-rejected">未批准</span>
                <div v-if="d.reviewer_name" class="muted">审核：{{d.reviewer_name}}</div>
              </td>
              <td><button class="btn sec sm" @click="openDmg(d)">处理</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!st.damages.length" class="no-data">暂无破损记录</div>
      </div>
    </template>

    <!-- ========== 盘点 ========== -->
    <template v-if="st.tab==='stocktake'">
      <div class="card">
        <h2>新建盘点单（冻结系统快照，差异保留不改账）</h2>
        <div class="row">
          <div class="grow"><input v-model="st.newStockName" placeholder="如 2026年10月期中盘点"></div>
          <button class="btn" @click="createStock">建立盘点</button>
        </div>
      </div>
      <div class="card">
        <h2>盘点单</h2>
        <table>
          <thead><tr><th>#</th><th>名称</th><th>建立时间</th><th>状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="s in st.stocktakes" :key="s.id">
              <td>#{{s.id}}</td><td>{{s.name}}</td><td>{{fmt(s.created_at)}}</td>
              <td><span :class="s.closed_at?'badge b-approved':'badge b-pending'">{{s.closed_at?'已关闭':'进行中'}}</span></td>
              <td><button class="btn sec sm" @click="openStock(s.id)">打开</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>

  <!-- ===== 实物详情 / 套件部件 / 履历 ===== -->
  <div v-if="st.itemModal" class="modal-mask" @click.self="st.itemModal=false">
    <div class="modal" style="width:720px">
      <h2>实物 {{st.itemDetail.item.code}}
        <span :class="'badge b-'+st.itemDetail.item.status">{{st.itemDetail.status_name}}</span>
      </h2>
      <div class="kv">
        <span class="k">品种</span><span>{{st.itemDetail.template_name}}（{{st.itemDetail.spec}}）</span>
        <span class="k">柜位</span><span class="code">{{st.itemDetail.item.location}}</span>
      </div>

      <div v-if="st.itemDetail.is_kit && !st.itemDetail.item.kit_id">
        <h3>套件部件逐件核对（应到 {{st.itemDetail.kit_expected}} 件，柜内在位 {{st.itemDetail.kit_present}} 件）</h3>
        <div :class="['kit-box', st.itemDetail.kit_complete?'ok':'']">
          <div class="kit-title">
            {{st.itemDetail.template_name}}（{{st.itemDetail.item.code}}）
            <span v-if="st.itemDetail.kit_complete" class="badge b-intact">部件齐全</span>
            <span v-else class="badge b-missing">⚠ 套件缺件，不能按整套数量认定齐全</span>
          </div>
          <div v-for="c in kitCompRows()" :key="c.code" class="kit-comp">
            <span class="code">{{c.code}}</span><span>{{c.name}} {{c.spec}}</span>
            <span class="muted">柜位 {{c.location}}</span>
            <span :class="'badge b-'+(c.in_cabinet?'available':c.status)">
              {{c.in_cabinet ? '在柜' : c.status_name}}
            </span>
          </div>
        </div>
      </div>

      <h3>使用 / 清洗 / 破损 / 盘点履历</h3>
      <div class="timeline">
        <div v-for="(e,idx) in st.itemHistory" :key="idx" :class="'tl-item '+e.kind">
          <div class="tl-at">{{fmt(e.at)}} · {{ {loan:'领用',return:'归还',cleaning:'清洗判定',cleaning_start:'送洗',damage:'破损/缺失',stocktake:'盘点'}[e.kind] }}{{e.operator? ' · '+e.operator : ''}}</div>
          <div>{{e.detail}}</div>
        </div>
      </div>
      <div v-if="!st.itemHistory.length" class="no-data">尚无履历</div>
      <div class="foot"><button class="btn sec" @click="st.itemModal=false">关闭</button></div>
    </div>
  </div>

  <!-- ===== 领用单 / 逐件归还 ===== -->
  <div v-if="st.loanModal" class="modal-mask" @click.self="st.loanModal=false">
    <div class="modal" style="width:820px">
      <h2>领用单 #{{st.loanDetail.loan.id}} · {{st.loanDetail.loan.course_name}} · {{st.loanDetail.loan.group_name}}</h2>
      <div class="kv">
        <span class="k">班级节次</span><span>{{st.loanDetail.loan.class_name}} {{st.loanDetail.loan.lesson_at}}</span>
        <span class="k">任课老师</span><span>{{st.loanDetail.loan.teacher_name}}</span>
        <span class="k">归还进度</span><span>{{st.loanDetail.returned_count}} / {{st.loanDetail.total_count}} 件（逐件核对，不以整套数量计）</span>
      </div>

      <h3 v-if="st.loanDetail.kit_groups.length">套件核对（缺件会明确提示）</h3>
      <div v-for="kg in st.loanDetail.kit_groups" :key="kg.parent_line_id"
           :class="['kit-box', kg.all_returned_good?'ok':'']">
        <div class="kit-title">
          <span class="code">{{kg.kit_code}}</span><span>{{kg.kit_name}}</span>
          <span v-if="kg.all_returned_good" class="badge b-intact">部件全部完好归还</span>
          <span v-else class="badge b-missing">⚠ {{kg.warning || '尚未还齐'}}</span>
        </div>
        <div v-for="c in kg.components" :key="c.line_id" class="kit-comp">
          <span class="code">{{c.item_code}}</span><span>{{c.name}}</span>
          <span :class="'badge b-'+(c.state==='unreturned'?'unreturned':c.state)">{{c.state_name}}</span>
        </div>
      </div>

      <h3>逐件扫码归还</h3>
      <div class="row">
        <div class="grow"><input v-model="st.retForm.code" class="scan-input" placeholder="扫码 / 输入器皿编号，回车登记"
          @keyup.enter="submitReturn" :disabled="st.loanDetail.loan.status!=='active'"></div>
        <div>
          <select v-model="st.retForm.status" :disabled="st.loanDetail.loan.status!=='active'">
            <option value="intact">完整</option><option value="dirty">待清洗</option>
            <option value="cracked">裂纹</option><option value="missing">缺失</option>
          </select>
        </div>
        <div class="grow"><input v-model="st.retForm.note" placeholder="备注（裂纹位置等）"
          :disabled="st.loanDetail.loan.status!=='active'"></div>
        <button class="btn" @click="submitReturn" :disabled="st.loanDetail.loan.status!=='active'">登记归还</button>
      </div>
      <div class="alert warn" v-if="st.loanDetail.loan.status==='active' && !st.loanDetail.all_lines_returned">
        仍有 {{st.loanDetail.total_count - st.loanDetail.returned_count}} 件未逐件核对；缺失部件须逐件登记为「缺失」，不能只按整套数量认定已还齐。
      </div>

      <h3>明细</h3>
      <table>
        <thead><tr><th>编号</th><th>品种</th><th>柜位</th><th>归还情况</th></tr></thead>
        <tbody>
          <tr v-for="l in st.loanDetail.lines" :key="l.id">
            <td class="code">{{l.item_code}}</td><td>{{l.template_name}}</td><td>{{l.location}}</td>
            <td>
              <span v-if="!l.return_status" class="badge b-unreturned">未还</span>
              <span v-else :class="'badge b-'+l.return_status">{{RETURN_NAMES[l.return_status]}}</span>
              <span v-if="l.return_note" class="muted"> {{l.return_note}}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="foot">
        <button class="btn sec" @click="st.loanModal=false">关闭</button>
        <button v-if="st.loanDetail.loan.status==='active'" class="btn warn" @click="finishLoan">
          实验结束核对完毕，结单
        </button>
      </div>
    </div>
  </div>

  <!-- ===== 破损处理 / 免赔 ===== -->
  <div v-if="st.dmgModal" class="modal-mask" @click.self="st.dmgModal=null">
    <div class="modal">
      <h2>破损/缺失记录 #{{st.dmgModal.id}} · <span class="code">{{st.dmgModal.item_code}}</span></h2>
      <div class="kv">
        <span class="k">品种</span><span>{{st.dmgModal.template_name}}</span>
        <span class="k">类型</span><span>{{st.dmgModal.damage_type==='missing'?'缺失':'裂纹/破损'}}</span>
        <span class="k">发现环节</span><span>{{ {return:'归还时',cleaning:'清洗后检查',inspection:'入库前目检',stocktake:'盘点'}[st.dmgModal.source] }}</span>
        <span class="k">责任追溯</span>
        <span>{{st.dmgModal.course_name ? st.dmgModal.course_name+' · '+st.dmgModal.class_name+' '+st.dmgModal.lesson_at+' · '+st.dmgModal.group_name : '无在借课程'}}</span>
        <span class="k">登记人</span><span>{{st.dmgModal.reporter_name}} · {{fmt(st.dmgModal.reported_at)}}</span>
        <span class="k">说明</span><span>{{st.dmgModal.description}}</span>
        <span class="k">免赔状态</span>
        <span>
          <span v-if="st.dmgModal.waiver_status==='none'" class="badge b-none">未申请</span>
          <span v-else-if="st.dmgModal.waiver_status==='pending'" class="badge b-pending">待审核</span>
          <span v-else-if="st.dmgModal.waiver_status==='approved'" class="badge b-approved">已批准</span>
          <span v-else class="badge b-rejected">未批准</span>
          <span v-if="st.dmgModal.waiver_note" class="muted" style="display:block">{{st.dmgModal.waiver_note}}</span>
        </span>
      </div>
      <img v-if="st.dmgModal.photo_path" :src="st.dmgModal.photo_path" class="photo-thumb">
      <h3>破损照片（存本地）</h3>
      <div class="row">
        <div class="grow"><input type="file" accept="image/*" @change="onPhoto"></div>
        <button class="btn sec sm" @click="uploadPhoto">上传照片</button>
      </div>

      <template v-if="st.dmgModal.waiver_status==='none' || st.dmgModal.waiver_status==='rejected'">
        <h3>提出免赔申请（任课老师/管理员）</h3>
        <textarea v-model="st.dmgForm.note" rows="2" style="width:100%" placeholder="申请理由，如：老化裂纹，非本组操作不当"></textarea>
        <button class="btn sec" style="margin-top:8px" @click="requestWaiver">提交免赔申请</button>
        <div class="alert info" style="margin-top:8px">提交后须由<b>非本节任课老师</b>或管理员审核；本节任课老师不能自行免赔。</div>
      </template>

      <template v-if="st.dmgModal.waiver_status==='pending'">
        <h3>免赔审核（非本节任课老师 / 管理员）</h3>
        <textarea v-model="st.reviewForm.note" rows="2" style="width:100%" placeholder="审核意见"></textarea>
        <div class="row" style="margin-top:8px">
          <button class="btn" @click="st.reviewForm.approve=true; reviewWaiver()">批准免赔</button>
          <button class="btn warn" @click="st.reviewForm.approve=false; reviewWaiver()">不予免赔</button>
        </div>
        <div v-if="st.user.role==='teacher' && st.dmgModal.course_teacher_id===st.user.id"
             class="alert err">您是本节课任课老师，系统将拒绝您自行审核免赔。</div>
      </template>

      <div class="foot">
        <button v-if="can.admin()" class="btn gray sm" @click="scrapItem(st.dmgModal.item_code)">管理员核销实物（保留历史）</button>
        <button class="btn sec" @click="st.dmgModal=null">关闭</button>
      </div>
    </div>
  </div>

  <!-- ===== 盘点详情 ===== -->
  <div v-if="st.stockModal" class="modal-mask" @click.self="st.stockModal=null">
    <div class="modal" style="width:880px">
      <h2>盘点单 #{{st.stockDetail.stocktake.id}} · {{st.stockDetail.stocktake.name}}</h2>
      <div class="kv">
        <span class="k">快照数量</span><span>{{st.stockDetail.summary.total}} 件（建立盘点时冻结）</span>
        <span class="k">已盘到</span><span>{{st.stockDetail.summary.counted}} 件</span>
        <span class="k">盘亏差异</span><span style="color:#c0392b;font-weight:600">{{st.stockDetail.summary.loss}} 件（保留，不改领用记录）</span>
        <span class="k">盘盈</span><span>{{st.stockDetail.surplus_codes.length}} 个编号：{{st.stockDetail.surplus_codes.join('、')||'—'}}</span>
        <span class="k">状态</span><span>{{st.stockDetail.stocktake.closed_at ? '已关闭 '+fmt(st.stockDetail.stocktake.closed_at) : '进行中'}}</span>
      </div>
      <div class="alert warn">盘点只记录账实差异并查明原因；系统不会用盘点结果直接修改领用/归还记录。</div>
      <div class="row" v-if="!st.stockDetail.stocktake.closed_at">
        <div class="grow"><input v-model="st.stScan" class="scan-input" placeholder="扫到实物编号，回车记已盘（账实相符）" @keyup.enter="stockScan(true)"></div>
        <button class="btn" @click="stockScan(true)">扫到 = 账实相符</button>
      </div>
      <table style="margin-top:12px">
        <thead><tr><th>编号</th><th>品种</th><th>柜位</th><th>快照状态</th><th>差异</th><th>查明</th><th></th></tr></thead>
        <tbody>
          <tr v-for="l in st.stockDetail.lines" :key="l.id">
            <td class="code">{{l.item_code}}</td><td>{{l.template_name}}</td><td>{{l.location}}</td>
            <td>{{STATUS_NAMES[l.system_status_snapshot]}}</td>
            <td><span :class="'badge b-'+l.difference">{{l.difference==='match'?'账实相符':'盘亏'}}</span></td>
            <td style="max-width:220px">
              <span v-if="l.resolution">{{l.resolution}}</span>
              <span v-else class="muted">差异保留待查</span>
            </td>
            <td>
              <button class="btn sec sm" @click="openResolve(l)"
                :disabled="!!st.stockDetail.stocktake.closed_at">查明/处理</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="foot">
        <button class="btn sec" @click="st.stockModal=false">关闭</button>
        <button v-if="!st.stockDetail.stocktake.closed_at" class="btn warn" @click="closeStock">结束盘点（保留差异）</button>
      </div>
    </div>
  </div>

  <!-- ===== 盘点差异查明 ===== -->
  <div v-if="st.resolveTarget" class="modal-mask" @click.self="st.resolveTarget=null">
    <div class="modal" style="width:520px">
      <h2>差异查明 · <span class="code">{{st.resolveTarget.item_code}}</span></h2>
      <div class="alert err">
        快照为「{{STATUS_NAMES[st.resolveTarget.system_status_snapshot]}}」，实物未点到（盘亏）。
        查明后记录说明；如确属缺失可登记缺失并追溯上一节课，<b>领用记录不会被改动</b>。
      </div>
      <textarea v-model="st.resolveForm.resolution" rows="3" style="width:100%" placeholder="如：已在上节课后打碎，当时漏报；追溯领用单 #…"></textarea>
      <label style="margin-top:10px"><input type="checkbox" v-model="st.resolveForm.report_loss"> 同时登记为缺失并追溯最近一次领用（上一节课）</label>
      <div class="foot">
        <button class="btn sec" @click="st.resolveTarget=null">取消</button>
        <button class="btn" @click="submitResolve">保存查明结果</button>
      </div>
    </div>
  </div>
  </template>
  `,

  methods: {
    // 清洗中实物 → 设备任务号：从队列接口拿不到任务号，需查询；这里占位由提示信息给出。
  },
}).mount("#app");
