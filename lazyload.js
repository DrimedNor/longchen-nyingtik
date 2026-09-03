/* ===== 文章内容按需加载模块 =====
 * 在原始show函数之后加载，重写show函数实现按需加载
 */
(function(){
  // 已加载的文章内容缓存
  var pageContentCache = {};
  // 正在加载的文章，避免重复请求
  var pageLoading = {};
  // 保存原始的show函数
  var originalShow = window.show;

  // 生成安全的文件名（与构建器一致）
  function getSafeFilename(slug) {
    return slug.replace(/\//g, "__").replace(/ /g, "_").replace(/[?？:："'<>*|]/g, "");
  }

  // 加载文章内容
  function loadPageContent(slug) {
    return new Promise(function(resolve, reject) {
      // 已缓存，直接返回
      if (pageContentCache[slug]) {
        resolve(pageContentCache[slug]);
        return;
      }
      // 正在加载，等待完成
      if (pageLoading[slug]) {
        pageLoading[slug].push({resolve: resolve, reject: reject});
        return;
      }
      // 开始加载
      pageLoading[slug] = [{resolve: resolve, reject: reject}];
      var url = "pages/" + getSafeFilename(slug) + ".json";
      fetch(url, {cache: "force-cache"})
        .then(function(r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function(data) {
          pageContentCache[slug] = data;
          var waiters = pageLoading[slug] || [];
          delete pageLoading[slug];
          waiters.forEach(function(w) { w.resolve(data); });
        })
        .catch(function(err) {
          delete pageLoading[slug];
          var waiters = pageLoading[slug] || [];
          waiters.forEach(function(w) { w.reject(err); });
        });
    });
  }

  // 重写show函数
  window.show = function(slug) {
    var p = window.bySlug ? window.bySlug[slug] : null;
    if (!p) {
      // 没有找到页面，调用原始show函数处理404
      if (originalShow) originalShow(slug);
      return;
    }

    // 如果不需要按需加载，或者是目录页，直接调用原始show函数
    if (!p._need_load || p.is_index || slug === "index") {
      if (originalShow) originalShow(slug);
      return;
    }

    // 需要按需加载
    // 先显示加载状态（简化版，直接设置内容）
    var contentEl = document.getElementById('content');
    if (contentEl) {
      contentEl.innerHTML = '<div class="article"><div style="text-align:center;padding:3rem 0;color:var(--ink-faint);"><div style="font-size:2rem;margin-bottom:1rem;">📖</div><div>正在加载文章内容...</div></div></div>';
    }

    // 加载文章内容
    loadPageContent(slug).then(function(data) {
      // 加载成功，把内容赋值给p对象，然后调用原始show函数
      p.html = data.html;
      p.meta = data.meta || p.meta;
      p.tags = data.tags || p.tags;
      p._need_load = false; // 标记已加载，避免重复加载
      // 调用原始show函数渲染
      if (originalShow) originalShow(slug);
    }).catch(function(err) {
      // 加载失败
      if (contentEl) {
        contentEl.innerHTML = '<div class="article"><div style="text-align:center;padding:3rem 0;color:var(--ink-faint);"><div style="font-size:2rem;margin-bottom:1rem;">⚠️</div><div>文章内容加载失败</div><div style="font-size:.85rem;margin-top:.5rem;">' + (err.message || '') + '</div><button onclick="location.reload()" style="margin-top:1rem;padding:.5rem 1rem;border-radius:8px;border:1px solid var(--accent);background:var(--accent-soft);color:var(--accent-deep);cursor:pointer;">重新加载</button></div></div>';
      }
    });
  };

  // 暴露loadPageContent函数供外部使用
  window.loadPageContent = loadPageContent;
})();
