#!/usr/bin/env bash
# Deploy LinkPulse to Antideploy.
#
#   ./deploy/antideploy.sh api     # backend/  -> https://lnkp.antideploy.app      (API + short links)
#   ./deploy/antideploy.sh web     # frontend/ -> https://linkpulse.antideploy.app (dashboard, static site)
#   ./deploy/antideploy.sh all
#
# Needs an account token in ~/.antideploy/config.json (created by the Antideploy device login; never
# commit it) and the applicationId of each app in backend/.antideploy.json and frontend/.antideploy.json
# (no secrets there, safe to commit). See deploy/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

API=https://antideploy.com/api/v1
API_URL=https://lnkp.antideploy.app
WEB_URL=https://linkpulse.antideploy.app

[ -s ~/.antideploy/config.json ] || { echo "No Antideploy token: run the device login first (deploy/README.md)." >&2; exit 1; }
# Loaded into a variable, never printed.
TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' ~/.antideploy/config.json)

app_id() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["applicationId"])' "$1/.antideploy.json"; }

# Never ship secrets, local databases, virtualenvs or build output.
EXCLUDES=(--exclude=.env --exclude=.env.antideploy --exclude=.venv --exclude=node_modules --exclude=dist --exclude='*.db'
          --exclude=__pycache__ --exclude=.pytest_cache --exclude=.antideploy.json)

set_vars() {  # set_vars <dir> <json object of variables>; stored encrypted, applied on the next deploy
  local id; id=$(app_id "$1")
  curl -fsS -X PUT "$API/secrets?applicationId=$id" -H "Authorization: Bearer $TOKEN" \
    -H 'content-type: application/json' -d "{\"env\": $2}" \
    | python3 -c 'import json,sys; print("variables:", ", ".join(json.load(sys.stdin)["keys"]))'
}

push() {  # push <dir> [extra tar excludes...]
  local dir=$1; shift
  local id; id=$(app_id "$dir")
  echo "Deploying $dir ..."
  tar czf - -C "$dir" "${EXCLUDES[@]}" "$@" . \
    | curl -fsS -X POST "$API/deploy?applicationId=$id" -H "Authorization: Bearer $TOKEN" -F "archive=@-" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status") or "queued", d.get("taskId", ""))' \
    | tee /dev/stderr | grep -q '^unchanged' && redeploy "$id" || true
}

redeploy() {  # same code, new variables: build again without uploading
  curl -fsS -X POST "$API/redeploy" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
    -d "{\"applicationId\": \"$1\"}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("code unchanged; rebuilding with current variables:", d.get("taskId", d))'
}

deploy_api() {
  # SECRET_KEY and DATABASE_URL are filled in by Antideploy itself; Redis is not used there.
  set_vars backend "{\"BASE_URL\": \"$API_URL\", \"FRONTEND_URL\": \"$WEB_URL\", \"TRUST_PROXY_HEADERS\": \"true\",
                     \"REDIS_URL\": \"none\", \"CHECK_REACHABILITY\": \"true\"}"
  push backend
}

deploy_web() {
  # The Dockerfile and nginx.conf are for docker compose; leaving them out lets Antideploy
  # build the Vite app as a static site (free, and not counted as a live application).
  # Uploaded .env files are not used by Antideploy's build, so VITE_API_URL is stored as a variable
  # of the app; it is present when Vite builds. (frontend/.env.production does the same for local builds.)
  set_vars frontend "{\"VITE_API_URL\": \"$API_URL\"}"
  push frontend --exclude=Dockerfile --exclude=nginx.conf
}

case "${1:-all}" in
  api) deploy_api ;;
  web) deploy_web ;;
  all) deploy_api; deploy_web ;;
  *) echo "usage: $0 [api|web|all]" >&2; exit 2 ;;
esac
echo "Watch progress at https://antideploy.com/console"
