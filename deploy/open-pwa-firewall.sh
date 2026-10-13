#!/bin/sh
# Run in the owner's authenticated Google Cloud Shell, not the VM's scoped account.
# Only this instance receives the dedicated tag; only TCP 443 is allowed.
set -eu
gcloud compute instances add-tags remote-asst \
  --project=virtual1-505703 --zone=us-central1-f --tags=personal-asis-pwa
gcloud compute firewall-rules create personal-asis-pwa-https \
  --project=virtual1-505703 --network=default --direction=INGRESS \
  --allow=tcp:443 --source-ranges=0.0.0.0/0 --target-tags=personal-asis-pwa \
  --description="Authenticated Personal Asis PWA HTTPS on remote-asst only"
