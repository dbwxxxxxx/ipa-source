#!/usr/bin/env python3
"""Convert appstore.json entries to AltStore source using bounded HTTP Range reads."""
from __future__ import annotations
import argparse, json, logging, os, re, sys, tempfile, urllib.error, urllib.parse, urllib.request, zipfile, plistlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from release_notes import release_note

LOG = logging.getLogger("altstore_generator")
MAX_REQUESTS = 80
MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRY = 2 * 1024 * 1024
TIMEOUT = 20
USER_AGENT = "ipa-source-build-altstore/1.0"

class IPAReadError(Exception): pass
class TransientReadError(IPAReadError): pass

class RangeReader:
    """Seekable read-only HTTP range stream; never saves or executes the archive."""
    def __init__(self, url, request_cap=MAX_REQUESTS, byte_cap=MAX_BYTES, timeout=TIMEOUT):
        self.url=url; self.request_cap=request_cap; self.byte_cap=byte_cap; self.timeout=timeout
        self.requests=0; self.bytes=0; self.pos=0; self.closed=False
        self.size=self._read_size()
        if self.size <= 0: raise IPAReadError("empty or unknown-size IPA")
    def _request(self, start, end):
        if self.requests >= self.request_cap: raise TransientReadError("HTTP request limit exceeded")
        if start < 0 or end < start or end >= self.size: raise IPAReadError("range outside archive bounds")
        self.requests+=1
        req=urllib.request.Request(self.url, headers={"Range":f"bytes={start}-{end}", "Accept-Encoding":"identity", "User-Agent":USER_AGENT})
        try:
            res=urllib.request.urlopen(req, timeout=self.timeout)
        except Exception as exc: raise TransientReadError(f"range request failed: {exc}") from exc
        with res:
            if res.status != 206: raise TransientReadError(f"expected HTTP 206, received {res.status}")
            cr=res.headers.get("Content-Range", "")
            m=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",cr.strip())
            if not m or tuple(map(int,m.groups())) != (start,end,self.size): raise TransientReadError(f"invalid Content-Range: {cr!r}")
            length=end-start+1
            if self.bytes+length > self.byte_cap: raise TransientReadError("total response byte limit exceeded")
            data=res.read(length+1)
            if len(data)!=length: raise TransientReadError("response body length mismatch")
            self.bytes+=len(data)
            return data
    def _read_size(self):
        # Bootstrap total size from the mandatory 0-0 partial response.
        if self.request_cap < 1 or self.byte_cap < 1: raise IPAReadError("reader limits too small")
        self.requests+=1
        req=urllib.request.Request(self.url,headers={"Range":"bytes=0-0","Accept-Encoding":"identity","User-Agent":USER_AGENT})
        try: res=urllib.request.urlopen(req,timeout=self.timeout)
        except Exception as exc: raise TransientReadError(f"size probe failed: {exc}") from exc
        with res:
            if res.status != 206: raise TransientReadError(f"expected HTTP 206 on size probe, received {res.status}")
            m=re.fullmatch(r"bytes 0-0/(\d+)",(res.headers.get("Content-Range") or "").strip())
            if not m: raise TransientReadError("missing or invalid Content-Range on size probe")
            data=res.read(2)
            if len(data)!=1: raise TransientReadError("invalid size probe body")
            self.bytes+=1
            return int(m.group(1))
    def seek(self, offset, whence=0):
        if whence==0: pos=offset
        elif whence==1: pos=self.pos+offset
        elif whence==2: pos=self.size+offset
        else: raise ValueError("invalid whence")
        if pos<0: raise ValueError("negative seek")
        self.pos=pos; return pos
    def tell(self): return self.pos
    def readable(self): return True
    def seekable(self): return True
    def read(self, n=-1):
        if self.closed: raise ValueError("I/O operation on closed reader")
        if n is None or n<0: n=self.size-self.pos
        n=min(n,max(0,self.size-self.pos))
        if n==0: return b""
        if n > self.byte_cap: raise IPAReadError("single read exceeds byte limit")
        data=self._request(self.pos,self.pos+n-1); self.pos+=len(data); return data
    def close(self): self.closed=True

def _main_info_path(names):
    candidates=[]
    for n in names:
        p=n.split("/")
        if len(p)==3 and p[0]=="Payload" and p[1].endswith(".app") and p[2]=="Info.plist": candidates.append(n)
    if not candidates: raise IPAReadError("no main Payload/*.app/Info.plist entry")
    return sorted(candidates)[0]

def read_ipa_metadata(url):
    reader=RangeReader(url)
    try:
        with zipfile.ZipFile(reader,"r") as zf:
            path=_main_info_path(zf.namelist())
            info=zf.getinfo(path)
            if info.file_size>MAX_ENTRY: raise IPAReadError(f"Info.plist exceeds {MAX_ENTRY} byte limit")
            if info.file_size<=0: raise IPAReadError("empty Info.plist")
            with zf.open(info) as stream: raw=stream.read(MAX_ENTRY+1)
            if len(raw)>MAX_ENTRY: raise IPAReadError("Info.plist read limit exceeded")
            data=plistlib.loads(raw)
    except IPAReadError: raise
    except Exception as exc: raise IPAReadError(f"invalid/unreadable IPA metadata: {exc}") from exc
    bundle=data.get("CFBundleIdentifier"); version=data.get("CFBundleShortVersionString"); build=data.get("CFBundleVersion")
    if not all(isinstance(x,str) and x.strip() for x in (bundle,version,build)):
        raise IPAReadError("Info.plist lacks a non-empty bundle identifier/version/build version")
    return {"bundleIdentifier":bundle.strip(),"version":version.strip(),"buildVersion":build.strip()}

def _date(value):
    if not value: return ""
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError,ValueError): return ""

def _is_lite(item):
    return bool(re.search(r"(^|[-_. ])lite($|[-_. ])",str(item.get("name", "")+" "+item.get("downloadURL", "")),re.I))

def build(source_path="appstore.json", output_path="altstore-source.json"):
    source=json.loads(Path(source_path).read_text(encoding="utf-8"))
    if not isinstance(source,dict) or not isinstance(source.get("apps"),list): raise ValueError("appstore.json must contain an apps array")
    accepted=[]
    for item in source["apps"]:
        url=item.get("downloadURL") if isinstance(item,dict) else None
        if not isinstance(url,str) or not url.startswith("https://"):
            LOG.warning("SKIP %s: missing public HTTPS downloadURL",(item or {}).get("name","?")); continue
        try: meta=read_ipa_metadata(url)
        except TransientReadError as exc:
            raise RuntimeError(f"conversion aborted; refusing partial source after read failure for {url}: {exc}") from exc
        except IPAReadError as exc:
            LOG.warning("SKIP %s (%s): %s",item.get("name","?"),url,exc); continue
        accepted.append((item,meta))
    # Group by actual bundle identifier; standard IPA wins over lite, then newest source entry.
    grouped={}
    for item,meta in accepted:
        key=meta["bundleIdentifier"]
        score=(not _is_lite(item),str(item.get("versionDate", "")))
        if key not in grouped or score>grouped[key][0]:
            if key in grouped: LOG.warning("DUPLICATE %s: replacing %s with preferred %s",key,grouped[key][1].get("name"),item.get("name"))
            grouped[key]=(score,item,meta)
        else: LOG.warning("DUPLICATE %s: skipping %s in favor of %s%s",key,item.get("name"),grouped[key][1].get("name")," (standard over lite)" if _is_lite(item) else "")
    apps=[]
    for _,item,meta in grouped.values():
        url=item["downloadURL"]
        appname=str(item.get("name") or meta["bundleIdentifier"]).split(" — ")[0]
        # A repository owner's avatar is used only as a visual placeholder, not a verified app icon.
        parts=urllib.parse.urlparse(url).path.strip('/').split('/')
        developer=parts[0] if urllib.parse.urlparse(url).hostname == 'github.com' and len(parts)>=2 else 'Unknown Developer'
        notes=str(item.get("localizedDescription") or item.get("versionDescription") or "").strip()
        # Current appstore entries already carry a concise Chinese abstract and attribution.
        # For legacy inputs, don't pass English prose through as if it were translated.
        if "Release 原文：" not in notes:
            release_match=re.search(r"https://github\.com/([^/]+/[^/]+)/releases/(?:tag|download)/([^/\s?#]+)",url)
            if release_match:
                repo,tag=release_match.groups()
                notes=release_note(repo,urllib.parse.unquote(tag),notes,f"https://github.com/{repo}/releases/tag/{tag}")
            elif not notes:
                notes="暂无可靠中文摘要"
        date=_date(item.get("versionDate"))
        size=int(item.get("size") or 0)
        icon=item.get("appIconURL") or item.get("iconURL") or "https://github.githubassets.com/favicons/favicon.png"
        version={"version":meta["version"],"buildVersion":meta["buildVersion"],"date":date,"localizedDescription":notes,"downloadURL":url,"size":size}
        app={"name":appname,"bundleIdentifier":meta["bundleIdentifier"],"developerName":developer,"localizedDescription":notes,"iconURL":icon,"versions":[version],"version":meta["version"],"versionDate":date,"versionDescription":notes,"downloadURL":url,"size":size}
        apps.append(app)
    if not apps: raise RuntimeError("conversion produced no verified apps; refusing to write an empty source")
    result={"name":source.get("name") or "GitHub IPA AltStore Source","identifier":source.get("identifier") or "app.generated.altstore.source","subtitle":"Apps from public GitHub releases","description":"Generated from public GitHub releases; version identifiers are read from each IPA's main app Info.plist.","iconURL":source.get("sourceicon") or "https://github.githubassets.com/favicons/favicon.png","apps":apps,"news":[]}
    if isinstance(source.get("sourceURL"),str): result["website"]=source["sourceURL"]
    target=Path(output_path)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{target.name}.",suffix=".tmp",dir=str(target.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2); stream.write("\n")
        os.replace(tmp,target)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
    LOG.info("Wrote %s with %d metadata-verified apps",output_path,len(apps))
    return result

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(levelname)s: %(message)s")
    ap=argparse.ArgumentParser(); ap.add_argument("input_pos",nargs="?"); ap.add_argument("output_pos",nargs="?"); ap.add_argument("--input",dest="input_opt"); ap.add_argument("--output",dest="output_opt"); args=ap.parse_args()
    input_path=args.input_opt or args.input_pos or "appstore.json"
    output_path=args.output_opt or args.output_pos or "altstore-source.json"
    try: build(input_path,output_path)
    except Exception as exc: LOG.error("generation failed: %s",exc); sys.exit(1)
