"""Tao GitHub Release cho mot tag va day file len do, doc lai sau khi xong.

    python scratch/github_release.py <owner/repo> <tag> --name "Clinging 1.0.1" \
        --body-file docs/release-1.0.1.md <file> [<file> ...]

Vi sao dung REST ma khong dung `gh`: may nay khong co gh CLI. Token lay bang
`git credential fill` (Git Credential Manager dang dung cho push), KHONG in ra
va KHONG luu vao file. GITHUB_TOKEN duoc uu tien neu da co trong moi truong.

Vi sao phai doc lai bang request KHONG tuc dat (kc o cuoi): POST tra ve 201 la
no nhan yeu cau, chu khong chung minh duoc asset nao nam tren Release ma nguoi
dung cong khai se nhin thay. Doc vo tuc dat con kiem duoc repo van la public —
mot lan dao sang private cung in ra 201 cho viec push cua chinh chu tai khoan.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import requests

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def token():
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip(), "GITHUB_TOKEN"
    out = subprocess.run(["git", "credential", "fill"],
                         input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("git credential fill that bai: " + out.stderr.strip())
    secret = None
    for line in out.stdout.splitlines():
        if line.startswith("password="):
            secret = line[len("password="):].strip()
    if not secret or len(secret) < 20:
        raise SystemExit("Khong lay duoc token tu Git Credential Manager")
    return secret, "git credential fill"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def api(sess, method, url, **kw):
    r = sess.request(method, url, timeout=180, **kw)
    if r.status_code >= 400:
        raise SystemExit("%s %s -> %s %s" % (method, url, r.status_code,
                                             r.text[:400]))
    return r


def release_for(sess, repo, tag, name, body):
    r = sess.get("%s/repos/%s/releases/tags/%s" % (API, repo, tag), timeout=60)
    if r.status_code == 404:
        created = api(sess, "POST", "%s/repos/%s/releases" % (API, repo),
                      json={"tag_name": tag, "name": name, "body": body,
                            "draft": False, "prerelease": False})
        print("da tao Release id=%s cho tag %s" % (created.json()["id"], tag))
        return created.json()
    print("Release cua tag %s da ton tai (id=%s), chi bo sung asset"
          % (tag, r.json()["id"]))
    return r.json()


def upload(sess, repo, rel, path):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    for asset in rel["assets"]:
        if asset["name"] != name:
            continue
        same = asset["size"] == size
        print("  asset %s da co (%s B, kich thuoc %s) -> xoa va day lai"
              % (name, asset["size"], "khop" if same else "KHONG khop"))
        api(sess, "DELETE", asset["url"])
    url = "%s/repos/%s/releases/%s/assets" % (UPLOADS, repo, rel["id"])
    t0 = time.time()
    with open(path, "rb") as f:
        r = sess.put(url, params={"name": name},
                     headers={"Content-Type": "application/octet-stream"},
                     data=f, timeout=1800)
    if r.status_code not in (200, 201):
        raise SystemExit("upload %s -> %s %s" % (name, r.status_code, r.text[:400]))
    a = r.json()
    print("  %s: %s B trong %.0f s, state=%s"
          % (name, a["size"], time.time() - t0, a["state"]))
    return a


def verify_unauthed(repo, tag, expect):
    """Doc cong khai, khong token: prove that a stranger sees the same release."""
    r = requests.get("%s/repos/%s/releases/tags/%s" % (API, repo, tag), timeout=60)
    if r.status_code != 200:
        print("GATE FAIL: nguoi dung vo tuc dat khong doc duoc release (%s)"
              % r.status_code)
        return 1
    rel = r.json()
    got = {a["name"]: a for a in rel["assets"]}
    bad = []
    print("public read-back: tag=%s name=%r draft=%s prerelease=%s"
          % (rel["tag_name"], rel["name"], rel["draft"], rel["prerelease"]))
    for name, size, digest in expect:
        a = got.get(name)
        if not a:
            bad.append("%s thieu asset" % name)
            continue
        if a["size"] != size:
            bad.append("%s size %s != %s" % (name, a["size"], size))
        remote = (a.get("digest") or "").replace("sha256:", "")
        if remote and remote != digest:
            bad.append("%s sha256 %s != %s" % (name, remote[:12], digest[:12]))
        # Range test: download_url dan toi URL ky so cua S3, 206 = file that voi tai.
        head = requests.get(a["browser_download_url"], timeout=120, stream=True,
                            headers={"Range": "bytes=0-1023"})
        chunk = next(head.iter_content(1024), b"")
        if head.status_code != 206 or len(chunk) != 1024:
            bad.append("%s tai ve khong chay (%s, %d B dau)"
                       % (name, head.status_code, len(chunk)))
        print("  %-32s %10d B  digest %s  first-1KB %s"
              % (name, a["size"], (remote[:12] or "n/a"), head.status_code))
    for b in bad:
        print("GATE FAIL: " + b)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("tag")
    ap.add_argument("--name", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    body = open(a.body_file, encoding="utf-8").read()

    tok, src = token()
    sess = requests.Session()
    sess.headers.update({"Authorization": "token " + tok,
                         "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"})
    who = sess.get(API + "/user", timeout=60).json()
    print("token (%s) cua tai khoan %s; repo %s" % (src, who.get("login"), a.repo))
    if who.get("login").lower() != a.repo.split("/")[0].lower():
        raise SystemExit("SAI TAI KHOAN: token cua %s khong phai chu so huu %s"
                         % (who.get("login"), a.repo.split("/")[0]))

    rel = release_for(sess, a.repo, a.tag, a.name, body)
    expect = []
    for path in a.files:
        size = os.path.getsize(path)
        digest = sha256(path)
        print("day %s (%d B, sha256 %s...)" % (os.path.basename(path), size,
                                              digest[:12]))
        upload(sess, a.repo, rel, path)
        expect.append((os.path.basename(path), size, digest))
    rc = verify_unauthed(a.repo, a.tag, expect)
    print(json.dumps({"html_url": rel["html_url"]}))
    print("https://github.com/%s/releases/tag/%s" % (a.repo, a.tag))
    return rc


if __name__ == "__main__":
    sys.exit(main())
