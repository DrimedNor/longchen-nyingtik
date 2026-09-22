#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Cloudflare 运维四件：缓存 Purge / 登录接口限速 / 状态体检 / 生效验证
================================================================
背景（2026-09-22 实测结论，非猜测）：
  wrangler 的 OAuth token 权限范围里**没有** `cache_purge`、也没有 `zone:waf`
  （scopes 实测：user:read / account:read / workers:* / pages:write / d1:write /
   zone:read / ssl_certs:write / ai:* …；**zone 级只有 read**）
  ⇒ 用现成凭据打 API：purge_cache → 401 code 10000；rulesets → 403 code 10000。
  两条路二选一：
    A. 小谦在 Dashboard 点两下（见《Dashboard两件操作指引》）
    B. 建一个带 `Zone → Cache Purge` ＋ `Zone → WAF Edit` 的 API Token，放进环境变量后跑本脚本

用法（**默认只读**；写操作必须 --yes）：
    python cf_ops.py status              # 只读：zone / 缓存头 / 限速规则现状
    python cf_ops.py purge --yes         # 清空该 zone 全部缓存（幂等、无副作用）
    python cf_ops.py ratelimit --yes     # 建/更新 /api/login 限速规则
    python cf_ops.py verify --run        # 只读探测：连发 8 次错误登录，看是否出现 429

凭据：环境变量 CF_API_TOKEN（或 CLOUDFLARE_API_TOKEN）；缺省时回退 wrangler OAuth（只够 status）。
本脚本不写入任何凭据、不打印完整 token。
"""
import io, json, os, re, sys, time
import urllib.request, urllib.error

ZONE_NAME = "longchen-nyingtik.wiki"
LOGIN_PATHS = ["/api/login", "/login"]
LIMIT_PERIOD = 60           # 秒
LIMIT_REQUESTS = 5          # 每 period 允许次数（对齐后台既有 5/15min 口径的收紧版）
LIMIT_TIMEOUT = 60          # 触发后拦截时长（秒）
API = "https://api.cloudflare.com/client/v4"


def load_token():
    for k in ("CF_API_TOKEN", "CLOUDFLARE_API_TOKEN"):
        if os.environ.get(k):
            return os.environ[k].strip(), "env:" + k
    p = os.path.join(os.environ.get("APPDATA", ""), "xdg.config", ".wrangler", "config", "default.toml")
    if os.path.isfile(p):
        t = io.open(p, encoding="utf-8", errors="ignore").read()
        m = re.search(r'oauth_token\s*=\s*"([^"]+)"', t)
        if m:
            return m.group(1), "wrangler-oauth(仅够 status)"
    return None, None


TOKEN, TOKEN_SRC = load_token()


def call(method, path, body=None, quiet=False):
    if not TOKEN:
        return -1, {"success": False, "errors": [{"message": "未找到 token（设 CF_API_TOKEN）"}]}
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(raw)
        except Exception:
            j = {"errors": [{"message": raw[:200]}]}
        return e.code, j
    except Exception as e:
        return -1, {"errors": [{"message": repr(e)[:200]}]}


def brief(st, j):
    if j.get("success"):
        return True, "OK"
    errs = j.get("errors") or []
    msg = "；".join(str(e.get("message")) for e in errs) or "(无错误信息)"
    codes = ",".join(str(e.get("code")) for e in errs if e.get("code"))
    hint = ""
    if st in (401, 403):
        hint = "  ⇒ 凭据缺该权限（Dashboard 侧需 Zone:Cache Purge / Zone WAF:Edit）"
    return False, "HTTP %s [%s] %s%s" % (st, codes, msg, hint)


def get_zone():
    st, j = call("GET", "/zones?per_page=50")
    ok, m = brief(st, j)
    if not ok:
        print("  ✗ 取 zone 失败：", m)
        return None
    for z in (j.get("result") or []):
        if z.get("name") == ZONE_NAME:
            return z["id"]
    print("  ✗ zone 列表里没有", ZONE_NAME)
    return None


def http_head(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 cf_ops"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)
    except Exception as e:
        return -1, {"err": repr(e)[:120]}


# ------------------------------------------------------------------ status
def cmd_status(_):
    print("token 来源：%s | 长度 %d" % (TOKEN_SRC or "无", len(TOKEN or "")))
    zid = get_zone()
    print("zone id：", zid)
    if zid:
        st, j = call("GET", "/zones/%s/rulesets" % zid)
        ok, m = brief(st, j)
        print("rulesets 读取：", m)
        if ok:
            for r in (j.get("result") or []):
                if "ratelimit" in (r.get("phase") or ""):
                    print("   - 限速规则集：phase=%s id=%s" % (r.get("phase"), r.get("id")))
        st, j = call("GET", "/zones/%s/rulesets/phases/http_ratelimit/entrypoint" % zid)
        ok, m = brief(st, j)
        print("限速 entrypoint：", m)
        if ok:
            rules = (j.get("result") or {}).get("rules") or []
            if not rules:
                print("   ⚠ 尚无任何限速规则 ⇒ /api/login 无限流")
            for r in rules:
                print("   - %s | enabled=%s | %s" % (r.get("description"), r.get("enabled"), r.get("expression")))
    print()
    print("线上缓存头（Purge 是否生效 / O-01 观察）：")
    for u in ["https://%s/robots.txt" % ZONE_NAME,
              "https://%s/practice.js" % ZONE_NAME,
              "https://%s/zangli.html" % ZONE_NAME]:
        st, h = http_head(u)
        print("  %-44s %s  Cache-Control=%s  cf-cache-status=%s"
              % (u, st, h.get("Cache-Control") or h.get("err") or "(无)", h.get("cf-cache-status") or "-"))
    print()
    print("登录接口现状：")
    st, h = http_head("https://%s/api/login" % ZONE_NAME)
    print("  GET /api/login -> %s（405/401 均属正常，只确认路由存在）" % st)


# ------------------------------------------------------------------ purge
def cmd_purge(argv):
    if "--yes" not in argv:
        print("✗ 这是写操作：确认要清空 %s 的全部边缘缓存，请加 --yes" % ZONE_NAME)
        return 2
    zid = get_zone()
    if not zid:
        return 1
    st, j = call("POST", "/zones/%s/purge_cache" % zid, {"purge_everything": True})
    ok, m = brief(st, j)
    print("purge_everything：", m)
    if ok:
        print("  ✅ 已提交清空。等 5～10 秒后跑 `cf_ops.py status` 复看缓存头是否刷新。")
        return 0
    return 1


# ------------------------------------------------------------------ ratelimit
def cmd_ratelimit(argv):
    rule = {
        "action": "block",
        "action_parameters": {
            "response": {
                "status_code": 429,
                "content_type": "application/json",
                "content": '{"success":false,"error":"too many login attempts, retry later"}',
            }
        },
        "expression": '(http.request.method eq "POST" and http.request.uri.path in {%s})'
                      % " ".join('"%s"' % p for p in LOGIN_PATHS),
        "description": "longchen: 登录接口限速（同 IP %ds 内 >%d 次即拦）" % (LIMIT_PERIOD, LIMIT_REQUESTS),
        "enabled": True,
        "ratelimit": {
            "characteristics": ["ip.src"],
            "period": LIMIT_PERIOD,
            "requests_per_period": LIMIT_REQUESTS,
            "mitigation_timeout": LIMIT_TIMEOUT,
        },
    }
    print("拟写入规则：")
    print(json.dumps(rule, ensure_ascii=False, indent=2))
    if "--yes" not in argv:
        print("\n✗ 这是写操作：确认后加 --yes")
        return 2
    zid = get_zone()
    if not zid:
        return 1
    st, j = call("PUT", "/zones/%s/rulesets/phases/http_ratelimit/entrypoint" % zid, {"rules": [rule]})
    ok, m = brief(st, j)
    print("PUT http_ratelimit entrypoint：", m)
    if ok:
        print("  ✅ 规则已写入。跑 `cf_ops.py verify --run` 实测是否真的会 429。")
        return 0
    return 1


# ------------------------------------------------------------------ verify
def cmd_verify(argv):
    url = "https://%s/api/login" % ZONE_NAME
    print("向 %s 连发 14 次「错误凭据」POST，看是否出现 429（每次约 0.15s，约 3 秒）" % url)
    if "--run" not in argv:
        print("（演练模式，不实际发请求；确认后加 --run）")
        return 0
    body = json.dumps({"username": "__cf_ops_probe__", "password": "x" * 12}).encode()
    hits = {}
    for i in range(1, 15):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "Mozilla/5.0 cf_ops"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            print("  第 %2d 次：请求异常 %r" % (i, e))
            break
        hits[code] = hits.get(code, 0) + 1
        print("  第 %2d 次 -> %s" % (i, code))
        if code == 429:
            print("  ✅ 已触发 429 ⇒ 限速生效（同 IP %ds 内 >%d 次）" % (LIMIT_PERIOD, LIMIT_REQUESTS))
            break
        time.sleep(0.15)
    print("汇总：", hits)
    if 429 not in hits:
        print("  ⚠ 未出现 429 ⇒ 规则未生效 / 未配置 / 有别的路径绕过（核对 www 与根域是否都走同一 zone）")
        return 1
    return 0


CMDS = {"status": cmd_status, "purge": cmd_purge, "ratelimit": cmd_ratelimit, "verify": cmd_verify}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(CMDS[sys.argv[1]](sys.argv[2:]) or 0)
