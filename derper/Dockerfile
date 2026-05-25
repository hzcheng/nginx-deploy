# 构建阶段
FROM golang:1.26-alpine AS builder
WORKDIR /app

ARG GOPROXY=https://proxy.golang.org,direct
RUN go env -w GOPROXY=${GOPROXY}

ARG DERP_VERSION=v1.80.0
RUN go install tailscale.com/cmd/derper@${DERP_VERSION}

# 运行阶段
FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /go/bin/derper /usr/local/bin/derper
CMD ["derper"]
