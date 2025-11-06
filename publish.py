#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish.py
Publish this repo “as an app” for Alauda Catalog:
- Detect repo root automatically (even if launched from ci_cd/)
- Stop docker-compose services (optional)
- Build & push image to GHCR (token prompt)
- Ensure Helm chart (create if missing), update values.yaml image repo/tag
- Package chart to docs/ and generate index.yaml (GitHub Pages)
- Commit & push to GitHub (origin main)

Afterwards, add Helm repo URL to Alauda:
  https://<GITHUB_OWNER>.github.io/<REPO_NAME>
"""
import argparse
import getpass
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

# --------------------------- shell helpers ---------------------------

def run(cmd: str, cwd: Optional[Path] = None, check: bool = True) -> Tuple[int,str,str]:
    p = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, shell=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {cmd}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return p.returncode, out, err

def need(cmd_name: str):
    try:
        run(f"command -v {shlex.quote(cmd_name)}", check=True)
    except Exception:
        raise SystemExit(f"ERROR: `{cmd_name}` is required on PATH")

def detect_repo_root(start: Path) -> Path:
    # Try git toplevel first
    code, out, err = run("git rev-parse --show-toplevel", cwd=start, check=False)
    if code == 0 and out.strip():
        return Path(out.strip())
    # Walk up until .git found
    cur = start.resolve()
    for _ in range(10):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise SystemExit(f"ERROR: Not inside a Git repository (start={start}). Run from repo or init git.")

def parse_github_url(url: str) -> Tuple[str, str]:
    """
    git@github.com:owner/repo.git or https://github.com/owner/repo(.git)
    """
    m = re.match(r"git@github\.com:(?P<o>[^/]+)/(?P<r>[^/]+?)(?:\.git)?$", url)
    if not m:
        m = re.match(r"https?://github\.com/(?P<o>[^/]+)/(?P<r>[^/]+?)(?:\.git)?$", url)
    if not m:
        raise ValueError(f"Cannot parse GitHub URL: {url}")
    owner = m.group("o")
    repo = re.sub(r"\.git$", "", m.group("r"))
    return owner, repo

def ensure_git_remote_origin(ssh_url: str, repo_root: Path):
    code, out, _ = run("git remote -v", cwd=repo_root)
    if "origin" not in out:
        print("Setting git remote origin ...")
        run(f"git remote add origin {shlex.quote(ssh_url)}", cwd=repo_root)

def ensure_on_branch(repo_root: Path, branch: str = "main"):
    code, out, _ = run("git rev-parse --abbrev-ref HEAD", cwd=repo_root)
    current = out.strip()
    if current != branch:
        print(f"Checking out branch {branch} (current: {current}) ...")
        run(f"git checkout -B {shlex.quote(branch)}", cwd=repo_root)

def git_commit_push(repo_root: Path, message: str):
    run("git add -A", cwd=repo_root)
    code, out, err = run(f'git commit -m {shlex.quote(message)}', cwd=repo_root, check=False)
    if code == 0:
        print("Committed changes.")
    else:
        print("Nothing to commit (or commit failed). Proceeding.")
    run("git push -u origin HEAD", cwd=repo_root)

# --------------------------- docker/compose ---------------------------

def docker_login_ghcr(username: str, token: str):
    print("Logging in to ghcr.io ...")
    cmd = f'echo {shlex.quote(token)} | docker login ghcr.io -u {shlex.quote(username)} --password-stdin'
    run(cmd)

def docker_build_push(image_ref: str, context_dir: Path, dockerfile: Optional[str]):
    df_opt = f"-f {shlex.quote(dockerfile)}" if dockerfile else ""
    print(f"Building image: {image_ref}")
    run(f"docker build {df_opt} -t {shlex.quote(image_ref)} {shlex.quote(str(context_dir))}")
    print(f"Pushing image: {image_ref}")
    run(f"docker push {shlex.quote(image_ref)}")

def compose_down_if_present(compose_dir: Path):
    dc_yml = compose_dir / "docker-compose.yml"
    if not dc_yml.exists():
        print(f"No docker-compose.yml in {compose_dir}, skipping stop.")
        return
    print(f"Stopping compose services in {compose_dir} ...")
    run("docker compose down --remove-orphans", cwd=compose_dir)

# --------------------------- helm/chart ---------------------------

def write_minimal_chart(chart_dir: Path, image_repo: str, image_tag: str, app_version: str):
    chart_dir.mkdir(parents=True, exist_ok=True)
    (chart_dir / "templates").mkdir(parents=True, exist_ok=True)
    (chart_dir / "Chart.yaml").write_text(f"""apiVersion: v2
name: chartmuseum-migrator
description: Migrate Helm charts from SRC to TGT using Vault (no overwrite)
type: application
version: {image_tag}
appVersion: "{app_version}"
home: https://github.com/
""", encoding="utf-8")
    (chart_dir / "values.yaml").write_text(f"""image:
  repository: {image_repo}
  tag: "{image_tag}"
  pullPolicy: IfNotPresent

env:
  SRC_URL: ""
  SRC_USER: ""
  SRC_PASS: ""
  TGT_URL: ""
  TGT_USER: ""
  TGT_PASS: ""
  VAULT_ADDR: ""
  VAULT_TOKEN: ""
  EXTRA_ARGS: ""
""", encoding="utf-8")
    (chart_dir / "templates" / "job.yaml").write_text(r"""apiVersion: batch/v1
kind: Job
metadata:
  name: chartmuseum-migrator
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrator
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          env:
            - name: SRC_URL     ; value: {{ .Values.env.SRC_URL | quote }}
            - name: SRC_USER    ; value: {{ .Values.env.SRC_USER | quote }}
            - name: SRC_PASS    ; value: {{ .Values.env.SRC_PASS | quote }}
            - name: TGT_URL     ; value: {{ .Values.env.TGT_URL | quote }}
            - name: TGT_USER    ; value: {{ .Values.env.TGT_USER | quote }}
            - name: TGT_PASS    ; value: {{ .Values.env.TGT_PASS | quote }}
            - name: VAULT_ADDR  ; value: {{ .Values.env.VAULT_ADDR | quote }}
            - name: VAULT_TOKEN ; value: {{ .Values.env.VAULT_TOKEN | quote }}
            - name: EXTRA_ARGS  ; value: {{ .Values.env.EXTRA_ARGS | quote }}
          command:
            - /bin/sh
            - -ce
            - |
              echo "Starting chart migration job..."
              python3 migrate_cm.py --out /work/out ${EXTRA_ARGS}
""", encoding="utf-8")
    print(f"Created minimal Helm chart at {chart_dir}")

def ensure_values_image(chart_dir: Path, image_repo: str, image_tag: str):
    values = chart_dir / "values.yaml"
    if not values.exists():
        write_minimal_chart(chart_dir, image_repo, image_tag, app_version=image_tag)
        return
    txt = values.read_text(encoding="utf-8")
    # Update repo
    if re.search(r'^\s*repository:\s*', txt, flags=re.M):
        txt = re.sub(r'(^\s*repository:\s*).*$',
                     rf'\1{image_repo}', txt, flags=re.M)
    else:
        txt += f'\nimage:\n  repository: {image_repo}\n'
    # Update tag
    if re.search(r'^\s*tag:\s*', txt, flags=re.M):
        txt = re.sub(r'(^\s*tag:\s*).*$',
                     rf'\1"{image_tag}"', txt, flags=re.M)
    else:
        txt = re.sub(r'(^image:\s*\n)', rf'\1  tag: "{image_tag}"\n', txt, count=1, flags=re.M)
    values.write_text(txt, encoding="utf-8")
    print(f"Updated {values} with image {image_repo}:{image_tag}")

def helm_package_to_docs(chart_dir: Path, docs_dir: Path, repo_url: str) -> Optional[str]:
    need("helm")
    docs_dir.mkdir(parents=True, exist_ok=True)
    run(f"helm lint {shlex.quote(str(chart_dir))}")
    # determine chart name
    ch = (chart_dir / "Chart.yaml").read_text(encoding="utf-8")
    m = re.search(r"^name:\s*([^\s]+)", ch, re.M)
    chart_name = m.group(1) if m else "chartmuseum-migrator"
    run(f"helm package {shlex.quote(str(chart_dir))} -d {shlex.quote(str(docs_dir))}")
    run(f"helm repo index {shlex.quote(str(docs_dir))} --url {shlex.quote(repo_url)}")
    tgzs = sorted(docs_dir.glob(f"{chart_name}-*.tgz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return tgzs[0].name if tgzs else None

# --------------------------- main ---------------------------

def main():
    ap = argparse.ArgumentParser(description="Publish GHCR image + Helm repo (GitHub Pages) for Alauda")
    ap.add_argument("--github-url", default="git@github.com:vladarh/chartmuseum-RND.git", help="GitHub repo URL (SSH/HTTPS)")
    ap.add_argument("--image-repo", default=None, help="Image repo, e.g. ghcr.io/<owner>/<name>")
    ap.add_argument("--image-tag", default=None, help="Image tag (default: YYYYMMDD-HHMMSS)")
    ap.add_argument("--chart-dir", default="charts/chartmuseum-migrator", help="Path under repo root for Helm chart")
    ap.add_argument("--docs-dir", default="docs", help="Folder served by GitHub Pages")
    ap.add_argument("--stop-compose", action="store_true", help="Stop docker compose in ci_cd/ before build")
    ap.add_argument("--compose-dir", default="ci_cd", help="Compose directory relative to repo root")
    ap.add_argument("--dockerfile", default=None, help="Path to Dockerfile (e.g., Dockerfile.local). Default: Dockerfile if exists else None")
    ap.add_argument("--branch", default="main", help="Branch to push")
    args = ap.parse_args()

    # prerequisites
    need("git"); need("docker"); need("helm")

    # detect repo root even if we start from ci_cd/
    start = Path.cwd()
    repo_root = detect_repo_root(start)
    print("============================================================")
    print("Publisher to GHCR + GitHub Pages (Helm repo) for Alauda")
    print("Repo root:", repo_root)
    print("============================================================")

    # Parse owner/repo from GitHub URL
    owner, repo = parse_github_url(args.github_url)
    helm_repo_url = f"https://{owner}.github.io/{repo}"

    # Ensure git remote/branch
    ensure_git_remote_origin(args.github_url, repo_root)
    ensure_on_branch(repo_root, branch=args.branch)

    # Compose stop (optional)
    if args.stop_compose:
        compose_down_if_present(repo_root / args.compose_dir)

    # GHCR auth
    print("\nGHCR authentication")
    ghcr_user = input(f"GHCR username [{owner}]: ").strip() or owner
    ghcr_token = getpass.getpass("GHCR token (will not echo): ").strip()
    if not ghcr_token:
        print("ERROR: GHCR token is required")
        return 2
    docker_login_ghcr(ghcr_user, ghcr_token)

    # Image ref
    default_image_repo = args.image_repo or f"ghcr.io/{owner}/{repo}-migrator"
    image_repo = input(f"Image repository [{default_image_repo}]: ").strip() or default_image_repo
    default_tag = args.image_tag or time.strftime("%Y%m%d-%H%M%S")
    image_tag = input(f"Image tag [{default_tag}]: ").strip() or default_tag
    image_ref = f"{image_repo}:{image_tag}"

    # Dockerfile selection
    dockerfile = args.dockerfile
    if not dockerfile:
        df_path = (repo_root / "Dockerfile")
        df_local = (repo_root / "Dockerfile.local")
        if df_local.exists():
            dockerfile = str(df_local)
        elif df_path.exists():
            dockerfile = str(df_path)
        else:
            dockerfile = None
    if dockerfile:
        print(f"Using Dockerfile: {dockerfile}")
    else:
        print("WARNING: No Dockerfile found; relying on default docker build context (may fail if none).")

    # Build & push image
    docker_build_push(image_ref, repo_root, dockerfile)

    # Ensure Helm chart + values image
    chart_dir = (repo_root / args.chart_dir).resolve()
    if not (chart_dir / "Chart.yaml").exists():
        write_minimal_chart(chart_dir, image_repo=image_repo, image_tag=image_tag, app_version=image_tag)
    else:
        ensure_values_image(chart_dir, image_repo=image_repo, image_tag=image_tag)

    # Package chart into docs/ and update index.yaml
    docs_dir = (repo_root / args.docs_dir).resolve()
    tar_name = helm_package_to_docs(chart_dir, docs_dir, helm_repo_url)

    # Commit + push docs
    msg = f"Publish Helm repo {tar_name or ''} and image {image_ref}"
    git_commit_push(repo_root, msg)

    # Output
    print("\n============================================================")
    print("DONE")
    print("Add this Helm repo URL to Alauda Catalog:")
    print(f"  {helm_repo_url}")
    print("\nIf not yet enabled, turn on GitHub Pages for this repo:")
    print("  Settings → Pages → Source: Deploy from a branch, Branch: main, Folder: /docs")
    print("\nHelm test (local):")
    print(f"  helm repo add cmigrator {helm_repo_url}")
    print("  helm repo update && helm search repo cmigrator")
    print("\nImage pushed:")
    print(f"  {image_ref}")
    print("============================================================")
    return 0

if __name__ == "__main__":
    sys.exit(main())
