# Two stages, the same shape for every language: the build image assembles the app with ap-build,
# the runtime image runs it. The app serves HTTP on $PORT.
{%- set lang = "java" if cookiecutter.language in ["java", "kotlin"] else cookiecutter.language %}
FROM ghcr.io/actionplatform/build-{{ lang }}:0 AS build
ARG TARGETARCH
WORKDIR /w
COPY . .
RUN AP_ARCH=$([ "$TARGETARCH" = "amd64" ] && echo x86_64 || echo arm64) AP_ARTIFACTS=/out ap-build package

FROM ghcr.io/actionplatform/runtime-{{ lang }}:0
WORKDIR /app
COPY --from=build /out /app
ENV PORT=8000
EXPOSE 8000
{%- if cookiecutter.language == "python" %}
ENV PYTHONPATH=/app
CMD ["-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
{%- elif cookiecutter.language == "node" %}
CMD ["dist/server.js"]
{%- elif cookiecutter.language == "go" %}
ENTRYPOINT ["/app/bootstrap"]
{%- elif cookiecutter.language == "ruby" %}
CMD ["bundle", "exec", "rackup", "-s", "webrick", "-o", "0.0.0.0", "-p", "8000"]
{%- else %}
CMD ["-jar", "/app/app.jar", "--server.port=8000"]
{%- endif %}
