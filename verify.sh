#!/usr/bin/env bash
set -euo pipefail

CM_URL="${CM_URL:-http://localhost:18080}"
STORE="${STORE:-$HOME/captain-chart-museum/chartstore}"
REPOS=("repoA" "repoB")
CHARTS=("webapp" "api")
declare -A VERSIONS
VERSIONS["webapp"]="0.1.0 0.1.1 0.2.0"
VERSIONS["api"]="1.0.0 1.1.0"

make_chart_tgz() {
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

echo "Seeding into: $STORE"
mkdir -p "$STORE"
for r in "${REPOS[@]}"; do
  mkdir -p "$STORE/$r/charts"
  for c in "${CHARTS[@]}"; do
    for v in ${VERSIONS[$c]}; do
      tgz="/tmp/${c}-${v}.tgz"
      make_chart_tgz "$c" "$v" "$tgz"
      # place at repo root (this build reads /charts/<repo>/<file>.tgz)
      cp -f "$tgz" "$STORE/$r/"
      # keep a copy under charts/ too (harmless)
      cp -f "$tgz" "$STORE/$r/charts/"
      echo "  $r <= $(basename "$tgz")"
    done
  done
done

echo "Waiting for server to be ready..."
for i in {1..30}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$CM_URL/health" || true)
  [ "$code" = "200" ] && break || sleep 1
done
curl -sS "$CM_URL/health" || true
echo

echo "Direct GETs (should be 200):"
for f in \
  "repoA/webapp-0.1.0.tgz" \
  "repoA/api-1.0.0.tgz" \
  "repoB/webapp-0.2.0.tgz" \
  "repoB/api-1.1.0.tgz"; do
  printf "%-32s -> " "/$f"
  curl -sS -o /dev/null -w "HTTP %{http_code}\n" "$CM_URL/$f"
done
echo

echo "/api/repositories:"
curl -sS "$CM_URL/api/repositories"; echo
echo

for r in "${REPOS[@]}"; do
  echo "/api/$r/charts:"
  curl -sS "$CM_URL/api/$r/charts"; echo; echo
  echo "/$r/index.yaml (first 20 lines):"
  curl -sS "$CM_URL/$r/index.yaml" | head -n 20; echo
done
