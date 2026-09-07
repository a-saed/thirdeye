# Third Eye — single container: API, server-rendered documents, and the SPA.
#
# BUILD CONTEXT IS THE REPO ROOT, not api/. The image needs three things that
# live in different trees — the Go source, the derived parquet tables, and the
# built SPA — so the context has to contain all of them. .dockerignore is what
# keeps that from meaning 1.7 GB.
#
# THE DATA IS BAKED IN, NOT MOUNTED.
# The previous version of this file expected /data and /web as runtime mounts,
# which suited a VM with a volume. Cloud Run has no volume: an instance starts
# from the image and nothing else. The tables are 24 MB and the SPA 6.4 MB, so
# baking them costs ~30 MB of image and removes the entire class of "deployed
# but the volume was empty" failures. The consequence is that a monthly
# pipeline run now requires a rebuild and redeploy, not a file copy — that is
# recorded in docs/DEPLOYMENT.md.

FROM golang:1.24-alpine AS build
WORKDIR /src
# Dependencies first, so a source-only change does not re-download them.
COPY api/go.mod api/go.sum ./
RUN go mod download
# Toolchain AFTER the module download, deliberately: build-base is ~200 MB of
# apk and the download layer takes minutes. Installing it earlier would
# invalidate that cache on every toolchain change for no benefit.
RUN apk add --no-cache build-base
COPY api/*.go ./
# CGO IS REQUIRED. h3-go v4 is a cgo binding to the C H3 library and has no
# pure-Go fallback — CGO_ENABLED=0 fails with "build constraints exclude all
# Go files", which is also why the js/wasm build is impossible. The previous
# version of this file set CGO_ENABLED=0 and asserted h3-go was pure Go; that
# was wrong, and it means this image had never been built successfully.
#
# Static link anyway, so the runtime stays a bare alpine with no libc hunt:
# musl links statically without the glibc caveats, and osusergo/netgo keep the
# user and DNS lookups in Go rather than in the C library.
RUN CGO_ENABLED=1 go build -trimpath -tags osusergo,netgo \
      -ldflags="-s -w -extldflags=-static" -o /out/thirdeye-api .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 app
WORKDIR /app

COPY --from=build /out/thirdeye-api /app/thirdeye-api
COPY api/limitations.json /app/limitations.json
# Read by the API, the pipeline and the frontend from one place. The binary
# looks for it at config/thresholds.json relative to its working directory.
COPY config/thresholds.json /app/config/thresholds.json
# 24 MB of parquet, loaded into RAM at startup (~350 MB resident).
COPY data/derived/h3_tables /data
# The built SPA. Serving it from here is what lets one container answer
# everything and makes the 404 status correct — see api/spa.go.
COPY web/dist /web

USER app

# Cloud Run injects PORT and expects the container to honour it. The old file
# hardcoded 8080, which happens to be Cloud Run's default and would therefore
# have worked right up until it didn't.
ENV PORT=8080 DATA_DIR=/data WEB_DIR=/web
EXPOSE 8080
ENTRYPOINT ["/bin/sh","-c","exec /app/thirdeye-api -data $DATA_DIR -limits /app/limitations.json -web $WEB_DIR -addr 0.0.0.0:$PORT"]
