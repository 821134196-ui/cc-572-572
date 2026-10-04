<template>
  <div v-if="!store.user" class="login-wrap">
    <div class="login-card">
      <h1>实验室玻璃器皿<br/>领用与破损登记系统</h1>
      <p class="muted">中学实验室 · 按课程配发 · 逐件核对 · 全程溯源</p>
      <div class="row" style="justify-content:center;margin:18px 0">
        <input v-model="loginForm.username" placeholder="用户名" @keyup.enter="login" />
        <input v-model="loginForm.password" type="password" placeholder="密码" @keyup.enter="login" />
        <button class="primary" @click="login">登录</button>
      </div>
      <div v-if="loginErr" class="alert alert-error">{{ loginErr }}</div>
      <div class="muted quick-login">
        演示账号（密码同用户名）：
        <button v-for="a in demoAccounts" :key="a.u" @click="quick(a)">{{ a.label }}</button>
      </div>
    </div>
  </div>

  <div v-else>
    <header class="topbar">
      <div class="brand">🧪 玻璃器皿管理</div>
      <nav class="tabs">
        <button v-for="t in visibleTabs" :key="t.key"
                class="pill-tab" :class="{active: tab===t.key}" @click="switchTab(t.key)">
          {{ t.label }}
        </button>
      </nav>
      <div class="row">
        <span class="muted">{{ store.user.name }}（{{ store.user.role_name }}）</span>
        <button @click="logout">退出</button>
      </div>
    </header>

    <main class="content">
      <!-- ============ 柜位 / 编号查询 ============ -->
      <section v-if="tab==='locate'">
        <div class="card">
          <h2>柜位查实物</h2>
          <div class="row">
            <input v-model="locateQuery" placeholder="扫描/输入器皿独立编号，如 DS-9001-03"
                   class="scan-input" @keyup.enter="findItem" />
            <button class="primary" @click="findItem">查询编号</button>
            <input v-model="locateLoc" placeholder="或按柜位，如 C-01-03" style="width:200px"
                   @keyup.enter="loadLocations" />
            <button @click="loadLocations">查柜位</button>
          </div>
          <div v-if="locateMsg" class="alert" :class="locateMsg.cls">{{ locateMsg.text }}</div>
        </div>

        <div class="card" v-if="locations.length">
          <h3>柜位清单</h3>
          <table>
            <tr><th>柜位</th><th>存放件数</th><th>其中可借</th><th></th></tr>
            <tr v-for="l in locations" :key="l.location_code">
              <td><code>{{ l.location_code }}</code></td>
              <td>{{ l.count }}</td>
              <td>{{ l.available }}</td>
              <td><button @click="openLocation(l.location_code)">查看实物</button></td>
            </tr>
          </table>
        </div>
      </section>

      <!-- ============ 台账（管理员） ============ -->
      <section v-if="tab==='catalog'">
        <div class="card">
          <h2>器皿台账</h2>
          <div class="row">
            <input v-model="catFilter.code" placeholder="编号筛选" @keyup.enter="loadCatalog" />
            <select v-model="catFilter.status" @change="loadCatalog">
              <option value="">全部状态</option>
              <option v-for="(n,k) in statusNames" :key="k" :value="k">{{ n }}</option>
            </select>
            <button @click="loadCatalog">筛选</button>
            <button class="primary" @click="showAddItem=true">新增实物（独立编号+柜位）</button>
          </div>
        </div>
        <div class="card">
          <table>
            <tr><th>编号</th><th>名称/规格</th><th>柜位</th><th>状态</th><th>所属套件</th><th>溯源</th></tr>
            <tr v-for="it in catalog" :key="it.code">
              <td><code>{{ it.code }}</code></td>
              <td>{{ it.name }} {{ it.spec }} <span v-if="it.is_set" class="tag tag-blue">套件</span></td>
              <td>{{ it.location_code }}</td>
              <td><span class="tag" :class="statusTag(it.status)">{{ it.status_name }}</span></td>
              <td>{{ it.kit_code || '—' }}</td>
              <td><button @click="openHistory(it.code)">使用/清洗记录</button></td>
            </tr>
          </table>
        </div>
      </section>

      <!-- ============ 课程与领用（老师） ============ -->
      <section v-if="tab==='issue'">
        <div class="card">
          <h2>我的课程与学生组</h2>
          <button class="primary" @click="showNewCourse=true">新建课程</button>
        </div>
        <div class="card" v-for="c in courses" :key="c.id">
          <div class="row" style="justify-content:space-between">
            <h3 style="margin:0">{{ c.name }} · {{ c.class_name }}</h3>
            <div class="row">
              <button @click="addGroup(c)">+ 学生组</button>
              <button class="primary" @click="startIssue(c)">配发器皿</button>
            </div>
          </div>
          <table style="margin-top:8px">
            <tr><th>学生组</th><th>成员</th></tr>
            <tr v-for="g in c.groups" :key="g.id"><td>{{ g.name }}</td><td class="muted">{{ g.members }}</td></tr>
          </table>
        </div>
      </section>

      <!-- ============ 领用单 / 归还核对（老师） ============ -->
      <section v-if="tab==='return'">
        <div class="card">
          <h2>领用单与逐件归还核对</h2>
          <div class="row">
            <select v-model="loanFilter" @change="loadLoans">
              <option value="OPEN">借用中</option>
              <option value="">全部</option>
              <option value="CLOSED">已结案</option>
            </select>
          </div>
        </div>
        <div class="card" v-for="l in loans" :key="l.id">
          <div class="row" style="justify-content:space-between">
            <div>
              <strong>#{{ l.id }} {{ l.course }} · {{ l.group }}</strong>
              <span class="muted">（{{ l.class_name }}，{{ l.teacher }}，配发 {{ l.issued_at }}）</span>
              <span class="tag" :class="l.status==='OPEN'?'tag-amber':'tag-gray'">
                {{ l.status==='OPEN'?'借用中':'已结案' }}
              </span>
            </div>
            <button @click="openLoan(l.id)">逐件核对</button>
          </div>
        </div>
      </section>

      <!-- ============ 检查与清洗（管理员） ============ -->
      <section v-if="tab==='wash'">
        <div class="card">
          <h2>归还检查 · 清洗设备</h2>
          <p class="muted">器皿归还后为“已还待检”；检查合格直接回库，需清洗的送清洗机，清洗合格才回到可借库存。</p>
          <div class="row">
            <button @click="loadWashDesk">刷新</button>
            <button class="primary" :disabled="!dirtySelection.length" @click="sendWash">
              送清洗机（{{ dirtySelection.length }} 件）
            </button>
          </div>
        </div>
        <div class="card">
          <h3>待检 / 待洗（已还未回库）</h3>
          <table>
            <tr><th></th><th>编号</th><th>名称</th><th>柜位</th><th>归还登记</th><th>操作</th></tr>
            <tr v-for="it in returnedItems" :key="it.code">
              <td><input type="checkbox" v-model="dirtySelection" :value="it.code" /></td>
              <td><code>{{ it.code }}</code></td>
              <td>{{ it.name }} {{ it.spec }}</td>
              <td>{{ it.location_code }}</td>
              <td>{{ it.return_result_name }}</td>
              <td class="row">
                <button class="green" @click="inspect(it,'PASS')">检查合格回库</button>
                <button @click="inspect(it,'NEED_WASH')">判定需清洗</button>
              </td>
            </tr>
            <tr v-if="!returnedItems.length"><td colspan="6" class="muted">暂无待检器皿</td></tr>
          </table>
        </div>
        <div class="card">
          <h3>清洗机任务（模拟设备接口）</h3>
          <table>
            <tr><th>机台任务号</th><th>器皿</th><th>开始</th><th>完成</th><th>结果</th><th>模拟设备回调</th></tr>
            <tr v-for="w in washJobs" :key="w.id">
              <td><code>{{ w.job_id }}</code></td>
              <td>{{ w.item_code }}</td>
              <td>{{ w.started_at }}</td>
              <td>{{ w.finished_at || '—' }}</td>
              <td>
                <span class="tag" :class="w.result==='PASS'?'tag-green':w.result==='FAIL'?'tag-red':'tag-blue'">
                  {{ {RUNNING:'清洗中',PASS:'合格回库',FAIL:'清洗后发现破损'}[w.result] }}
                </span>
              </td>
              <td class="row" v-if="w.result==='RUNNING'">
                <button class="green" @click="finishWash(w,'PASS')">清洗合格</button>
                <button class="danger" @click="finishWash(w,'FAIL')">清洗后发现裂纹</button>
              </td>
              <td v-else class="muted">{{ w.note }}</td>
            </tr>
          </table>
        </div>
      </section>

      <!-- ============ 破损与免赔 ============ -->
      <section v-if="tab==='damage'">
        <div class="card">
          <h2>破损 / 缺失登记与免赔审核</h2>
          <p class="muted" v-if="isTeacher">
            任课老师只能登记破损，免赔由非任课老师（赵主任）审核；下方尝试自行免赔将被系统拒绝。
          </p>
          <p class="muted" v-else>免赔审核员（非任课老师）：审核每件破损/缺失登记。</p>
        </div>
        <div class="card" v-for="d in damages" :key="d.id">
          <div class="row" style="justify-content:space-between">
            <div>
              <strong><code>{{ d.item_code }}</code> {{ d.item_name }}</strong>
              <span class="tag" :class="d.status==='PENDING'?'tag-amber':d.status==='WAIVED'?'tag-green':'tag-red'">
                {{ d.status_name }}
              </span>
              <span class="tag tag-blue">{{ d.source_name }}</span>
              <span class="tag tag-gray">{{ d.damage_type_name }}</span>
            </div>
            <div class="muted">{{ d.reported_at }} 登记：{{ d.reported_by }}</div>
          </div>
          <p style="margin:8px 0">{{ d.description }}</p>
          <div v-if="d.reviewed_by" class="muted">
            审核：{{ d.reviewed_by }} {{ d.reviewed_at }}「{{ d.review_note }}」
          </div>
          <div v-else class="row" style="margin-top:8px">
            <input v-model="reviewNotes[d.id]" placeholder="审核意见" style="width:320px" />
            <template v-if="isReviewer">
              <button class="green" @click="review(d,'WAIVED')">核准免赔</button>
              <button class="danger" @click="review(d,'CHARGED')">照价赔偿</button>
            </template>
            <template v-else>
              <button class="warn" @click="review(d,'WAIVED')">（老师尝试）自行免赔</button>
            </template>
          </div>
        </div>
      </section>

      <!-- ============ 盘点（管理员） ============ -->
      <section v-if="tab==='stocktake'">
        <div class="card">
          <h2>盘点</h2>
          <div class="row">
            <input v-model="newST.label" placeholder="盘点单名称，如 10月全校盘点" />
            <input v-model="newST.scope" placeholder="限定柜位（可空=全部）" />
            <button class="primary" @click="createStocktake">新建盘点</button>
          </div>
        </div>
        <div class="card" v-for="st in stocktakes" :key="st.id">
          <div class="row" style="justify-content:space-between">
            <div>
              <strong>#{{ st.id }} {{ st.label }}</strong>
              <span class="muted">{{ st.scope }} · {{ st.created_at }}</span>
              <span class="tag" :class="st.status==='OPEN'?'tag-amber':'tag-gray'">
                {{ {OPEN:'待录入',COUNTED:'已录入'}[st.status] }}
              </span>
              <span v-if="st.variance_open" class="tag tag-red">{{ st.variance_open }} 条差异待处理</span>
            </div>
            <button @click="openStocktake(st.id)">打开盘点单</button>
          </div>
        </div>
      </section>
    </main>

    <!-- ============ 弹窗：器皿/套件/柜位 ============ -->
    <div v-if="itemModal" class="mask" @click.self="itemModal=null">
      <div class="modal">
        <h2><code>{{ itemModal.code }}</code> {{ itemModal.name }} {{ itemModal.spec }}</h2>
        <div class="row">
          <span>柜位 <code>{{ itemModal.location_code }}</code></span>
          <span class="tag" :class="statusTag(itemModal.status)">{{ itemModal.status_name }}</span>
          <span v-if="itemModal.kit_code">所属套件：<code>{{ itemModal.kit_code }}</code></span>
        </div>
        <div v-if="itemModal.parts.length">
          <h3>套件部件（{{ itemModal.parts.length }} 件，逐件独立编号）</h3>
          <table>
            <tr><th>编号</th><th>部件</th><th>柜位</th><th>当前状态</th></tr>
            <tr v-for="p in itemModal.parts" :key="p.code">
              <td><code>{{ p.code }}</code></td><td>{{ p.name }} {{ p.spec }}</td>
              <td>{{ p.location_code }}</td>
              <td><span class="tag" :class="statusTag(p.status)">{{ p.status_name }}</span></td>
            </tr>
          </table>
        </div>
        <div v-if="itemModal.photo_path"><img :src="itemModal.photo_path" class="photo" /></div>
        <div class="row" style="margin-top:14px;justify-content:flex-end">
          <button @click="itemModal=null">关闭</button>
          <button class="primary" @click="openHistory(itemModal.code)">使用/清洗溯源</button>
        </div>
      </div>
    </div>

    <!-- ============ 弹窗：柜位实物 ============ -->
    <div v-if="locModal" class="mask" @click.self="locModal=null">
      <div class="modal">
        <h2>柜位 {{ locModal.location_code }} 的实物</h2>
        <table>
          <tr><th>编号</th><th>名称</th><th>状态</th></tr>
          <tr v-for="it in locModal.items" :key="it.code">
            <td><code>{{ it.code }}</code></td><td>{{ it.name }} {{ it.spec }}</td>
            <td><span class="tag" :class="statusTag(it.status)">{{ it.status_name }}</span></td>
          </tr>
        </table>
        <div class="row" style="margin-top:14px;justify-content:flex-end"><button @click="locModal=null">关闭</button></div>
      </div>
    </div>

    <!-- ============ 弹窗：全生命周期溯源 ============ -->
    <div v-if="historyModal" class="mask" @click.self="historyModal=null">
      <div class="modal">
        <h2>溯源：<code>{{ historyModal.item.code }}</code> {{ historyModal.item.name }}</h2>
        <h3>使用记录（每节课、每个学生组）</h3>
        <table>
          <tr><th>课程/班级</th><th>学生组</th><th>任课老师</th><th>配发时间</th><th>归还结果</th><th>单状态</th></tr>
          <tr v-for="(l,i) in historyModal.loans" :key="i">
            <td>{{ l.course }}<br/><span class="muted">{{ l.class_name }}</span></td>
            <td>{{ l.group }}</td><td>{{ l.teacher }}</td><td>{{ l.issued_at }}</td>
            <td>{{ l.return_result }}</td>
            <td>{{ l.loan_status==='OPEN'?'借用中':'已结案' }}</td>
          </tr>
          <tr v-if="!historyModal.loans.length"><td colspan="6" class="muted">尚无领用记录</td></tr>
        </table>
        <h3>清洗记录</h3>
        <table>
          <tr><th>机台任务</th><th>开始</th><th>完成</th><th>结果</th><th>备注</th></tr>
          <tr v-for="(w,i) in historyModal.washes" :key="i">
            <td><code>{{ w.job_id }}</code></td><td>{{ w.started_at }}</td>
            <td>{{ w.finished_at||'—' }}</td><td>{{ w.result }}</td><td>{{ w.note }}</td>
          </tr>
          <tr v-if="!historyModal.washes.length"><td colspan="5" class="muted">尚无清洗记录</td></tr>
        </table>
        <h3>破损记录</h3>
        <table>
          <tr><th>发现环节</th><th>类型</th><th>说明</th><th>审核</th></tr>
          <tr v-for="d in historyModal.damages" :key="d.id">
            <td>{{ d.source_name }}</td><td>{{ d.damage_type_name }}</td>
            <td>{{ d.description }}</td><td>{{ d.status_name }}</td>
          </tr>
          <tr v-if="!historyModal.damages.length"><td colspan="4" class="muted">无破损记录</td></tr>
        </table>
        <div class="row" style="margin-top:14px;justify-content:flex-end"><button @click="historyModal=null">关闭</button></div>
      </div>
    </div>

    <!-- ============ 弹窗：配发 ============ -->
    <div v-if="issueModal" class="mask" @click.self="issueModal=null">
      <div class="modal">
        <h2>配发器皿：{{ issueModal.course.name }}（{{ issueModal.course.class_name }}）</h2>
        <div class="row">
          <label>学生组
            <select v-model="issueModal.group_id">
              <option v-for="g in issueModal.course.groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </label>
        </div>
        <div class="row" style="margin-top:10px">
          <input v-model="scanCode" placeholder="扫描器皿编号，回车加入；同一件不能借给两个组"
                 class="scan-input" @keyup.enter="addScan" />
        </div>
        <div v-if="scanDup.length" class="alert alert-warn">
          本单内重复扫码已自动忽略：{{ scanDup.join('、') }}（重复扫码只记一次）
        </div>
        <table style="margin-top:10px">
          <tr><th>编号</th><th>名称</th><th>柜位</th><th>状态</th><th></th></tr>
          <tr v-for="it in scanPreview" :key="it.code">
            <td><code>{{ it.code }}</code></td><td>{{ it.name }} {{ it.spec }}</td>
            <td>{{ it.location_code }}</td>
            <td><span class="tag" :class="statusTag(it.status)">{{ it.status_name }}</span></td>
            <td><button @click="removeScan(it.code)">移除</button></td>
          </tr>
        </table>
        <div v-if="issueErr" class="alert alert-error">
          {{ issueErr.message || issueErr }}
          <div v-if="issueErr.blocked">
            <div v-for="b in issueErr.blocked" :key="b.code" style="margin-top:4px">
              ❌ <code>{{ b.code }}</code> 当前为「{{ b.status_name }}」{{ b.where }}
            </div>
          </div>
        </div>
        <div class="row" style="margin-top:14px;justify-content:flex-end">
          <button @click="issueModal=null">取消</button>
          <button class="primary" @click="submitIssue">确认配发</button>
        </div>
      </div>
    </div>

    <!-- ============ 弹窗：逐件归还核对 ============ -->
    <div v-if="loanModal" class="mask" @click.self="loanModal=null">
      <div class="modal" style="width:900px">
        <h2>领用单 #{{ loanModal.id }}：{{ loanModal.course }} · {{ loanModal.group }}</h2>
        <p class="muted">已核对 {{ loanModal.returned }}/{{ loanModal.total }} 件；
          实验结束后逐件扫码核对，缺失也要登记，不能只按整套数量认定已还齐。</p>

        <div v-if="loanModal.kit_summaries.length" class="kit-box">
          <h3>套件核对</h3>
          <div v-for="k in loanModal.kit_summaries" :key="k.kit_code" class="alert"
               :class="k.complete?'alert-ok':'alert-error'">
            <div><strong>{{ k.verdict }}</strong></div>
            <div class="muted" style="margin-top:4px">
              <span v-for="p in k.parts" :key="p.code" style="margin-right:14px">
                <code>{{ p.code }}</code> {{ p.name }}：
                <strong :class="p.result==='MISSING'?'r':p.result==='CRACKED'?'r':''">{{ p.result_name }}</strong>
              </span>
            </div>
          </div>
        </div>

        <div class="row" style="margin:10px 0">
          <input v-model="returnCode" placeholder="扫描/输入归还器皿编号"
                 class="scan-input" @keyup.enter="scanReturn" />
        </div>
        <div class="row">
          <span v-if="pendingReturnItem" class="alert alert-warn" style="margin:0">
            <code>{{ pendingReturnItem.code }}</code> {{ pendingReturnItem.name }} —— 请选择检查结果：
          </span>
          <template v-if="pendingReturnItem">
            <button class="green" @click="doReturn('COMPLETE')">完整</button>
            <button class="warn" @click="doReturn('DIRTY')">待清洗</button>
            <button class="danger" @click="doReturn('CRACKED')">裂纹</button>
            <button class="danger" @click="doReturn('MISSING')">缺失</button>
          </template>
        </div>

        <div v-if="returnMsg" class="alert" :class="returnMsg.cls" style="margin-top:10px">
          {{ returnMsg.text }}
        </div>

        <table style="margin-top:10px">
          <tr><th>编号</th><th>名称</th><th>归还结果</th><th>归还时间</th><th>备注</th></tr>
          <tr v-for="it in loanModal.items" :key="it.code">
            <td><code>{{ it.code }}</code> <span v-if="it.kit_code" class="tag tag-blue">套件部件</span></td>
            <td>{{ it.name }}</td>
            <td>
              <span v-if="it.return_result" class="tag"
                    :class="{'COMPLETE':'tag-green','DIRTY':'tag-amber','CRACKED':'tag-red','MISSING':'tag-red'}[it.return_result]">
                {{ it.return_result_name }}
              </span>
              <span v-else class="tag tag-gray">未还</span>
            </td>
            <td>{{ it.returned_at || '—' }}</td>
            <td class="muted">{{ it.note }}</td>
          </tr>
        </table>

        <div class="row" style="margin-top:14px;justify-content:flex-end">
          <button @click="loanModal=null">关闭</button>
          <button class="primary" @click="closeLoan">全部核对完毕，结案</button>
        </div>
      </div>
    </div>

    <!-- ============ 弹窗：盘点录入 ============ -->
    <div v-if="stModal" class="mask" @click.self="stModal=null">
      <div class="modal" style="width:900px">
        <h2>盘点单 #{{ stModal.id }} {{ stModal.label }}</h2>
        <template v-if="stModal.status==='OPEN'">
          <p class="muted">把实盘逐件扫描到下方（每行一个编号，可附 柜位）；系统与账面逐项比对，
            账实不符将作为差异长期保留，<strong>不会改动任何领用记录</strong>。</p>
          <textarea v-model="countText" rows="8" style="width:100%"
                    placeholder="DS-9001&#10;BK-1001 C-01-00&#10;BK-1002"></textarea>
          <div class="row" style="margin-top:10px">
            <button class="primary" @click="submitCount">录入实盘并比对</button>
            <span class="muted">账面应在柜 {{ stModal.expected.length }} 件：
              {{ stModal.expected.map(i=>i.code).join('、') }}</span>
          </div>
        </template>
        <template v-else>
          <h3>盘点差异（保留，不回改领用记录）</h3>
          <div v-for="v in stModal.variances" :key="v.id" class="alert"
               :class="v.status==='OPEN'?'alert-error':'alert-ok'">
            <div><strong><code>{{ v.item_code }}</code> {{ v.kind_name }}</strong>
              <span class="tag" :class="v.status==='OPEN'?'tag-red':'tag-green'">
                {{ v.status==='OPEN'?'待处理':'已处理' }}
              </span>
            </div>
            <div style="margin:4px 0">{{ v.detail }}</div>
            <div v-if="v.status==='OPEN'" class="row">
              <input v-model="resolveText[v.id]" placeholder="处理说明（只追加说明，差异记录保留）"
                     style="width:420px" />
              <button @click="resolveVariance(v)">登记处理</button>
            </div>
            <div v-else class="muted">处理：{{ v.resolution }}（{{ v.resolved_by }} {{ v.resolved_at }}）</div>
          </div>
          <div v-if="!stModal.variances.length" class="alert alert-ok">账实相符，无差异。</div>
        </template>
        <div class="row" style="margin-top:14px;justify-content:flex-end"><button @click="stModal=null">关闭</button></div>
      </div>
    </div>

    <!-- ============ 弹窗：新增课程 / 学生组 / 实物 ============ -->
    <div v-if="showNewCourse" class="mask" @click.self="showNewCourse=false">
      <div class="modal" style="width:480px">
        <h2>新建课程</h2>
        <div class="col-form">
          <input v-model="newCourse.name" placeholder="课程名称，如 粗盐提纯" />
          <input v-model="newCourse.class_name" placeholder="班级，如 初三(1)班" />
        </div>
        <div v-if="formErr" class="alert alert-error">{{ formErr }}</div>
        <div class="row" style="margin-top:12px;justify-content:flex-end">
          <button @click="showNewCourse=false">取消</button>
          <button class="primary" @click="submitCourse">创建</button>
        </div>
      </div>
    </div>

    <div v-if="showAddItem" class="mask" @click.self="showAddItem=false">
      <div class="modal" style="width:520px">
        <h2>新增实物器皿</h2>
        <div class="col-form">
          <input v-model="newItem.code" placeholder="独立编号，如 TT-3004" />
          <select v-model="newItem.template_id">
            <option value="">选择型号</option>
            <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }} {{ t.spec }}</option>
          </select>
          <input v-model="newItem.location_code" placeholder="柜位，如 A-03-02" />
          <input v-model="newItem.kit_code" placeholder="所属套件编号（可空），如 DS-9001" />
        </div>
        <div v-if="formErr" class="alert alert-error">{{ formErr }}</div>
        <div class="row" style="margin-top:12px;justify-content:flex-end">
          <button @click="showAddItem=false">取消</button>
          <button class="primary" @click="submitItem">入库</button>
        </div>
      </div>
    </div>

    <div v-if="globalMsg" class="toast" :class="globalMsg.cls">{{ globalMsg.text }}</div>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { api, store } from './api.js'

const STATUS_NAMES = {
  AVAILABLE: '可借', LENT: '已借出', RETURNED: '已还待检',
  CLEANING: '清洗中', BROKEN: '破损', MISSING: '缺失', RETIRED: '报废'
}
const statusNames = STATUS_NAMES
const isTeacher = computed(() => store.user.role === 'teacher')
const isReviewer = computed(() => store.user.role === 'reviewer')

const tabs = [
  { key: 'locate', label: '柜位查实物', roles: ['teacher', 'admin', 'reviewer'] },
  { key: 'catalog', label: '器皿台账', roles: ['admin'] },
  { key: 'issue', label: '课程配发', roles: ['teacher'] },
  { key: 'return', label: '归还核对', roles: ['teacher'] },
  { key: 'wash', label: '检查清洗', roles: ['admin'] },
  { key: 'damage', label: '破损免赔', roles: ['teacher', 'reviewer'] },
  { key: 'stocktake', label: '盘点', roles: ['admin'] }
]
const visibleTabs = computed(() => tabs.filter(t => t.roles.includes(store.user.role)))
const tab = ref(visibleTabs.value[0]?.key || 'locate')
function switchTab(k) {
  tab.value = k
  if (k === 'locate') loadLocations()
  if (k === 'catalog') loadCatalog()
  if (k === 'issue') loadCourses()
  if (k === 'return') loadLoans()
  if (k === 'wash') loadWashDesk()
  if (k === 'damage') loadDamages()
  if (k === 'stocktake') loadStocktakes()
}

// ---------- 提示 ----------
const globalMsg = ref(null)
function toast(text, cls = 'alert-ok') {
  globalMsg.value = { text, cls }
  setTimeout(() => (globalMsg.value = null), 3500)
}
function errText(e) { return e?.message || String(e) }

// ---------- 登录 ----------
const loginForm = reactive({ username: '', password: '' })
const loginErr = ref('')
const demoAccounts = [
  { u: 'teacher1', p: 'teacher1', label: '王老师（任课）' },
  { u: 'admin1', p: 'admin1', label: '陈管理员' },
  { u: 'reviewer1', p: 'reviewer1', label: '赵主任（审核员）' }
]
async function login() {
  loginErr.value = ''
  try {
    const u = await api.post('/api/login', loginForm)
    store.setUser(u)
    initAfterLogin()
  } catch (e) { loginErr.value = errText(e) }
}
function quick(a) {
  loginForm.username = a.u; loginForm.password = a.p
  login()
}
function logout() { store.setUser(null) }
function initAfterLogin() {
  tab.value = visibleTabs.value[0]?.key
  switchTab(tab.value)
}
onMounted(() => { if (store.user) initAfterLogin() })

function statusTag(s) {
  return { AVAILABLE: 'tag-green', LENT: 'tag-blue', RETURNED: 'tag-amber',
    CLEANING: 'tag-blue', BROKEN: 'tag-red', MISSING: 'tag-red', RETIRED: 'tag-gray' }[s] || 'tag-gray'
}

// ---------- 柜位 / 编号查询 ----------
const locateQuery = ref('')
const locateLoc = ref('')
const locateMsg = ref(null)
const locations = ref([])
const itemModal = ref(null)
const locModal = ref(null)

async function loadLocations() {
  locations.value = await api.get('/api/locations')
}
async function findItem() {
  locateMsg.value = null
  const code = locateQuery.value.trim()
  if (!code) return
  try {
    const it = await api.get(`/api/items/${encodeURIComponent(code)}`)
    itemModal.value = it
    // 若该件属于未还套件，给出醒目提示
    if (it.status !== 'AVAILABLE') {
      locateMsg.value = { cls: 'alert-warn',
        text: `编号 ${code} 实物当前状态为「${it.status_name}」，不在可借库存（柜位 ${it.location_code}）` }
    } else {
      locateMsg.value = { cls: 'alert-ok',
        text: `找到实物：${it.name}，柜位 ${it.location_code}，状态：可借` }
    }
  } catch (e) { locateMsg.value = { cls: 'alert-error', text: errText(e) } }
}
async function openLocation(loc) {
  locModal.value = await api.get(`/api/locations/${encodeURIComponent(loc)}`)
}

// ---------- 溯源 ----------
const historyModal = ref(null)
async function openHistory(code) {
  historyModal.value = await api.get(`/api/items/${encodeURIComponent(code)}/history`)
  itemModal.value = null
}

// ---------- 台账 ----------
const catalog = ref([])
const templates = ref([])
const catFilter = reactive({ code: '', status: '' })
const showAddItem = ref(false)
const newItem = reactive({ code: '', template_id: '', location_code: '', kit_code: '' })
const formErr = ref('')

async function loadCatalog() {
  const q = new URLSearchParams()
  if (catFilter.code) q.set('code', catFilter.code)
  if (catFilter.status) q.set('status', catFilter.status)
  catalog.value = await api.get(`/api/items?${q}`)
}
async function submitItem() {
  formErr.value = ''
  try {
    await api.post('/api/items', { ...newItem, template_id: Number(newItem.template_id),
      kit_code: newItem.kit_code || null })
    showAddItem.value = false
    Object.assign(newItem, { code: '', template_id: '', location_code: '', kit_code: '' })
    loadCatalog(); toast('实物已入库：独立编号 + 柜位')
  } catch (e) { formErr.value = errText(e) }
}

// ---------- 课程 ----------
const courses = ref([])
const showNewCourse = ref(false)
const newCourse = reactive({ name: '', class_name: '' })

async function loadCourses() { courses.value = await api.get('/api/courses') }
async function submitCourse() {
  formErr.value = ''
  try {
    await api.post('/api/courses', newCourse)
    showNewCourse.value = false
    newCourse.name = ''; newCourse.class_name = ''
    loadCourses(); toast('课程已创建')
  } catch (e) { formErr.value = errText(e) }
}
async function addGroup(c) {
  const name = prompt('学生组名称，如 第3组')
  if (!name) return
  const members = prompt('成员姓名（可空）', '') || ''
  try {
    await api.post(`/api/courses/${c.id}/groups`, { name, members })
    loadCourses(); toast('学生组已建立')
  } catch (e) { toast(errText(e), 'alert-error') }
}

// ---------- 配发 ----------
const issueModal = ref(null)
const scanCode = ref('')
const scannedCodes = ref([])
const scanPreview = ref([])
const scanDup = ref([])
const issueErr = ref(null)
const availableCache = ref([])

function startIssue(c) {
  issueModal.value = { course: c, group_id: c.groups[0]?.id }
  scannedCodes.value = []; scanPreview.value = []; scanDup.value = []
  scanCode.value = ''; issueErr.value = null
}
async function addScan() {
  const code = scanCode.value.trim(); scanCode.value = ''
  issueErr.value = null
  if (!code) return
  if (scannedCodes.value.includes(code)) {
    if (!scanDup.value.includes(code)) scanDup.value.push(code)
    return
  }
  try {
    const list = await api.get(`/api/items?code=${encodeURIComponent(code)}`)
    const it = list.find(x => x.code === code)
    if (!it) { issueErr.value = { message: `编号 ${code} 不存在` }; return }
    scannedCodes.value.push(code)
    scanPreview.value.push(it)
  } catch (e) { issueErr.value = { message: errText(e) } }
}
function removeScan(code) {
  scannedCodes.value = scannedCodes.value.filter(c => c !== code)
  scanPreview.value = scanPreview.value.filter(i => i.code !== code)
}
async function submitIssue() {
  issueErr.value = null
  if (!issueModal.value.group_id) { issueErr.value = { message: '请先建立学生组' }; return }
  try {
    const r = await api.post('/api/loans', {
      course_id: issueModal.value.course.id,
      group_id: issueModal.value.group_id,
      item_codes: scannedCodes.value
    })
    issueModal.value = null
    toast(`已配发 ${r.issued} 件${r.duplicate_scans_ignored.length ?
      '，重复扫码 ' + r.duplicate_scans_ignored.length + ' 次已忽略' : ''}`)
    loadLoans()
  } catch (e) { issueErr.value = e.data?.detail ? { message: e.data.detail.message, blocked: e.data.detail.blocked } : { message: errText(e) } }
}

// ---------- 领用单 / 归还 ----------
const loans = ref([])
const loanFilter = ref('OPEN')
const loanModal = ref(null)
const returnCode = ref('')
const pendingReturnItem = ref(null)
const returnMsg = ref(null)

async function loadLoans() {
  const q = loanFilter.value ? `?status=${loanFilter.value}` : ''
  loans.value = await api.get(`/api/loans${q}`)
}
async function openLoan(id) {
  loanModal.value = await api.get(`/api/loans/${id}`)
  pendingReturnItem.value = null; returnMsg.value = null; returnCode.value = ''
}
async function refreshLoan() {
  loanModal.value = await api.get(`/api/loans/${loanModal.value.id}`)
}
function scanReturn() {
  const code = returnCode.value.trim(); returnCode.value = ''
  returnMsg.value = null
  if (!code) return
  const it = loanModal.value.items.find(x => x.code === code)
  if (!it) { returnMsg.value = { cls: 'alert-error', text: `${code} 不在本领用单配发清单中` }; return }
  if (it.return_result) {
    returnMsg.value = { cls: 'alert-error',
      text: `${code} 已于 ${it.returned_at} 登记为「${it.return_result_name}」——重复扫码归还只记一次` }
    return
  }
  pendingReturnItem.value = it
}
async function doReturn(result) {
  const it = pendingReturnItem.value
  try {
    const r = await api.post(`/api/loans/${loanModal.value.id}/return/${it.code}`,
      { result, note: '' })
    let extra = ''
    if (r.kit_warnings.length) extra = '；⚠ ' + r.kit_warnings.join('；')
    returnMsg.value = {
      cls: result === 'MISSING' || result === 'CRACKED' ? 'alert-warn' : 'alert-ok',
      text: `${it.code} 已登记为「${r.result_name}」（${r.returned}/${r.total}）${extra}`
    }
  } catch (e) { returnMsg.value = { cls: 'alert-error', text: errText(e) } }
  pendingReturnItem.value = null
  await refreshLoan()
}
async function closeLoan() {
  try {
    await api.post(`/api/loans/${loanModal.value.id}/close`, {})
    toast('领用单已结案'); await refreshLoan(); loadLoans()
  } catch (e) { returnMsg.value = { cls: 'alert-error', text: errText(e) } }
}

// ---------- 检查 / 清洗 ----------
const returnedItems = ref([])
const washJobs = ref([])
const dirtySelection = ref([])

async function loadWashDesk() {
  const list = await api.get('/api/items?status=RETURNED')
  // 附带归还登记结果（查最近领用单）
  const enriched = []
  for (const it of list) {
    const h = await api.get(`/api/items/${it.code}/history`)
    const last = h.loans.filter(l => l.return_result !== '未还').at(-1)
    enriched.push({ ...it, return_result_name: last?.return_result || '待检' })
  }
  returnedItems.value = enriched
  washJobs.value = await api.get('/api/wash')
  dirtySelection.value = dirtySelection.value.filter(c => list.some(i => i.code === c))
}
async function inspect(it, action) {
  try {
    const r = await api.post(`/api/items/${it.code}/inspect`, { action })
    toast(`${it.code}：${r.status_name}`); loadWashDesk()
  } catch (e) { toast(errText(e), 'alert-error') }
}
async function sendWash() {
  try {
    const r = await api.post('/api/wash/start', { item_codes: dirtySelection.value })
    toast(`已送清洗机，任务号：${r.jobs.map(j => j.job_id).join('、')}`)
    dirtySelection.value = []; loadWashDesk()
  } catch (e) { toast(errText(e), 'alert-error') }
}
async function finishWash(w, result) {
  try {
    const r = await api.post(`/api/wash/${w.job_id}/complete?result=${result}`, {})
    if (result === 'FAIL') {
      toast(`清洗后发现破损，已追溯上一节课：${r.traced_loan?.course} - ${r.traced_loan?.group}`,
        'alert-warn')
    } else {
      toast(`${w.item_code} 清洗合格，已回到可借库存`)
    }
    loadWashDesk()
  } catch (e) { toast(errText(e), 'alert-error') }
}

// ---------- 破损 / 免赔 ----------
const damages = ref([])
const reviewNotes = reactive({})
async function loadDamages() { damages.value = await api.get('/api/damages') }
async function review(d, decision) {
  try {
    await api.post(`/api/damages/${d.id}/review`, { decision, note: reviewNotes[d.id] || '' })
    toast(decision === 'WAIVED' ? '免赔已核准（非任课老师审核）' : '已登记为照价赔偿')
    loadDamages()
  } catch (e) {
    toast(`${e.status === 403 ? '⛔ 被系统拒绝：' : ''}${errText(e)}`, 'alert-error')
  }
}

// ---------- 盘点 ----------
const stocktakes = ref([])
const newST = reactive({ label: '', scope: '' })
const stModal = ref(null)
const countText = ref('')
const resolveText = reactive({})

async function loadStocktakes() { stocktakes.value = await api.get('/api/stocktakes') }
async function createStocktake() {
  if (!newST.label) return toast('请填写盘点单名称', 'alert-error')
  try {
    await api.post('/api/stocktakes', { label: newST.label, scope_location: newST.scope || null })
    newST.label = ''; newST.scope = ''
    loadStocktakes(); toast('盘点单已创建')
  } catch (e) { toast(errText(e), 'alert-error') }
}
async function openStocktake(id) {
  stModal.value = await api.get(`/api/stocktakes/${id}`)
  countText.value = stModal.value.expected.map(i => i.code).join('\n')
}
async function submitCount() {
  const entries = countText.value.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
    const [item_code, found_location] = l.split(/\s+/)
    return { item_code, found_location: found_location || null }
  })
  try {
    const r = await api.post(`/api/stocktakes/${stModal.value.id}/count`, entries)
    toast(`实盘 ${r.counted} 件 / 账面 ${r.expected} 件，差异 ${r.variances.length} 条已保留`)
    await openStocktake(stModal.value.id)
    loadStocktakes()
  } catch (e) { toast(errText(e), 'alert-error') }
}
async function resolveVariance(v) {
  try {
    await api.post(`/api/stocktakes/${stModal.value.id}/variances/${v.id}/resolve`,
      { resolution: resolveText[v.id] || '已核实处理' })
    toast('处理说明已追加，差异记录保留'); await openStocktake(stModal.value.id); loadStocktakes()
  } catch (e) { toast(errText(e), 'alert-error') }
}

// 管理员页面需要型号列表
onMounted(async () => {
  if (store.user?.role === 'admin') templates.value = await api.get('/api/templates').catch(() => [])
})
</script>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.login-card {
  background: #fff; border: 1px solid var(--border); border-radius: 14px;
  padding: 40px 44px; width: 560px; text-align: center; box-shadow: 0 8px 30px rgba(15,23,42,.08);
}
.login-card h1 { font-size: 24px; line-height: 1.4; margin: 0 0 6px; }
.quick-login { margin-top: 18px; display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
.topbar {
  background: #fff; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 18px; padding: 0 22px; position: sticky; top: 0; z-index: 20;
}
.brand { font-weight: 700; white-space: nowrap; }
.tabs { display: flex; gap: 4px; flex: 1; overflow-x: auto; }
.content { max-width: 1080px; margin: 0 auto; padding: 18px; }
.photo { max-width: 240px; border-radius: 8px; margin-top: 8px; border: 1px solid var(--border); }
.kit-box { margin: 10px 0; }
.r { color: var(--red); }
.col-form { display: flex; flex-direction: column; gap: 10px; }
.toast {
  position: fixed; right: 24px; bottom: 24px; z-index: 100;
  padding: 12px 18px; border-radius: 10px; font-weight: 600;
  box-shadow: 0 6px 24px rgba(15,23,42,.18); background: #fff;
}
.toast.alert-ok { background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; }
.toast.alert-error { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; }
.toast.alert-warn { background: #fffbeb; border: 1px solid #fde68a; color: #92400e; }
</style>

