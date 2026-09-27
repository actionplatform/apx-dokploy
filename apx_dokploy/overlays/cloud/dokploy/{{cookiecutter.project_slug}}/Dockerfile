# Two stages, the same shape for every language: the build image assembles the app with ap-build,
# the runtime image runs it. The app serves HTTP on $PORT.
{%- set lang = "java" if cookiecutter.language in ["java", "kotlin"] else cookiecutter.language %}
{%- set version = {"python": "3.12", "node": "22", "go": "1.27", "java": "21", "ruby": "3.3"}[lang] %}
{%- set arg = lang|upper ~ "_VERSION" %}
# The language version: every build/runtime image exists per version (see actionplatform/images-base versions.json).
ARG {{ arg }}={{ version }}
FROM ghcr.io/actionplatform/build-{{ lang }}:${ {{- arg -}} } AS build
ARG TARGETARCH
WORKDIR /w
COPY . .
RUN AP_ARCH=$([ "$TARGETARCH" = "amd64" ] && echo x86_64 || echo arm64) AP_ARTIFACTS=/out ap-build package

FROM ghcr.io/actionplatform/runtime-{{ lang }}:${ {{- arg -}} }
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
