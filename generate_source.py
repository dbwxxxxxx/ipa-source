#!/usr/bin/env python3
"""Build an All-in-One Sign source from public GitHub releases."""
from __future__ import annotations
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ipa-source-build/1.0"}
TOKEN = os.environ.get("GITHUB_TOKEN", "")
if TOKEN: HEADERS["Authorization"] = f"Bearer {TOKEN}"

class APIError(RuntimeError): pass

def request_json(url):
    for attempt in range(4):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403 and (e.headers.get("X-RateLimit-Remaining") == "0" or "rate limit" in e.read().decode("utf-8", "ignore").lower()):
                reset = int(e.headers.get("X-RateLimit-Reset", time.time()+60))
                delay = max(1, min(reset-time.time()+2, 90))
                if attempt < 3: time.sleep(delay); continue
            if e.code == 404: raise APIError(f"not found: {url}")
            if e.code >= 500 and attempt < 3: time.sleep(2**attempt); continue
            raise APIError(f"GitHub API HTTP {e.code}: {url}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < 3: time.sleep(2**attempt); continue
            raise APIError(f"GitHub API request failed: {url}: {e}") from None
    raise APIError(f"GitHub API request failed: {url}")

def pages(url):
    page = 1
    while True:
        separator = "&" if "?" in url else "?"
        result = request_json(f"{url}{separator}per_page=100&page={page}")
        if not isinstance(result, list): raise APIError(f"Unexpected paginated response: {url}")
        yield from result
        if len(result) < 100: break
        page += 1

def safe_date(value):
    if not value: return ""
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError): return ""

def manual_repos(path):
    try: data=json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError: return []
    except Exception as e: raise APIError(f"Invalid {path}: {e}")
    if not isinstance(data, list) or any(not isinstance(x,str) for x in data): raise APIError("manual_repositories.json must be a JSON array of owner/repo strings")
    repos=[]
    for value in data:
        value=value.strip().removeprefix("https://github.com/").strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value): raise APIError(f"Invalid repository entry: {value}")
        repos.append(value)
    return repos

def build():
    repository=os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[^/]+/[^/]+", repository): raise APIError("GITHUB_REPOSITORY must be owner/repo")
    owner=repository.split("/",1)[0]
    starred=list(pages(f"{API}/users/{urllib.parse.quote(owner)}/starred"))
    # Star list comes from the repository owner; retain only public repositories.
    repos={r["full_name"]:r for r in starred if not r.get("private",False)}
    for name in manual_repos("manual_repositories.json"):
        if name.lower() not in {k.lower() for k in repos}: repos[name]=None
    apps=[]; failures=[]
    for full_name, repo in sorted(repos.items(), key=lambda kv: kv[0].lower()):
        try:
            if repo is None: repo=request_json(f"{API}/repos/{urllib.parse.quote(full_name, safe='/')}")
            if repo.get("private", False): continue
            icon=(repo.get("owner") or {}).get("avatar_url") or "https://github.githubassets.com/favicons/favicon.png"
            releases=list(pages(f"{API}/repos/{urllib.parse.quote(full_name, safe='/')}/releases"))
        except APIError as e:
            if "not found" in str(e).lower(): print(f"SKIP unavailable repo/release: {full_name}", file=sys.stderr); continue
            failures.append(f"{full_name}: {e}"); continue
        stable=[r for r in releases if not r.get("draft") and not r.get("prerelease")]
        stable.sort(key=lambda r: r.get("published_at") or r.get("created_at") or "", reverse=True)
        rel = next((r for r in stable if any(str(a.get("name", "")).lower().endswith(".ipa") and a.get("browser_download_url") for a in r.get("assets", []))), None)
        if rel is None: continue
        assets=[a for a in rel.get("assets",[]) if str(a.get("name","")).lower().endswith(".ipa") and a.get("browser_download_url")]
        description=(rel.get("body") or "").strip() or f"Release {rel.get('tag_name','')} from {full_name}"
        for asset in assets:
            # Each IPA is an independent selectable entry; do not imply variants are interchangeable.
            aname=asset.get("name", "app.ipa")
            apps.append({"name": f"{repo.get('name',full_name.split('/')[-1])} — {aname}", "type":0, "version":str(rel.get("tag_name") or rel.get("name") or "未知"), "versionDate":rel.get("published_at") or rel.get("created_at") or "", "versionDescription":description, "lock":"0", "downloadURL":asset["browser_download_url"], "isLanZouCloud":"0", "iconURL":icon, "tintColor":"3478F6", "size":str(int(asset.get("size") or 0))})
    if failures: raise APIError("扫描未完整完成，为防止清空旧源而中止写入：\n"+"\n".join(failures))
    source={"name":"GitHub IPA 软件源", "message":"由 GitHub Actions 自动更新；应用来自各项目最新稳定版 Release。请自行核验来源及设备兼容性。", "identifier":repository.lower().replace("/","."), "sourceURL":f"https://{owner}.github.io/{repository.split('/',1)[1]}/appstore.json", "sourceicon":"https://github.githubassets.com/favicons/favicon.png", "apps":apps}
    output=Path("appstore.json"); temp=output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(source,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); temp.replace(output)
    print(f"Wrote {output}: {len(apps)} IPA entries from {len(repos)} public repositories")

if __name__=="__main__":
    try: build()
    except APIError as e: print(f"ERROR: {e}",file=sys.stderr); sys.exit(1)
