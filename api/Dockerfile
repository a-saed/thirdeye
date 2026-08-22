# Two stages: the build image carries the Go toolchain, the runtime does not.
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
# CGO off: parquet-go and h3-go are pure Go, so this stays a static binary and
# the runtime image needs no libc.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/thirdeye-api .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 app
WORKDIR /app
COPY --from=build /out/thirdeye-api /app/thirdeye-api
COPY limitations.json /app/limitations.json
# Parquet tables and the built SPA are mounted at run time, not baked in: the
# tables change monthly and are ~140 MB in RAM, the SPA changes per deploy.
USER app
EXPOSE 8080
ENV DATA_DIR=/data WEB_DIR=/web
ENTRYPOINT ["/bin/sh","-c","exec /app/thirdeye-api -data $DATA_DIR -limits /app/limitations.json -web $WEB_DIR -addr 0.0.0.0:8080"]
