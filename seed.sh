#!/usr/bin/env bash
set -euo pipefail

CM_URL="${CM_URL:-http://localhost:18080}"
STORE="${STORE:-$HOME/captain-chart-museum/chartstore}"

REPOS=("repoA" "repoB")
CHARTS=("webapp" "api")
declare -A VERSIONS
VERSIONS["webapp"]="0.1.0 0.1.1 0.2.0"
VERSIONS["api"]="1.0.0 1.1.0"

echo "Using ChartMuseum at: ${CM_URL}"
echo "Writing charts into: ${STORE}"

# Create repo folder structure
for r in "${REPOS[@]}"; do
  mkdir -p "${STORE}/${r}/charts"
done

# Build a minimal Helm-like chart tarball without Helm installed
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

echo "Seeding charts by copying files into ${STORE}..."
for r in "${REPOS[@]}"; do
  for c in "${CHARTS[@]}"; do
    for v in ${VERSIONS[$c]}; do
      tgz="/tmp/${c}-${v}.tgz"
      make_chart_tgz "$c" "$v" "$tgz"
      cp -f "$tgz" "${STORE}/${r}/charts/"
      echo "  Copied ${tgz} -> ${STORE}/${r}/charts/"
    done
  done
done

echo "Waiting a moment for index generation..."
sleep 1

echo
echo "Verify /api/repositories:"
curl -sS "${CM_URL}/api/repositories" || true
echo

echo "Verify /api/<repo>/charts:"
for r in "${REPOS[@]}"; do
  echo "-- ${r} --"
  curl -sS "${CM_URL}/api/${r}/charts" || true
  echo
done

echo "Verify <repo>/index.yaml (first 20 lines):"
for r in "${REPOS[@]}"; do
  echo "-- ${r} --"
  curl -sS "${CM_URL}/${r}/index.yaml" | head -n 20 || true
  echo
done

echo "Done."
