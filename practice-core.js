/**
 * practice-core.js —— 功课模块核心算法（单一来源）
 *
 * 定位：本文件是「功课模块」的**唯一算法来源**。
 *   · build_site.py 会把本文件内容内联进 PRACTICE_PAGE_JS（前端用）
 *   · Node 可直接 require 本文件做单元测试，并与小程序 utils/util.js 逐位比对
 *   ⇒ 改一处两端生效，杜绝「两处实现漂移」。
 *
 * ⚠️ 口径红线（小谦 2026-09-22 决定 D1／D2／D3）：
 *   D1「剩余天数不含今天」→ daysBetween(today, D) **禁止 +1**；
 *      与小程序对同一输入必须算出同一个每日量。
 *   D2 移植 pace 六态（含文案）。
 *   D3 过期未达成 → 视为需全部完成，并给「一键改期」入口。
 *
 * ⚠️ 日期纪律：一律「本地日期字符串 → 当天 0 点」归一后取整天差。
 *   使用 new Date(s + 'T00:00:00')（本地午夜），**禁止** new Date('YYYY-MM-DD')
 *   （后者按 UTC 解析，在东八区外的时区会差一天）；也禁止直接用时间戳相减。
 *
 * 算法与字段口径均取自活跃小程序项目
 *   C:\Users\Drime\.qclaw\workspace\projects\qianwanxing-miniprogram
 *   （miniprogram/utils/util.js · miniprogram/pages/settings/practice/practice_settings.js）
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PracticeCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DAY = 1000 * 60 * 60 * 24;

  // ---------------------------------------------------------------- 基础日期
  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function formatDate(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function getToday() { return formatDate(new Date()); }

  /** 本地午夜 Date（东八区外也稳定） */
  function toLocalMidnight(s) {
    if (s instanceof Date) s = formatDate(s);
    return new Date(String(s) + 'T00:00:00');
  }

  /** date2 - date1 的整天差（**不含今天** 的语义由此保证：daysBetween(today, D) = D - today） */
  function daysBetween(date1, date2) {
    return Math.round((toLocalMidnight(date2) - toLocalMidnight(date1)) / DAY);
  }

  /** 在日期上加天数，返回 'YYYY-MM-DD' */
  function addDays(dateStr, days) {
    var d = toLocalMidnight(dateStr);
    d.setDate(d.getDate() + days);
    return formatDate(d);
  }

  // ---------------------------------------------------------------- 三维知二推一
  /**
   * 已知 总量 N + 截止日 D → 每日量 M
   * 小程序口径（practice_settings.js onDeadlineChange）：
   *   days = daysBetween(today, D); days > 0 时 M = ceil(N / days)
   * ⚠️ 用的是**总量 N**（不是剩余量 R）——忠实移植，勿"顺手改正"。
   */
  function deriveDailyFromDeadline(total, deadline, today) {
    today = today || getToday();
    var n = Number(total) || 0;
    if (!deadline || n <= 0) return { ok: false, reason: 'missing', daily: 0, days: 0, hint: '' };
    var days = daysBetween(today, deadline);
    if (days <= 0) return { ok: false, reason: 'past', daily: 0, days: days, hint: '结束日期需晚于今天' };
    var daily = Math.ceil(n / days);
    return { ok: true, daily: daily, days: days, hint: '按此目标，每天需完成 ' + daily + '（共 ' + days + ' 天）' };
  }

  /**
   * 已知 总量 N + 每日量 M → 截止日 D
   * 小程序口径（onDailyTargetInput）：days = ceil(N / M); D = addDays(today, days)
   * ⚠️ 是 addDays(today, days)，**不是** addDays(today, days - 1)。
   */
  function deriveDeadlineFromDaily(total, daily, today) {
    today = today || getToday();
    var n = Number(total) || 0;
    var m = Number(daily) || 0;
    if (n <= 0 || m <= 0) return { ok: false, reason: 'missing', deadline: '', days: 0, hint: '' };
    var days = Math.ceil(n / m);
    var deadline = addDays(today, days);
    return { ok: true, deadline: deadline, days: days, hint: '按此进度，预计 ' + deadline + ' 完成（约 ' + days + ' 天）' };
  }

  /**
   * 「智能每日目标」（今日页展示用）—— 用**剩余量 R**
   * 小程序口径（util.js calcSmartDailyTarget）：过期(remainDays<=0) 时返回**剩余全部**。
   */
  function calcSmartDailyTarget(cumulativeTarget, currentTotal, deadline, today) {
    today = today || getToday();
    var target = Number(cumulativeTarget) || 0;
    if (target <= 0) return 0;
    var remaining = target - (Number(currentTotal) || 0);
    if (remaining <= 0) return 0;
    if (!deadline) return 0;                       // 无截止日期不计算
    var remainDays = daysBetween(today, deadline);
    if (remainDays <= 0) return remaining;         // D3：已过期 → 需全部完成
    return Math.ceil(remaining / remainDays);
  }

  // ---------------------------------------------------------------- 达成节奏
  var PACE_TEXT = {
    done: '已达成目标',
    ahead: '已超前计划',
    onTrack: '按当前节奏可按时达成',
    behind: '进度偏慢，需加快',
    expired: '已过希望完成日期',
    none: ''
  };

  /**
   * 达成情况 + 节奏判断
   * @returns {hasTarget, done, remaining, remainingDays, estimatedDate,
   *           hasDeadline, daysToDeadline, pace, paceText}
   *   pace: 'done'|'ahead'|'onTrack'|'behind'|'expired'|'none'
   *
   * ⚠️ 移植说明（实测发现，勿"修好它"）：小程序 calcCompletion() 的枚举里**有** ahead，
   *   但实现里**从不赋值** → 实际可达状态是 5 个（done/onTrack/behind/expired/none）。
   *   本移植保持一致：ahead 保留在枚举与文案表中，逻辑分支不变，避免与小程序产生口径差。
   */
  function calcCompletion(cumulativeTarget, currentTotal, dailyTarget, deadline, today) {
    today = today || getToday();
    var target = Number(cumulativeTarget) || 0;
    var done = Number(currentTotal) || 0;
    if (target <= 0) return { hasTarget: false };

    var remaining = target - done;
    var remainingDays = null;
    var estimatedDate = '';

    if (remaining <= 0) {
      remainingDays = 0;
      estimatedDate = '已达成';
    } else if (dailyTarget && dailyTarget > 0) {
      remainingDays = Math.ceil(remaining / dailyTarget);
      estimatedDate = addDays(today, remainingDays);
    }

    var hasDeadline = false;
    var daysToDeadline = null;
    var pace = 'none';
    var paceText = '';

    if (deadline) {
      hasDeadline = true;
      daysToDeadline = daysBetween(today, deadline);      // 不含今天
      if (remaining <= 0) {
        pace = 'done'; paceText = PACE_TEXT.done;
      } else if (daysToDeadline < 0) {
        pace = 'expired'; paceText = PACE_TEXT.expired;
      } else if (remainingDays != null) {
        if (remainingDays <= daysToDeadline) { pace = 'onTrack'; paceText = PACE_TEXT.onTrack; }
        else { pace = 'behind'; paceText = PACE_TEXT.behind; }
      }
    } else if (remaining <= 0) {
      pace = 'done'; paceText = PACE_TEXT.done;
    }

    // 没有每日量但有截止日期时，预计日期即目标日期
    if (!estimatedDate && hasDeadline && remaining > 0) estimatedDate = deadline;

    return {
      hasTarget: true, done: done, remaining: remaining,
      remainingDays: remainingDays, estimatedDate: estimatedDate,
      hasDeadline: hasDeadline, daysToDeadline: daysToDeadline,
      pace: pace, paceText: paceText
    };
  }

  /** 连续打卡天数（须今天或昨天有记录） */
  function calcStreak(dates, today) {
    today = today || getToday();
    var uniq = [];
    var seen = {};
    (dates || []).forEach(function (d) {
      if (d && !seen[d]) { seen[d] = 1; uniq.push(d); }
    });
    if (!uniq.length) return 0;
    uniq.sort().reverse();
    var yesterday = addDays(today, -1);
    if (uniq[0] !== today && uniq[0] !== yesterday) return 0;
    var streak = 1;
    for (var i = 1; i < uniq.length; i++) {
      if (daysBetween(uniq[i], uniq[i - 1]) === 1) streak++;
      else break;
    }
    return streak;
  }

  // ---------------------------------------------------------------- 显示格式化
  function formatNumber(num) {
    if (num === undefined || num === null) return '0';
    return String(num).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function formatDuration(minutes) {
    var m0 = Number(minutes) || 0;
    if (!m0) return '0分钟';
    if (m0 < 60) return m0 + '分钟';
    var h = Math.floor(m0 / 60), m = m0 % 60;
    return m > 0 ? (h + '小时' + m + '分钟') : (h + '小时');
  }

  // ---------------------------------------------------------------- 选项常量
  /** type 口径：小程序向导写 'switch'，但存量数据里是 'checkbox'（7 条）→ 两者等价 */
  var TYPES = [
    { value: 'switch',   label: '打卡', desc: '做了 / 没做，如早课、发愿' },
    { value: 'count',    label: '计数', desc: '计次数，如心咒、大拜' },
    { value: 'duration', label: '计时', desc: '记时长，如静坐、听开示' }
  ];
  var SWITCH_LIKE = { switch: 1, checkbox: 1 };
  function isSwitchLike(type) { return !!SWITCH_LIKE[type]; }

  /** 类目：以存量数据实际取值为准（daily 14 / mantra 10 / offering 4 / study 3），另留扩展 */
  var CATEGORIES = [
    { value: 'mantra',   label: '持咒' },
    { value: 'daily',    label: '日常' },
    { value: 'offering', label: '供养' },
    { value: 'study',    label: '闻思' },
    { value: 'body',     label: '身体' },
    { value: 'mind',     label: '观修' },
    { value: 'other',    label: '其他' }
  ];
  function categoryLabel(v) {
    for (var i = 0; i < CATEGORIES.length; i++) if (CATEGORIES[i].value === v) return CATEGORIES[i].label;
    return v || '其他';
  }

  var ICONS = [
    '🙏', '📿', '🪔', '🔥', '🧘', '🧘‍♂️', '🧘‍♀️', '🪷', '🐚', '🔔', '🕯️', '⏳', '⌛', '🪬', '🏵️', '🎶',
    '🥁', '🫧', '🧿', '🐉', '🦅', '🦁', '🐘', '🦚', '🦢', '🐢', '🐝', '🌾', '🍀', '☘️', '🕊️', '💫',
    '🌅', '🌄', '🌊', '🌌', '☀️', '🌞', '🌤️', '⛅', '🌦️', '🌧️', '❄️', '⛄', '🌈', '🌠', '🌃', '🌇',
    '🌉', '🌁', '🌙', '⭐', '🌟', '✨', '🌿', '🌱', '🌳', '🌲', '🌷', '🌸', '🌺', '🍃', '🍵', '🌻',
    '🏔️', '🗻', '⛰️', '🏞️', '🏝️', '🏜️', '🌋', '🗿', '🏯', '⛩️', '🛕', '🎐', '🎋', '🎏', '🎑', '🪵',
    '✅', '💧', '📖', '🏃', '⏰', '✍️', '🎯', '💪', '🎨', '🎵', '🛌', '🥗', '🚶', '📝', '📚', '🎓',
    '💡', '🦋', '🐦', '🏋️', '🚴', '🛏️', '🛋️', '🚿', '🧼', '💰', '💎', '🔑', '📱', '💻', '📷', '🎧',
    '🎤', '🎹', '🎸', '🥋', '🏊', '🏓', '🍚', '🥛', '🍬', '🏠', '🚗', '🛵', '🚲', '🕐', '🕒', '🕕',
    '🕘', '🕛'
  ];

  return {
    // 日期
    formatDate: formatDate, getToday: getToday, daysBetween: daysBetween, addDays: addDays,
    // 推算
    deriveDailyFromDeadline: deriveDailyFromDeadline,
    deriveDeadlineFromDaily: deriveDeadlineFromDaily,
    calcSmartDailyTarget: calcSmartDailyTarget,
    // 节奏
    calcCompletion: calcCompletion, calcStreak: calcStreak, PACE_TEXT: PACE_TEXT,
    // 显示
    formatNumber: formatNumber, formatDuration: formatDuration,
    // 常量
    TYPES: TYPES, CATEGORIES: CATEGORIES, ICONS: ICONS,
    isSwitchLike: isSwitchLike, categoryLabel: categoryLabel
  };
});
