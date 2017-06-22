docker build \
   #  --build-arg BUILD_PROJECT="spinnaker-jtk54" \
   # --build-arg  BUILD_ACCOUNT="514021394939-compute@developer.gserviceaccount.com" \
   # --build-arg BUILD_KEY="$(cat build.json)" \
   # --build-arg DOCKER_PROJECT="spinnaker-marketplace" \
   # --build-arg DOCKER_ACCOUNT="bom-writer@spinnaker-marketplace.iam.gserviceaccount.com" \
   # --build-arg DOCKER_KEY="$(cat market.json)" \
   # --build-arg CLUSTER_NAME="halyard-woot" \
   # --build-arg KUBE_CONF="$(python -c 'import sys, yaml, json; json.dump(yaml.load(sys.stdin), sys.stdout, indent=3)' < config)" \
   -t jtk54/halyard-k8s -f hal_install_spin.docker .
