#!/usr/bin/env bash
# Installs Dokploy on this machine, signs up an admin and prints DOKPLOY_URL / DOKPLOY_API_KEY for GITHUB_ENV.
set -euo pipefail

curl -sSL https://dokploy.com/install.sh | sudo sh >/tmp/dokploy-install.log 2>&1 || { tail -40 /tmp/dokploy-install.log; exit 1; }

url=http://localhost:3000
for _ in $(seq 1 90); do
  curl -fsS "$url/api/health" >/dev/null 2>&1 && break
  sleep 5
done
curl -fsS "$url/api/health" >/dev/null

jar=$(mktemp)
curl -fsS -c "$jar" -H 'content-type: application/json' -H "origin: $url" \
  -d '{"email":"ci@actionplatform.io","password":"ci-password-123","name":"ci"}' \
  "$url/api/auth/sign-up/email" >/dev/null

org=$(curl -fsS -b "$jar" -H "origin: $url" "$url/api/auth/organization/list" | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')

key=$(curl -fsS -b "$jar" -H 'content-type: application/json' -H "origin: $url" \
  -d "{\"0\":{\"json\":{\"name\":\"ci\",\"metadata\":{\"organizationId\":\"$org\"}}}}" \
  "$url/api/trpc/user.createApiKey?batch=1" | python3 -c 'import json,sys;d=json.load(sys.stdin)[0]["result"]["data"]["json"];print(d.get("key") or d.get("apiKey",{}).get("key"))')

echo "DOKPLOY_URL=$url"
echo "DOKPLOY_API_KEY=$key"
