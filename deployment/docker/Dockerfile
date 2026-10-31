# Build from the FINAL composed repository root, never a historical variant.
# Operator-provided private-linux/ contains a complete reviewed Linux build.
FROM python:3.15-slim-bookworm@sha256:4e03260adeeebafccd084f3584e6b84823aba5651cfb53ef8a078ed441ddf9cd
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp/nebula-home
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libstdc++6 libgcc-s1 libglib2.0-0 libgomp1 libatomic1 \
    libx11-6 libxcursor1 libxrandr2 libxi6 libxrender1 libxext6 libsm6 \
    libasound2 libnss3 libxss1 libgl1 libsdl2-2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 nebula && useradd --uid 1000 --gid 1000 --no-create-home nebula \
    && mkdir -p /opt/nebula /opt/nebula-container /opt/nebula-runtime /var/lib/nebula \
    && chown 1000:1000 /var/lib/nebula
WORKDIR /opt/nebula
COPY deployment/docker/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt
COPY backend/ backend/
COPY protocol/ protocol/
COPY tools/ tools/
COPY THIRD_PARTY_NOTICES.md docs/LICENSING.md /usr/share/licenses/nebula-preserved/
COPY mirror-server/UnityProject/Assets/Mirror/LICENSE /usr/share/licenses/nebula-preserved/Mirror-LICENSE
COPY mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/Telepathy/Telepathy/LICENSE /usr/share/licenses/nebula-preserved/Telepathy-LICENSE
COPY mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/SimpleWebTransport/LICENSE /usr/share/licenses/nebula-preserved/SimpleWebTransport-LICENSE
COPY mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/KCP/kcp2k/LICENSE /usr/share/licenses/nebula-preserved/kcp2k-LICENSE
COPY mirror-server/UnityProject/Assets/Mirror/Runtime/Transports/KCP/kcp2k/where-allocation/LICENSE /usr/share/licenses/nebula-preserved/where-allocation-LICENSE
COPY deployment/docker/entrypoint.py deployment/docker/healthcheck.py /opt/nebula-container/
COPY deployment/docker/private-linux/ /opt/nebula-runtime/
# The complete build must retain its original NebulaServer_Data tree/plugins.
RUN test -f /opt/nebula-runtime/build/NebulaServer.x86_64 \
    && test -f /opt/nebula-runtime/build/NebulaServer_Data/Managed/Assembly-CSharp.dll \
    && test -f /opt/nebula-runtime/build-linux-validation.json \
    && chmod 0555 /opt/nebula-runtime/build/NebulaServer.x86_64
USER 1000:1000
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "/opt/nebula-container/entrypoint.py"]
