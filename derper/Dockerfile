# 构建阶段
FROM golang:1.23-alpine AS builder
WORKDIR /app

# 设置 Go 代理（国内环境可加速）
RUN go env -w GOPROXY=https://goproxy.cn,direct 2>/dev/null || true

# 安装 derper
RUN go install tailscale.com/cmd/derper@latest

# 运行阶段
FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /go/bin/derper /usr/local/bin/derper
ENTRYPOINT ["derper"]
