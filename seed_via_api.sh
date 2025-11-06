#!/usr/bin/env bash
set -euo pipefail

# Config
CM_URL="${CM_URL:-http://localhost:18080}"     # Change if you used a different published port
STORE="${STORE:-$HOME/captain-chart-museum/chartstore}"
REPOS=("repoA" "repoB")

# Charts and versions to generate
CHARTS=("webapp" "api")
declare -A VERSIONS
VERSIONS["webapp"]="0.1.0 0.1.1 0.2.0"
VERSIONS["api"]="1.0.0 1.1.0"

# Tools
command -v curl >/dev/null 2>&1 || { echo "curl required"; exit 1; }
HAS_JQ=0; command -v jq >/dev/null 2>&1 && HAS_JQ=1

# Create a simple Helm-style chart tarball without needing Helm
make_chart_tgz() {
  # Args: name version outpath
  local name="$1" ver="$2" out="$3"
  local d; d="$(mktemp -d)"
  mkdir -p "$d/$name/templates"
  cat >"$d/$name/Chart.yaml" <<EOF
apiVersion: v2
name: $name
version: $ver
description: demo $name $ver
type: application
appVersion: "$ver"
EOF
  echo "message: hello from $name $ver" >"$d/$name/values.yaml"
  cat >"$d/$name/templates/cm.yaml" <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include (print $.Chart.Name "-cfg") . }}
data:
  message: {{ .Values.message | quote }}
EOF
  (cd "$d" && tar -czf "$out" "$name")
  rm -rf "$d"
}

echo "ChartMuseum URL: ${CM_URL}"
echo "Seeding store:   ${STORE}"
mkdir -p "${STORE}"

# Create repos and copy charts into <repo>/charts (read-only mount on container is fine)
for repo in "${REPOS[@]}"; do
  mkdir -p "${STORE}/${repo}/charts"
  for chart in "${CHARTS[@]}"; do
    for ver in ${VERSIONS[$chart]}; do
      tgz="/tmp/${chart}-${ver}.tgz"
      make_chart_tgz "$chart" "$ver" "$tgz"
      cp -f "$tgz" "${STORE}/${repo}/charts/"
      echo "  Copied ${tgz} -> ${STORE}/${repo}/charts/"
    done
  done
done

# Small wait so the server sees new files
sleep 1

# Verify endpoints
echo
echo "=== /health ==="
curl -sS -i "${CM_URL}/health" || true
echo

echo "=== /api/repositories ==="
repos="$(curl -sS "${CM_URL}/api/repositories" || echo "[]")"
echo "$repos"
echo

echo "=== /api/<repo>/charts ==="
for repo in "${REPOS[@]}"; do
  echo "-- ${repo} --"
  if [ "$HAS_JQ" -eq 1 ]; then
    curl -sS "${CM_URL}/api/${repo}/charts" | jq .
  else
    curl -sS "${CM_URL}/api/${repo}/charts"
  fi
  echo
done

echo "=== <repo>/index.yaml (first 20 lines) ==="
for repo in "${REPOS[@]}"; do
  echo "-- ${repo} --"
  curl -sS "${CM_URL}/${repo}/index.yaml" | head -n 20 || true
  echo
done

echo "Done."
