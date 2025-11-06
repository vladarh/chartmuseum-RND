docker rm -f cm-local 2>/dev/null || true
docker run -d -p 18080:8080 \
  -v "$HOME/captain-chart-museum/chartstore:/charts:ro" \
  -e STORAGE=local \
  -e STORAGE_LOCAL_ROOTDIR=/charts \
  -e DEPTH=1 \
  -e DISABLE_API=false \
  -e ENABLE_LIST_REPOS=true \
  -e DISABLE_STATEFILES=true \
  -e ALWAYS_REGENERATE_CHART_INDEX=true \
  -e CACHE_INTERVAL=1s \
  -e DEBUG=1 \
  --name cm-local \
  chartmuseum:repo-list

docker logs -f cm-local | sed -n '1,5p'
