/**
 * practice-page.js —— 功课模块页面（单一来源，主站 SPA 与独立页共用同一份）
 *
 * 依赖：practice-core.js（同源注入，提供 window.PracticeCore）
 * 入口：renderPracticePage() → 返回 HTML 片段；initPracticePage() → 绑定与加载
 *
 * 设计取舍：
 *   · 单页内「分栏切换」而非多个 hash 子路由 —— 不改动现有 hash 路由解析器，
 *     D5 只要求主站入口 #/__practice，子视图用页内 tab 承担（风险最小）。
 *   · 入口不在侧栏与首页快捷卡渲染（D4）；直接访问 #/__practice。
 *   · 数据一律走 /__api/practice/*（同源代理，Cookie 由服务端读，前端不传 username）。
 *   · 离线：打卡先写 localStorage 待发队列，联网后幂等重放（以 date+practiceId 为键）。
 */
(function (root) {
  'use strict';
  var C = root.PracticeCore;

  var PRACTICE_CSS = [
    '.pg-wrap{max-width:900px;margin:0 auto}',
    '.pg-tabs{display:flex;gap:.4rem;flex-wrap:wrap;margin:.2rem 0 1rem}',
    '.pg-tab{border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);border-radius:999px;',
    'padding:.5rem .95rem;font:inherit;font-size:.88rem;cursor:pointer;line-height:1;min-height:38px}',
    '.pg-tab.on{background:var(--accent);border-color:transparent;color:#fff;font-weight:600}',
    '.pg-card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:1rem 1rem 1.1rem;margin:0 0 .9rem}',
    '.pg-h{font-size:1rem;font-weight:700;margin:0 0 .7rem;display:flex;align-items:center;gap:.45rem}',
    '.pg-sub{color:var(--ink-soft);font-size:.82rem;line-height:1.7;margin:0 0 .7rem}',
    '.pg-row{display:flex;align-items:center;gap:.6rem;padding:.6rem 0;border-bottom:1px dashed var(--line)}',
    '.pg-row:last-child{border-bottom:0}',
    '.pg-name{flex:1 1 auto;min-width:0}',
    '.pg-name b{font-weight:600}',
    '.pg-meta{color:var(--ink-soft);font-size:.78rem;margin-top:.15rem;line-height:1.55}',
    '.pg-num{font-variant-numeric:tabular-nums}',
    '.pg-btn{border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:9px;padding:.5rem .8rem;',
    'font:inherit;font-size:.85rem;cursor:pointer;min-height:40px;white-space:nowrap}',
    '.pg-btn.ghost{background:var(--surface);color:var(--ink);border-color:var(--line)}',
    '.pg-btn.tiny{padding:.35rem .6rem;font-size:.78rem;min-height:32px}',
    '.pg-btn:disabled{opacity:.5;cursor:default}',
    '.pg-input,.pg-select{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:9px;',
    'padding:.55rem .65rem;font:inherit;font-size:.95rem;min-height:42px;width:100%;box-sizing:border-box}',
    '.pg-inline{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}',
    '.pg-inline .pg-input{width:auto;flex:1 1 8rem}',
    '.pg-bar{height:7px;background:var(--surface-soft);border-radius:99px;overflow:hidden;margin:.42rem 0 .3rem}',
    '.pg-bar i{display:block;height:100%;background:var(--accent)}',
    '.pg-badge{display:inline-block;font-size:.72rem;padding:.12rem .45rem;border-radius:5px;background:var(--surface-soft);',
    'color:var(--ink-soft);margin-left:.35rem;border:1px solid var(--line)}',
    '.pg-pace-ontrack{color:#2e7d32}.pg-pace-behind{color:#b3261e}.pg-pace-expired{color:#b3261e}',
    '.pg-pace-done{color:var(--accent)}.pg-pace-none{color:var(--ink-soft)}',
    '.pg-ok{background:#eef7ee;border-color:#cde5cd}.pg-err{background:#fdeceb;border-color:#f3c9c6}',
    '.pg-msg{font-size:.84rem;line-height:1.6;margin:.5rem 0 0}',
    '.pg-msg.err{color:#b3261e}.pg-msg.ok{color:#2e7d32}',
    '.pg-month{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-top:.5rem}',
    '.pg-day{border:1px solid var(--line);border-radius:8px;padding:.35rem .1rem;text-align:center;font-size:.78rem;',
    'cursor:pointer;background:var(--surface);color:var(--ink);font-variant-numeric:tabular-nums;min-height:42px}',
    '.pg-day.has{background:#f6ece4;border-color:var(--accent);color:var(--accent);font-weight:600}',
    '.pg-day.today{outline:2px solid var(--accent);outline-offset:-2px}',
    '.pg-day.empty{border:0;background:transparent;cursor:default;min-height:0}',
    '.pg-dayhead{text-align:center;font-size:.72rem;color:var(--ink-soft)}',
    '.pg-wizard{display:grid;gap:.7rem}',
    '.pg-field{display:grid;gap:.28rem}',
    '.pg-field label{font-size:.8rem;color:var(--ink-soft)}',
    '.pg-icons{display:flex;flex-wrap:wrap;gap:.2rem;max-height:9.5rem;overflow:auto;border:1px solid var(--line);',
    'border-radius:9px;padding:.4rem}',
    '.pg-icon{font-size:1.15rem;line-height:1;border:1px solid transparent;background:transparent;border-radius:7px;',
    'cursor:pointer;padding:.28rem}',
    '.pg-icon.on{border-color:var(--accent);background:var(--surface-soft)}',
    '.pg-mode{display:flex;gap:.35rem;flex-wrap:wrap}',
    '.pg-mode button{flex:1 1 10rem}',
    '.pg-big{font-size:2.6rem;text-align:center;font-variant-numeric:tabular-nums;margin:.4rem 0;color:var(--accent)}',
    '.pg-hint{font-size:.82rem;color:var(--ink-soft);line-height:1.7;margin:.35rem 0 0}',
    '.pg-foot{color:var(--ink-soft);font-size:.76rem;line-height:1.75;margin-top:1rem}',
    '@media(max-width:600px){.pg-tab{padding:.45rem .7rem;font-size:.82rem}.pg-card{padding:.85rem .8rem 1rem}',
    '.pg-name b{font-size:.95rem}',
    // §7.5：打卡是手机高频动作，触达区 ≥44px（含 tiny 小按钮与月历补录格）
    '.pg-btn,.pg-btn.tiny{min-height:44px;padding:.55rem .8rem}',
    '.pg-day{min-height:44px}}'
  ].join('');

  var TABS = [
    { k: 'today', n: '今日' }, { k: 'manage', n: '功课管理' },
    { k: 'stats', n: '统计' }, { k: 'tools', n: '工具' }, { k: 'settings', n: '导出' }
  ];

  var S = { data: null, view: 'today', wiz: null, msg: '', msgErr: false, counter: 0, timer: null, timerSec: 0, timerRun: false };

  // ------------------------------------------------------------------ 工具
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]; }); }

  // 设备免密（只读）身份：与主站 /admin 共用同一个 localStorage 键。
  // 有会话时服务端以会话为准（可写）；无会话时服务端按 X-Device-ID 反查
  // admin_dev_<id>（scope 必须含 practice）→ 只读。缺这个头，设备免密必然 401。
  var DEVICE_KEY = 'longchen-device-id';
  function deviceId() {
    try {
      var id = localStorage.getItem(DEVICE_KEY);
      if (!id) {
        id = 'dev_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem(DEVICE_KEY, id);
      }
      return id || '';
    } catch (e) { return ''; }
  }
  function jsonHeaders() {
    var h = { 'Content-Type': 'application/json' };
    var d = deviceId();
    if (d) h['X-Device-ID'] = d;
    return h;
  }

  function api(action, body) {
    return fetch('/__api/practice/' + action, {
      method: 'POST', credentials: 'same-origin',
      headers: jsonHeaders(),
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return { success: false, message: '响应解析失败' }; })
        .then(function (j) { j._status = r.status; return j; });
    });
  }

  function ensureCSS() {
    if (document.getElementById('pg-style')) return;
    var st = document.createElement('style');
    st.id = 'pg-style';
    st.textContent = PRACTICE_CSS;
    document.head.appendChild(st);
  }

  function isReadOnly() { return !!(S.data && S.data.viaDevice); }

  function practiceById(id) {
    var arr = (S.data && S.data.practices) || [];
    for (var i = 0; i < arr.length; i++) if (arr[i].id === id) return arr[i];
    return null;
  }
  function doneOf(id) { return (S.data && S.data.stat && S.data.stat.totalDone && Number(S.data.stat.totalDone[id])) || 0; }
  function logsOf() { return (S.data && S.data.logs) || {}; }

  // ------------------------------------------------------------------ 待发队列（离线打卡）
  var QUEUE_KEY = 'practice_pending_v1';
  function readQueue() { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch (e) { return []; } }
  function writeQueue(q) { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); } catch (e) {} }
  // 待发队列存 {date, practiceId, base, delta}：
  //   base  = 入队时前端所知的「服务端当天值」，delta = 待补增量。
  //   重放统一发 mode='set' 且 value = base + delta —— 绝对量，重复重放结果相同（幂等）。
  function enqueue(item) {
    var q = readQueue(), hit = null, i;
    for (i = 0; i < q.length; i++) {
      if (q[i].date === item.date && q[i].practiceId === item.practiceId) { hit = q[i]; break; }
    }
    var base = Number(item.base) || 0, delta = Number(item.delta) || 0;
    if (!hit) {
      q.push({ date: item.date, practiceId: item.practiceId, base: base, delta: delta });
    } else if (Number(hit.base) === base) {
      // 同基线：离线连点累加，不丢数
      hit.delta = (Number(hit.delta) || 0) + delta;
    } else {
      // 基线变了 → 说明先前那次请求其实已落库，改用新基线重算，避免重复计数
      hit.base = base; hit.delta = delta;
    }
    writeQueue(q);
  }
  function flushQueue() {
    var q = readQueue();
    if (!q.length) return Promise.resolve(0);
    var okKeys = {}, n = 0, chain = Promise.resolve();
    q.forEach(function (e) {
      chain = chain.then(function () {
        var req = {
          date: e.date, practiceId: e.practiceId,
          value: Math.max(0, (Number(e.base) || 0) + (Number(e.delta) || 0)),
          mode: 'set'
        };
        return api('checkin', req).then(function (j) {
          if (j && j.success) { okKeys[e.date + '|' + e.practiceId] = 1; n++; }
        }).catch(function () {});
      });
    });
    return chain.then(function () {
      // 只清重放成功的条目：部分失败要留住，不能丢记录
      writeQueue(readQueue().filter(function (x) { return !okKeys[x.date + '|' + x.practiceId]; }));
      return n;
    });
  }

  // ------------------------------------------------------------------ 渲染：外壳
  function renderPracticePage() {
    var tabs = TABS.map(function (t) {
      return '<button type="button" class="pg-tab' + (S.view === t.k ? ' on' : '') + '" data-pgview="' + t.k + '">' + t.n + '</button>';
    }).join('');
    return '<div class="pg-wrap"><h1 style="font-size:1.3rem">功课</h1>'
      + '<div class="pg-tabs" id="pgTabs">' + tabs + '</div>'
      + '<div id="pgBody"><p class="pg-sub">加载中…</p></div>'
      + '<p class="pg-foot">功课数据仅本人可见，不进入任何公开统计。入口不在侧栏显示，可直接访问 <code>#/__practice</code>。</p>'
      + '</div>';
  }

  function bindShell() {
    var tabs = document.getElementById('pgTabs');
    if (tabs && !tabs._pgBound) {
      tabs._pgBound = true;
      tabs.addEventListener('click', function (e) {
        var b = e.target.closest('[data-pgview]');
        if (!b) return;
        S.view = b.getAttribute('data-pgview');
        S.msg = ''; S.wiz = null;
        renderBody();
        var t2 = document.getElementById('pgTabs');
        if (t2) { Array.prototype.forEach.call(t2.children, function (c) { c.classList.toggle('on', c.getAttribute('data-pgview') === S.view); }); }
      });
    }
  }

  // ------------------------------------------------------------------ 渲染：今日
  function viewToday() {
    var arr = ((S.data && S.data.practices) || []).filter(function (p) { return p.isActive !== false; });
    if (!arr.length) {
      return '<div class="pg-card"><div class="pg-h">还没有功课</div>'
        + '<p class="pg-sub">先去「功课管理」添加，或从旧小程序一次性搬入已有功课。</p></div>';
    }
    var today = (S.data && S.data.today) || C.getToday();
    var dayLog = logsOf()[today] || {};
    var doneCount = 0;
    var rows = arr.map(function (p) {
      var done = doneOf(p.id);
      var cur = dayLog[p.id] ? Number(dayLog[p.id].value) : 0;
      var unit = p.unit || '';
      var isSwitch = C.isSwitchLike(p.type);
      if (isSwitch) { if (cur > 0) doneCount++; } else if (cur > 0) { doneCount++; }
      var dailyTxt = isSwitch ? ''
        : (p.dailyTarget > 0
            ? ('今日 ' + C.formatNumber(cur) + ' / ' + C.formatNumber(p.dailyTarget) + unit)
            : ('今日 ' + C.formatNumber(cur) + unit + '（未设每日量）'));
      var comp = C.calcCompletion(p.cumulativeTarget || 0, done, p.dailyTarget || 0, p.cumulativeDeadline || '', today);
      var pct = 0, remaining = '';
      if (comp.hasTarget) {
        pct = Math.max(0, Math.min(100, Math.round((comp.done / (p.cumulativeTarget || 1)) * 100)));
        remaining = comp.remaining > 0
          ? ('还剩 ' + C.formatNumber(comp.remaining) + unit + (comp.daysToDeadline != null ? (' · 剩 ' + comp.daysToDeadline + ' 天') : '') + (comp.paceText ? (' · ' + comp.paceText) : ''))
          : '已达成目标';
      }
      var step = Math.max(1, p.dailyTarget || 1);
      var btns = isSwitch
        ? '<button type="button" class="pg-btn tiny" data-pgtick="' + esc(p.id) + '" data-val="1" ' + (isReadOnly() ? 'disabled' : '') + '>' + (cur > 0 ? '已打卡' : '打卡') + '</button>'
        : '<button type="button" class="pg-btn tiny ghost" data-pgtick="' + esc(p.id) + '" data-val="' + step + '" ' + (isReadOnly() ? 'disabled' : '') + '>+' + C.formatNumber(step) + '</button>'
          // 每日量为 0/1 时不再重复给一个同值的「+1」
          + (step > 1 ? '<button type="button" class="pg-btn tiny ghost" data-pgtick="' + esc(p.id) + '" data-val="1" ' + (isReadOnly() ? 'disabled' : '') + '>+1</button>' : '');
      return '<div class="pg-row"><div class="pg-name"><b>' + esc(p.icon || '✅') + ' ' + esc(p.name) + '</b>'
        + '<div class="pg-meta">' + (isSwitch ? ('今日：' + (cur > 0 ? '已完成' : '未完成')) : dailyTxt)
        + (remaining ? '<br>' + esc(remaining) : '')
        + (comp.hasTarget ? '　（' + C.formatNumber(done) + ' / ' + C.formatNumber(p.cumulativeTarget) + '，' + pct + '%）' : '')
        + '</div>'
        + (comp.hasTarget ? '<div class="pg-bar"><i style="width:' + pct + '%"></i></div>' : '')
        + '</div><div class="pg-inline">' + btns + '</div></div>';
    }).join('');
    var dates = Object.keys(logsOf()).filter(function (d) { var day = logsOf()[d]; return day && Object.keys(day).length; });
    var streak = C.calcStreak(dates, today);
    return '<div class="pg-card"><div class="pg-h">今日功课 · ' + esc(today) + '</div>'
      + rows
      + '<p class="pg-hint">今日 ' + doneCount + ' / ' + arr.length + ' 项 · 连续 ' + streak + ' 天'
      + (isReadOnly() ? '　（设备免密为只读，打卡需登录）' : '') + '</p>'
      + (S.msg ? '<p class="pg-msg ' + (S.msgErr ? 'err' : 'ok') + '">' + esc(S.msg) + '</p>' : '')
      + '</div>' + viewMonth();
  }

  function viewMonth() {
    var today = (S.data && S.data.today) || C.getToday();
    var ym = (S.data && S.data.month) || today.slice(0, 7);
    var y = +ym.slice(0, 4), m = +ym.slice(5, 7);
    var first = new Date(y, m - 1, 1);
    var days = new Date(y, m, 0).getDate();
    var log = logsOf();
    var cells = [];
    for (var i = 0; i < first.getDay(); i++) cells.push('<div class="pg-day empty"></div>');
    for (var d = 1; d <= days; d++) {
      var ds = ym + '-' + (d < 10 ? '0' + d : d);
      var dayObj = log[ds];
      var filled = !!(dayObj && Object.keys(dayObj).length);
      var cls = 'pg-day' + (filled ? ' has' : '') + (ds === today ? ' today' : '');
      cells.push('<button type="button" class="' + cls + '" data-pgday="' + ds + '" ' + (isReadOnly() ? 'disabled' : '') + '>' + d + '</button>');
    }
    var head = ['日', '一', '二', '三', '四', '五', '六'].map(function (x) { return '<div class="pg-dayhead">' + x + '</div>'; }).join('');
    return '<div class="pg-card"><div class="pg-h">' + ym + ' 打卡月历</div>'
      + '<p class="pg-sub">点某天可补录（不能填未来）。有记录的日期以藏红标出。</p>'
      + '<div class="pg-month">' + head + cells.join('') + '</div></div>';
  }

  // ------------------------------------------------------------------ 渲染：管理
  function viewManage() {
    var arr = (S.data && S.data.practices) || [];
    var list = arr.length ? arr.map(function (p) {
      var comp = C.calcCompletion(p.cumulativeTarget || 0, doneOf(p.id), p.dailyTarget || 0, p.cumulativeDeadline || '', (S.data && S.data.today) || C.getToday());
      var plan = p.cumulativeTarget ? ('总目标 ' + C.formatNumber(p.cumulativeTarget) + (p.unit || '') + (p.cumulativeDeadline ? ('　截止 ' + p.cumulativeDeadline) : '') + (p.dailyTarget ? ('　每日 ' + C.formatNumber(p.dailyTarget)) : '（未设每日量）')) : '未设总目标';
      var pace = comp.hasTarget && comp.paceText ? ('　<span class="pg-pace-' + comp.pace + '">' + esc(comp.paceText) + '</span>') : '';
      return '<div class="pg-row"><div class="pg-name"><b>' + esc(p.icon || '✅') + ' ' + esc(p.name) + '</b>'
        + '<span class="pg-badge">' + esc(C.TYPES.filter(function (t) { return t.value === p.type; }).map(function (t) { return t.label; })[0] || p.type) + '</span>'
        + '<span class="pg-badge">' + esc(C.categoryLabel(p.category)) + '</span>'
        + (p.isActive === false ? '<span class="pg-badge">已停用</span>' : '')
        + '<div class="pg-meta">' + esc(plan) + pace + '</div></div>'
        + '<div class="pg-inline"><button type="button" class="pg-btn tiny ghost" data-pgedit="' + esc(p.id) + '">编辑</button>'
        + '<button type="button" class="pg-btn tiny ghost" data-pgtoggle="' + esc(p.id) + '">' + (p.isActive === false ? '启用' : '停用') + '</button>'
        + '<button type="button" class="pg-btn tiny ghost" data-pgdel="' + esc(p.id) + '">删除</button></div></div>';
    }).join('') : '<p class="pg-sub">还没有功课。点下方「新增功课」开始。</p>';

    return '<div class="pg-card"><div class="pg-h">功课管理</div>'
      + '<p class="pg-sub">共 ' + arr.length + ' 项。知识课「三维知二推一」：总量／截止日／每日量，填任意两个自动算出第三个。</p>'
      + list
      + '<div class="pg-inline" style="margin-top:.8rem"><button type="button" class="pg-btn" data-pgnew="1">＋ 新增功课</button></div>'
      + (S.msg ? '<p class="pg-msg ' + (S.msgErr ? 'err' : 'ok') + '">' + esc(S.msg) + '</p>' : '')
      + '</div>' + viewWizard();
  }

  function viewWizard() {
    if (!S.wiz) return '';
    var w = S.wiz, f = w.form;
    if (w.step === 1) {
      var tOpts = C.TYPES.map(function (t) { return '<option value="' + t.value + '"' + (f.type === t.value ? ' selected' : '') + '>' + t.label + ' — ' + t.desc + '</option>'; }).join('');
      var cOpts = C.CATEGORIES.map(function (c) { return '<option value="' + c.value + '"' + (f.category === c.value ? ' selected' : '') + '>' + c.label + '</option>'; }).join('');
      var icons = C.ICONS.map(function (ic) { return '<button type="button" class="pg-icon' + (f.icon === ic ? ' on' : '') + '" data-pgicon="' + ic + '">' + ic + '</button>'; }).join('');
      return '<div class="pg-card"><div class="pg-h">① 基本信息</div><div class="pg-wizard">'
        + '<div class="pg-field"><label>名称（≤30 字）</label><input class="pg-input" id="pgfName" value="' + esc(f.name) + '" maxlength="30" placeholder="如：莲师心咒"></div>'
        + '<div class="pg-field"><label>类型</label><select class="pg-select" id="pgfType">' + tOpts + '</select></div>'
        + '<div class="pg-field"><label>类目</label><select class="pg-select" id="pgfCat">' + cOpts + '</select></div>'
        + '<div class="pg-field"><label>单位（如 遍 / 分钟 / 次）</label><input class="pg-input" id="pgfUnit" value="' + esc(f.unit) + '" maxlength="8" placeholder="遍"></div>'
        + '<div class="pg-field"><label>图标</label><div class="pg-icons" id="pgfIcons">' + icons + '</div></div>'
        + '</div><div class="pg-inline" style="margin-top:.8rem"><button type="button" class="pg-btn" data-pgwnext="1">下一步</button>'
        + '<button type="button" class="pg-btn ghost" data-pgwcancel="1">取消</button></div>'
        + (S.msg ? '<p class="pg-msg ' + (S.msgErr ? 'err' : 'ok') + '">' + esc(S.msg) + '</p>' : '') + '</div>';
    }
    // step 2：目标方式（知二推一）
    var mode = f.mode;
    var hint = '';
    if (mode === 'deadline' && f.cumulativeTarget && f.cumulativeDeadline) {
      var r1 = C.deriveDailyFromDeadline(f.cumulativeTarget, f.cumulativeDeadline, (S.data && S.data.today) || C.getToday());
      hint = r1.ok ? r1.hint : r1.hint;
    } else if (mode === 'daily' && f.cumulativeTarget && f.dailyTarget) {
      var r2 = C.deriveDeadlineFromDaily(f.cumulativeTarget, f.dailyTarget, (S.data && S.data.today) || C.getToday());
      hint = r2.ok ? r2.hint : '';
    }
    return '<div class="pg-card"><div class="pg-h">② 目标方式（知二推一）</div>'
      + '<div class="pg-mode"><button type="button" class="pg-btn' + (mode === 'deadline' ? '' : ' ghost') + '" data-pgmode="deadline">按结束日期</button>'
      + '<button type="button" class="pg-btn' + (mode === 'daily' ? '' : ' ghost') + '" data-pgmode="daily">按每日量</button></div>'
      + '<div class="pg-wizard" style="margin-top:.8rem">'
      + '<div class="pg-field"><label>总目标 N</label><input class="pg-input" id="pgfTot" type="number" min="0" value="' + esc(f.cumulativeTarget) + '"></div>'
      + (mode === 'deadline'
        ? '<div class="pg-field"><label>截止日期 D</label><input class="pg-input" id="pgfDl" type="date" value="' + esc(f.cumulativeDeadline) + '"></div>'
          + '<div class="pg-field"><label>每日达成量 M（自动）</label><input class="pg-input" id="pgfDaily" readonly value="' + esc(f.derivedDaily || '') + '"><span class="pg-badge">自动</span></div>'
        : '<div class="pg-field"><label>每日达成量 M</label><input class="pg-input" id="pgfDaily" type="number" min="1" value="' + esc(f.dailyTarget) + '"></div>'
          + '<div class="pg-field"><label>预计完成日（自动）</label><input class="pg-input" id="pgfDl" readonly value="' + esc(f.derivedDeadline || '') + '"><span class="pg-badge">自动</span></div>')
      + '</div>'
      + (hint ? '<p class="pg-hint">' + esc(hint) + '</p>' : '<p class="pg-hint">填「总目标 + 另一项」即可自动算出第三项。</p>')
      + '<div class="pg-inline" style="margin-top:.8rem"><button type="button" class="pg-btn" data-pgwsave="1">保存</button>'
      + '<button type="button" class="pg-btn ghost" data-pgwback="1">上一步</button>'
      + '<button type="button" class="pg-btn ghost" data-pgwcancel="1">取消</button></div>'
      + (S.msg ? '<p class="pg-msg ' + (S.msgErr ? 'err' : 'ok') + '">' + esc(S.msg) + '</p>' : '') + '</div>';
  }

  // ------------------------------------------------------------------ 渲染：统计
  function viewStats() {
    var arr = (S.data && S.data.practices) || [];
    var today = (S.data && S.data.today) || C.getToday();
    var log = logsOf();
    var dates = Object.keys(log).filter(function (d) { return log[d] && Object.keys(log[d]).length; });
    var streak = C.calcStreak(dates, today);
    var ym = (S.data && S.data.month) || today.slice(0, 7);
    var daysInMonth = new Date(+ym.slice(0, 4), +ym.slice(5, 7), 0).getDate();
    var filledDays = dates.filter(function (d) { return d.slice(0, 7) === ym; }).length;
    var rows = arr.map(function (p) {
      var done = doneOf(p.id);
      var comp = C.calcCompletion(p.cumulativeTarget || 0, done, p.dailyTarget || 0, p.cumulativeDeadline || '', today);
      var pct = comp.hasTarget ? Math.max(0, Math.min(100, Math.round((comp.done / (p.cumulativeTarget || 1)) * 100))) : 0;
      // 括号易错，拆开写：有总目标才拼「累计 x / N　剩 y（约 z 天）」
      var cumTxt = '';
      if (comp.hasTarget) {
        cumTxt = ' / ' + C.formatNumber(p.cumulativeTarget) + '　剩 ' + C.formatNumber(comp.remaining);
        if (comp.remainingDays != null) cumTxt += '（约 ' + comp.remainingDays + ' 天）';
      }
      return '<div class="pg-row"><div class="pg-name"><b>' + esc(p.icon || '✅') + ' ' + esc(p.name) + '</b>'
        + '<div class="pg-meta pg-num">累计 ' + C.formatNumber(done) + (p.unit || '')
        + cumTxt
        + (comp.estimatedDate ? ('　预计 ' + esc(comp.estimatedDate)) : '')
        + (comp.paceText ? '　<span class="pg-pace-' + comp.pace + '">' + esc(comp.paceText) + '</span>' : '')
        + '</div>' + (comp.hasTarget ? '<div class="pg-bar"><i style="width:' + pct + '%"></i></div>' : '') + '</div></div>';
    }).join('');
    return '<div class="pg-card"><div class="pg-h">统计 · ' + esc(ym) + '</div>'
      + '<p class="pg-sub pg-num">连续打卡 <b>' + streak + '</b> 天　·　本月已填 <b>' + filledDays + '</b> / ' + daysInMonth + ' 天</p>'
      + (rows || '<p class="pg-sub">还没有功课。</p>') + '</div>';
  }

  // ------------------------------------------------------------------ 渲染：工具
  function viewTools() {
    var arr = ((S.data && S.data.practices) || []).filter(function (p) { return p.isActive !== false; });
    var opts = arr.map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.name) + (p.unit ? ('（' + esc(p.unit) + '）') : '') + '</option>'; }).join('');
    var cd = arr.filter(function (p) { return p.type === 'count'; });
    return '<div class="pg-card"><div class="pg-h">计数器</div>'
      + '<div class="pg-field"><label>绑定功课</label><select class="pg-select" id="pgcSel">' + (opts || '<option value="">（先添加计数类功课）</option>') + '</select></div>'
      + '<div class="pg-big pg-num" id="pgcNum">0</div>'
      + '<div class="pg-inline"><button type="button" class="pg-btn" id="pgcAdd">＋1</button>'
      + '<button type="button" class="pg-btn ghost" id="pgcAdd10">＋10</button>'
      + '<button type="button" class="pg-btn ghost" id="pgcReset">归零</button>'
      + '<button type="button" class="pg-btn" id="pgcSave" ' + (isReadOnly() ? 'disabled' : '') + '>记入今日</button></div>'
      + '<p class="pg-hint">' + (cd.length ? '' : '计数类功课：') + '计数只在点「记入今日」时写库，中途刷新不丢（本机暂存）。</p></div>'
      + '<div class="pg-card"><div class="pg-h">静坐 / 计时</div>'
      + '<div class="pg-field"><label>记入功课（计时类）</label><select class="pg-select" id="pgtSel">' + (opts || '<option value="">（先添加计时类功课）</option>') + '</select></div>'
      + '<div class="pg-big pg-num" id="pgtNum">00:00</div>'
      + '<div class="pg-inline"><button type="button" class="pg-btn" id="pgtStart">开始</button>'
      + '<button type="button" class="pg-btn ghost" id="pgtStop">暂停</button>'
      + '<button type="button" class="pg-btn ghost" id="pgtZero">归零</button>'
      + '<button type="button" class="pg-btn" id="pgtSave" ' + (isReadOnly() ? 'disabled' : '') + '>记入今日</button></div>'
      + '<p class="pg-hint">正计时，单位为分钟（不足 1 分钟按 1 分钟记）。</p></div>';
  }

  // ------------------------------------------------------------------ 渲染：导出
  function viewSettings() {
    var q = readQueue();
    return '<div class="pg-card"><div class="pg-h">数据导出</div>'
      + '<p class="pg-sub">导出为 JSON（备份/再导入）、CSV（表格分析）、Markdown（存进 Obsidian）。**仅本人数据**。</p>'
      + '<div class="pg-inline"><button type="button" class="pg-btn ghost" data-pgexp="json">JSON</button>'
      + '<button type="button" class="pg-btn ghost" data-pgexp="csv">CSV</button>'
      + '<button type="button" class="pg-btn ghost" data-pgexp="md">Markdown</button></div>'
      + '</div><div class="pg-card"><div class="pg-h">离线待发</div>'
      + '<p class="pg-sub">断网时打卡会先存在本机，联网后自动重放（以日期＋功课为键，不重复计数）。</p>'
      + '<p class="pg-hint">当前待发 ' + q.length + ' 条。<button type="button" class="pg-btn tiny ghost" id="pgFlush">立即重试</button></p>'
      + '</div><div class="pg-card"><div class="pg-h">隐私</div>'
      + '<p class="pg-sub">功课数量属隐私：不进入站点埋点，不进 knowledge.json，也不出现在任何公开统计里。设备免密访问只能看、不能改。</p></div>';
  }

  function renderBody() {
    var box = document.getElementById('pgBody');
    if (!box) return;
    if (!S.data) {
      // 无数据只有两种可能：还在加载，或加载失败/未获授权。
      // 后者必须给出可读文案＋重试按钮 —— 否则 S.msg 只在各视图内部渲染，
      // 页面会永远停在「加载中…」（永久转圈，用户不知道发生了什么）。
      box.innerHTML = S.loadErr
        ? '<div class="pg-card"><p class="pg-msg err">' + esc(S.loadErr) + '</p>'
          + '<p class="pg-hint"><button type="button" class="pg-btn tiny ghost" id="pgRetry">重试</button></p></div>'
        : '<p class="pg-sub">加载中…</p>';
      var rb = document.getElementById('pgRetry');
      if (rb) rb.addEventListener('click', function () { S.loadErr = ''; initLoad(); });
      return;
    }
    var html = S.view === 'manage' ? viewManage()
      : S.view === 'stats' ? viewStats()
        : S.view === 'tools' ? viewTools()
          : S.view === 'settings' ? viewSettings()
            : viewToday();
    box.innerHTML = html;
    bindBody();
  }

  // ------------------------------------------------------------------ 交互
  function refresh() {
    return api('list', {}).then(function (j) {
      if (!j || !j.success) {
        var st = j && j._status;
        // 401/403 是「根本没拿到身份」，必须清空数据让 renderBody 走错误分支；
        // 其它失败保留已有数据，只在视图内提示，不至于把已看到的内容抹掉。
        S.loadErr = (j && j.message) || (st === 401 ? '登录已过期，请重新登录后访问。'
          : st === 403 ? '本设备未获授权：设备免密只读需先在后台登记。'
            : '加载失败，请刷新重试。');
        S.msg = S.loadErr; S.msgErr = true;
        if (st === 401 || st === 403) { S.data = null; }
        return;
      }
      S.loadErr = '';
      S.data = j;
    });
  }

  // 首屏/重试共用：先重放离线队列，再拉数据，最后渲染
  function initLoad() {
    renderBody();
    return flushQueue().then(function () { return refresh(); }).then(function () { renderBody(); })
      .catch(function () {
        S.loadErr = '网络异常，加载失败，请刷新重试。';
        S.msg = S.loadErr; S.msgErr = true;
        S.data = null;
        renderBody();
      });
  }

  function bindBody() {
    var box = document.getElementById('pgBody');
    if (!box) return;
    // 委托监听只绑一次（#pgBody 元素不随 innerHTML 替换而变）
    if (!box._pgBound) {
      box._pgBound = true;
      box.addEventListener('click', function (e) {
        var t = e.target.closest('button');
        if (!t) return;
        var a = function (k) { return t.getAttribute(k); };
        if (a('data-pgtick')) { doTick(a('data-pgtick'), +a('data-val')); return; }
        if (a('data-pgday')) { doDay(a('data-pgday')); return; }
        if (a('data-pgnew')) { S.wiz = { step: 1, form: { name: '', type: 'count', category: 'mantra', icon: '📿', unit: '遍', cumulativeTarget: '', cumulativeDeadline: '', dailyTarget: '', mode: 'deadline' } }; S.msg = ''; renderBody(); return; }
        if (a('data-pgedit')) { openEdit(a('data-pgedit')); return; }
        if (a('data-pgtoggle')) { doToggle(a('data-pgtoggle')); return; }
        if (a('data-pgdel')) { doDelete(a('data-pgdel')); return; }
        if (a('data-pgicon')) { S.wiz.form.icon = a('data-pgicon'); renderBody(); return; }
        if (a('data-pgmode')) { S.wiz.form.mode = a('data-pgmode'); S.msg = ''; wizRederive(); renderBody(); return; }
        if (a('data-pgwnext')) { wizNext(); return; }
        if (a('data-pgwback')) { S.wiz.step = 1; S.msg = ''; renderBody(); return; }
        if (a('data-pgwcancel')) { S.wiz = null; S.msg = ''; renderBody(); return; }
        if (a('data-pgwsave')) { wizSave(); return; }
        if (a('data-pgexp')) { doExport(a('data-pgexp')); return; }
      });
      box.addEventListener('input', function (e) {
        if (!S.wiz) return;
        var f = S.wiz.form, id = e.target.id;
        if (id === 'pgfName') f.name = e.target.value;
        else if (id === 'pgfUnit') f.unit = e.target.value;
        else if (id === 'pgfTot') f.cumulativeTarget = e.target.value;
        else if (id === 'pgfDl') f.cumulativeDeadline = e.target.value;
        else if (id === 'pgfDaily') f.dailyTarget = e.target.value;
        else return;
        if (S.wiz.step === 2) { wizRederive(); var d = document.getElementById('pgfDaily'); var l = document.getElementById('pgfDl'); if (d) d.value = f.derivedDaily || f.dailyTarget || ''; if (l) l.value = f.derivedDeadline || f.cumulativeDeadline || ''; }
      });
      box.addEventListener('change', function (e) {
        if (!S.wiz) return;
        var f = S.wiz.form;
        if (e.target.id === 'pgfType') { f.type = e.target.value; if (!C.isSwitchLike(f.type) && !f.unit) f.unit = '遍'; renderBody(); }
        else if (e.target.id === 'pgfCat') f.category = e.target.value;
      });
    }
    // 工具区：元素每次渲染都是新的 → 必须每次重绑（不能跟着 _pgBound 一起早退）
    bindTools();
  }

  function bindTools() {
    var cAdd = document.getElementById('pgcAdd');
    if (cAdd) {
      var upd = function () { var n = document.getElementById('pgcNum'); if (n) n.textContent = C.formatNumber(S.counter); };
      cAdd.addEventListener('click', function () { S.counter++; try { localStorage.setItem('practice_counter', String(S.counter)); } catch (e2) {} upd(); });
      document.getElementById('pgcAdd10').addEventListener('click', function () { S.counter += 10; try { localStorage.setItem('practice_counter', String(S.counter)); } catch (e2) {} upd(); });
      document.getElementById('pgcReset').addEventListener('click', function () { S.counter = 0; try { localStorage.removeItem('practice_counter'); } catch (e2) {} upd(); });
      document.getElementById('pgcSave').addEventListener('click', function () { doCounterSave(); });
      upd();
    }
    var tStart = document.getElementById('pgtStart');
    if (tStart) {
      var show = function () { var n = document.getElementById('pgtNum'); if (!n) return; var m = Math.floor(S.timerSec / 60), s2 = S.timerSec % 60; n.textContent = (m < 10 ? '0' : '') + m + ':' + (s2 < 10 ? '0' : '') + s2; };
      tStart.addEventListener('click', function () { if (S.timerRun) return; S.timerRun = true; S.timer = setInterval(function () { S.timerSec++; show(); }, 1000); });
      document.getElementById('pgtStop').addEventListener('click', function () { S.timerRun = false; if (S.timer) { clearInterval(S.timer); S.timer = null; } });
      document.getElementById('pgtZero').addEventListener('click', function () { S.timerRun = false; if (S.timer) { clearInterval(S.timer); S.timer = null; } S.timerSec = 0; show(); });
      document.getElementById('pgtSave').addEventListener('click', function () { doTimerSave(); });
      show();
    }
    var fl = document.getElementById('pgFlush');
    if (fl) fl.addEventListener('click', function () { flushQueue().then(function (n) { S.msg = '已重放 ' + n + ' 条'; S.msgErr = false; refresh().then(renderBody); }); });
  }

  function doTick(pid, val) {
    var p = practiceById(pid);
    if (!p) return;
    if (isReadOnly()) { S.msg = '设备免密为只读，打卡需登录'; S.msgErr = true; renderBody(); return; }
    var today = (S.data && S.data.today) || C.getToday();
    var dayLog = logsOf()[today] || {};
    var cur = dayLog[pid] ? Number(dayLog[pid].value) : 0;   // 前端所知的服务端当天值
    var isSwitch = C.isSwitchLike(p.type);
    // 在线走 add（与服务端真值合并）；离线入队走 base+delta（绝对量，重放幂等）
    var live = { date: today, practiceId: pid, value: val, mode: isSwitch ? 'set' : 'add' };
    var queued = { date: today, practiceId: pid, base: isSwitch ? 0 : cur, delta: isSwitch ? 1 : val };
    api('checkin', live).then(function (j) {
      if (j && j.success) { S.msg = '已记录'; S.msgErr = false; return refresh(); }
      enqueue(queued);
      S.msg = ((j && j.message) || '保存失败') + '　已暂存本机，联网后自动重试';
      S.msgErr = true;
    }).then(function () { renderBody(); })
      .catch(function () { enqueue(queued); S.msg = '网络异常，已暂存本机，联网后自动重试'; S.msgErr = true; renderBody(); });
  }

  function doDay(ds) {
    var arr = ((S.data && S.data.practices) || []).filter(function (p) { return p.isActive !== false; });
    if (!arr.length) return;
    var p = arr[0];
    var v = prompt('补录「' + p.name + '」在 ' + ds + ' 的数量（' + (p.unit || '') + '）：', '');
    if (v === null) return;
    api('checkin', { date: ds, practiceId: p.id, value: Number(v) || 0, mode: 'set' }).then(function (j) {
      S.msg = (j && j.success) ? ('已补录 ' + ds) : ((j && j.message) || '补录失败');
      S.msgErr = !(j && j.success);
      if (j && j.success) return refresh();
    }).then(function () { renderBody(); });
  }

  function openEdit(id) {
    var p = practiceById(id);
    if (!p) return;
    S.wiz = {
      step: 1, id: id,
      form: {
        name: p.name || '', type: p.type, category: p.category || 'other', icon: p.icon || '✅', unit: p.unit || '',
        cumulativeTarget: p.cumulativeTarget ? String(p.cumulativeTarget) : '',
        cumulativeDeadline: p.cumulativeDeadline || '',
        dailyTarget: p.dailyTarget ? String(p.dailyTarget) : '',
        mode: p.cumulativeDeadline ? 'deadline' : 'daily'
      }
    };
    S.msg = ''; renderBody();
  }

  function doToggle(id) {
    var p = practiceById(id);
    if (!p) return;
    api('save', { practice: { id: id, name: p.name, type: p.type, category: p.category, icon: p.icon, unit: p.unit, dailyTarget: p.dailyTarget || 0, cumulativeTarget: p.cumulativeTarget || 0, cumulativeDeadline: p.cumulativeDeadline || '', isActive: p.isActive === false, sortOrder: p.sortOrder || 0 } })
      .then(function (j) { S.msg = j && j.success ? '已更新' : ((j && j.message) || '更新失败'); S.msgErr = !(j && j.success); return refresh(); })
      .then(function () { renderBody(); });
  }

  function doDelete(id) {
    var p = practiceById(id);
    if (!p) return;
    if (!confirm('删除「' + p.name + '」？历史打卡记录会保留。')) return;
    api('delete', { id: id }).then(function (j) {
      S.msg = j && j.success ? '已删除' : ((j && j.message) || '删除失败');
      S.msgErr = !(j && j.success);
      return refresh();
    }).then(function () { renderBody(); });
  }

  function wizRederive() {
    var f = S.wiz.form, today = (S.data && S.data.today) || C.getToday();
    f.derivedDaily = ''; f.derivedDeadline = '';
    if (C.isSwitchLike(f.type)) return;
    if (f.mode === 'deadline' && f.cumulativeTarget && f.cumulativeDeadline) {
      var r = C.deriveDailyFromDeadline(f.cumulativeTarget, f.cumulativeDeadline, today);
      if (r.ok) f.derivedDaily = String(r.daily);
    } else if (f.mode === 'daily' && f.cumulativeTarget && f.dailyTarget) {
      var r2 = C.deriveDeadlineFromDaily(f.cumulativeTarget, f.dailyTarget, today);
      if (r2.ok) f.derivedDeadline = r2.deadline;
    }
  }

  function wizNext() {
    var f = S.wiz.form;
    if (!String(f.name || '').trim()) { S.msg = '先给功课起个名字'; S.msgErr = true; renderBody(); return; }
    S.wiz.step = 2; S.msg = ''; wizRederive(); renderBody();
  }

  function wizSave() {
    var f = S.wiz.form, today = (S.data && S.data.today) || C.getToday();
    wizRederive();
    var out = {
      id: S.wiz.id || '',
      name: String(f.name).trim(), type: f.type, category: f.category, icon: f.icon, unit: f.unit,
      cumulativeTarget: Number(f.cumulativeTarget) || 0,
      dailyTarget: Number(f.dailyTarget) || 0,
      cumulativeDeadline: f.cumulativeDeadline || ''
    };
    if (C.isSwitchLike(f.type)) { out.cumulativeTarget = 0; out.dailyTarget = 0; out.cumulativeDeadline = ''; }
    if (f.mode === 'deadline' && f.derivedDaily) out.dailyTarget = Number(f.derivedDaily) || 0;
    if (f.mode === 'daily' && f.derivedDeadline) out.cumulativeDeadline = f.derivedDeadline;
    api('save', { practice: out }).then(function (j) {
      S.msg = j && j.success ? '已保存' : ((j && j.message) || '保存失败');
      S.msgErr = !(j && j.success);
      if (j && j.success) { S.wiz = null; return refresh(); }
    }).then(function () { renderBody(); });
  }

  function doCounterSave() {
    if (!S.counter) { S.msg = '计数为 0'; S.msgErr = true; renderBody(); return; }
    var sel = document.getElementById('pgcSel');
    var pid = sel && sel.value;
    if (!pid) { S.msg = '请先选择绑定的功课'; S.msgErr = true; renderBody(); return; }
    api('checkin', { date: (S.data && S.data.today) || C.getToday(), practiceId: pid, value: S.counter, mode: 'add' }).then(function (j) {
      S.msg = j && j.success ? ('已记入 ' + S.counter) : ((j && j.message) || '保存失败');
      S.msgErr = !(j && j.success);
      if (j && j.success) { S.counter = 0; try { localStorage.removeItem('practice_counter'); } catch (e2) {} return refresh(); }
    }).then(function () { renderBody(); });
  }

  function doTimerSave() {
    var sel = document.getElementById('pgtSel');
    var pid = sel && sel.value;
    if (!pid) { S.msg = '请先选择绑定的功课'; S.msgErr = true; renderBody(); return; }
    var mins = Math.max(1, Math.round(S.timerSec / 60));
    api('checkin', { date: (S.data && S.data.today) || C.getToday(), practiceId: pid, value: mins, mode: 'add' }).then(function (j) {
      S.msg = j && j.success ? ('已记入 ' + mins + ' 分钟') : ((j && j.message) || '保存失败');
      S.msgErr = !(j && j.success);
      if (j && j.success) { S.timerSec = 0; S.timerRun = false; if (S.timer) { clearInterval(S.timer); S.timer = null; } return refresh(); }
    }).then(function () { renderBody(); });
  }

  function doExport(fmt) {
    // 走同源代理：token 由中间件从 Cookie 注入，前端不传任何身份
    var eh = {};
    var did = deviceId();
    if (did) eh['X-Device-ID'] = did;
    fetch('/__api/practice/export?format=' + fmt, { method: 'GET', credentials: 'same-origin', headers: eh })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); })
      .then(function (b) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(b);
        a.download = 'practice.' + fmt;
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
      })
      .catch(function (e) { S.msg = '导出失败：' + e.message; S.msgErr = true; renderBody(); });
  }

  // ------------------------------------------------------------------ 初始化
  function initPracticePage() {
    ensureCSS();
    try { S.counter = Number(localStorage.getItem('practice_counter') || 0) || 0; } catch (e) {}
    // 每次进入都从「今日」开始（hash 路由语义：进出＝重新进入该页）
    S.view = 'today'; S.msg = ''; S.msgErr = false; S.wiz = null;
    bindShell();
    S.data = null; S.loadErr = '';
    initLoad();
  }

  root.renderPracticePage = renderPracticePage;
  root.initPracticePage = initPracticePage;
})(typeof window !== 'undefined' ? window : this);
