# docker buildx create --use --bootstrap \
#   --name mybuilder \
#   --driver docker-container \
#   --buildkitd-config /etc/buildkitd.toml

docker buildx build \
  --builder mybuilder \
  --platform linux/amd64,linux/arm64 \
  --push -t registry.internal/asterisk-webhook-relay:latest \
  -f docker/Dockerfile \
  .

# docker buildx rm mybuilder
