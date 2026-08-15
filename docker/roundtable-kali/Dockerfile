FROM kalilinux/kali-rolling:latest

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV PLAYWRIGHT_MCP_BROWSER=chromium
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
ENV PYTHONUNBUFFERED=1
ENV GOPATH=/home/rt/go
ENV PATH="/home/rt/.local/bin:/home/rt/go/bin:${PATH}"

RUN rm -f /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/kali.sources \
    && printf '%s\n' 'deb http://kali.download/kali kali-rolling main contrib non-free non-free-firmware' > /etc/apt/sources.list \
    && apt_get() { apt-get -o Acquire::Retries=8 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 "$@"; } \
    && install_with_retry() { \
        local attempt; \
        for attempt in 1 2 3 4 5; do \
          if apt_get install -y --fix-missing "$@"; then \
            return 0; \
          fi; \
          if [[ "${attempt}" -eq 5 ]]; then \
            return 1; \
          fi; \
          apt-get clean; \
          rm -rf /var/cache/apt/archives/partial/*; \
          apt_get update; \
          sleep 5; \
        done; \
      } \
    && apt_get update \
    && install_with_retry kali-linux-headless \
    && install_with_retry --no-install-recommends \
    adb \
    bsdextrautils \
    ca-certificates \
    chisel-common-binaries \
    curl \
    default-jre-headless \
    dirsearch \
    enum4linux-ng \
    exiftool \
    fd-find \
    feroxbuster \
    ffuf \
    file \
    git \
    gitleaks \
    gobuster \
    iputils-ping \
    jq \
    krb5-user \
    naabu \
    ncat \
    netcat-traditional \
    netexec \
    nikto \
    openssh-client \
    procps \
    python3 \
    python3-pip \
    python3-venv \
    ripgrep \
    rlwrap \
    sshpass \
    tmux \
    unzip \
    wget \
    xxd \
    xz-utils \
    yq \
    zip \
    zstd \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && if command -v setcap >/dev/null 2>&1 && [ -e /usr/lib/nmap/nmap ]; then setcap -r /usr/lib/nmap/nmap || true; fi \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages --ignore-installed --no-cache-dir \
    awscli \
    bloodyad \
    'capstone<6' \
    coercer \
    pwntools \
    pymongo \
    pwncat \
    tccli

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) node_arch='x64'; go_arch='amd64'; pd_arch='amd64'; dalfox_arch='x86_64'; cloudfox_arch='amd64'; kerbrute_asset='kerbrute_linux_amd64'; ;; \
      arm64) node_arch='arm64'; go_arch='arm64'; pd_arch='arm64'; dalfox_arch='aarch64'; cloudfox_arch='arm64'; kerbrute_asset=''; ;; \
      *) echo "unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    go_version="$(curl -fsSL https://go.dev/dl/?mode=json | jq -r '[.[] | select(.stable == true)][0].version')"; \
    test -n "${go_version}"; \
    curl -fsSL "https://go.dev/dl/${go_version}.linux-${go_arch}.tar.gz" -o /tmp/go.tar.gz; \
    rm -rf /usr/local/go; \
    tar -xzf /tmp/go.tar.gz -C /usr/local; \
    ln -sf /usr/local/go/bin/go /usr/local/bin/go; \
    ln -sf /usr/local/go/bin/gofmt /usr/local/bin/gofmt; \
    rm -f /tmp/go.tar.gz; \
    node_version="$(curl -fsSL https://nodejs.org/dist/index.json | jq -r '[.[] | select(.version | startswith("v22."))][0].version')"; \
    test -n "${node_version}"; \
    curl -fsSL "https://nodejs.org/dist/${node_version}/node-${node_version}-linux-${node_arch}.tar.xz" -o /tmp/node.tar.xz; \
    mkdir -p /usr/local/lib/nodejs; \
    tar -xJf /tmp/node.tar.xz -C /usr/local/lib/nodejs; \
    ln -sf "/usr/local/lib/nodejs/node-${node_version}-linux-${node_arch}/bin/node" /usr/local/bin/node; \
    ln -sf "/usr/local/lib/nodejs/node-${node_version}-linux-${node_arch}/bin/npm" /usr/local/bin/npm; \
    ln -sf "/usr/local/lib/nodejs/node-${node_version}-linux-${node_arch}/bin/npx" /usr/local/bin/npx; \
    rm -f /tmp/node.tar.xz; \
    npm install -g \
      @anthropic-ai/claude-code@2.1.98 \
      @mariozechner/pi-coding-agent@0.73.0 \
      @openai/codex \
      @playwright/cli@latest; \
    ln -sf "/usr/local/lib/nodejs/node-${node_version}-linux-${node_arch}/bin/codex" /usr/local/bin/codex; \
    ln -sf "/usr/local/lib/nodejs/node-${node_version}-linux-${node_arch}/bin/playwright" /usr/local/bin/playwright; \
    mkdir -p /tmp/tooling; \
    katana_tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/projectdiscovery/katana/releases/latest | sed 's#.*/##')"; \
    nuclei_tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/projectdiscovery/nuclei/releases/latest | sed 's#.*/##')"; \
    dalfox_tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/hahwul/dalfox/releases/latest | sed 's#.*/##')"; \
    cloudfox_tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/BishopFox/cloudfox/releases/latest | sed 's#.*/##')"; \
    curl -fsSL "https://github.com/projectdiscovery/katana/releases/download/${katana_tag}/katana_${katana_tag#v}_linux_${pd_arch}.zip" -o /tmp/tooling/katana.zip; \
    unzip -q /tmp/tooling/katana.zip -d /tmp/tooling/katana; \
    install -m 0755 /tmp/tooling/katana/katana /usr/local/bin/katana; \
    curl -fsSL "https://github.com/projectdiscovery/nuclei/releases/download/${nuclei_tag}/nuclei_${nuclei_tag#v}_linux_${pd_arch}.zip" -o /tmp/tooling/nuclei.zip; \
    unzip -q /tmp/tooling/nuclei.zip -d /tmp/tooling/nuclei; \
    install -m 0755 /tmp/tooling/nuclei/nuclei /usr/local/bin/nuclei; \
    curl -fsSL "https://github.com/hahwul/dalfox/releases/download/${dalfox_tag}/dalfox-${dalfox_tag}-linux-${dalfox_arch}.tar.gz" -o /tmp/tooling/dalfox.tar.gz; \
    tar -xzf /tmp/tooling/dalfox.tar.gz -C /tmp/tooling; \
    install -m 0755 "/tmp/tooling/dalfox-${dalfox_tag}-linux-${dalfox_arch}/dalfox" /usr/local/bin/dalfox; \
    curl -fsSL "https://github.com/BishopFox/cloudfox/releases/download/${cloudfox_tag}/cloudfox-linux-${cloudfox_arch}.zip" -o /tmp/tooling/cloudfox.zip; \
    unzip -q /tmp/tooling/cloudfox.zip -d /tmp/tooling/cloudfox; \
    install -m 0755 /tmp/tooling/cloudfox/cloudfox/cloudfox /usr/local/bin/cloudfox; \
    if [[ -n "${kerbrute_asset}" ]]; then \
      curl -fsSL "https://github.com/ropnop/kerbrute/releases/download/v1.0.3/${kerbrute_asset}" -o /usr/local/bin/kerbrute; \
      chmod 0755 /usr/local/bin/kerbrute; \
    else \
      GOBIN=/usr/local/bin go install github.com/ropnop/kerbrute@latest; \
    fi; \
    npx playwright install chromium; \
    rm -rf /tmp/tooling

RUN bash -c "$(curl -fsSL https://aliyuncli.alicdn.com/install.sh)" \
    && if [[ -x /root/bin/aliyun ]]; then ln -sf /root/bin/aliyun /usr/local/bin/aliyun; fi

RUN useradd -m -s /bin/bash rt \
    && echo "rt ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && install -d -o rt -g rt /home/rt/.config/nuclei \
    && install -d -o rt -g rt /home/rt/.local \
    && install -d -o rt -g rt /home/rt/.local/nuclei-templates \
    && install -d -o rt -g rt /home/rt/knowledges \
    && install -d -o rt -g rt /home/rt/tools \
    && install -d -o rt -g rt /home/rt/pocs \
    && install -d -o rt -g rt /home/rt/workspace \
    && chown -R rt:rt /home/rt

RUN git clone --depth 1 https://github.com/projectdiscovery/nuclei-templates.git /home/rt/.local/nuclei-templates \
    && git clone --depth 1 https://github.com/swisskyrepo/PayloadsAllTheThings.git /home/rt/knowledges/PayloadsAllTheThings \
    && git clone --depth 1 https://github.com/swisskyrepo/InternalAllTheThings.git /home/rt/knowledges/InternalAllTheThings \
    && git clone --depth 1 https://github.com/HackTricks-wiki/hacktricks.git /home/rt/knowledges/hacktricks \
    && git clone --depth 1 https://github.com/HackTricks-wiki/hacktricks-cloud.git /home/rt/knowledges/hacktricks-cloud \
    && curl -fsSL https://github.com/frohoff/ysoserial/releases/download/v0.0.6/ysoserial-all.jar -o /home/rt/tools/ysoserial.jar \
    && git clone --depth 1 https://github.com/ticarpi/jwt_tool.git /home/rt/tools/jwt_tool \
    && python3 -m pip install --break-system-packages --no-cache-dir -r /home/rt/tools/jwt_tool/requirements.txt \
    && git clone --depth 1 https://github.com/IOActive/jdwp-shellifier.git /home/rt/tools/jdwp-shellifier \
    && git clone --depth 1 https://github.com/iSee857/CVE-PoC.git /home/rt/pocs/CVE-PoC \
    && git clone --depth 1 https://github.com/zhzyker/exphub.git /home/rt/pocs/exphub \
    && git clone --depth 1 https://github.com/passwa11/2023Hvv_.git /home/rt/pocs/2023Hvv_ \
    && git clone --depth 1 https://github.com/Threekiii/Awesome-POC.git /home/rt/pocs/Awesome-POC \
    && git clone --depth 1 https://github.com/vulhub/vulhub.git /home/rt/pocs/vulhub \
    && chown -R rt:rt /home/rt

USER rt

RUN printf '%s\n' 'disable-update-check: true' 'update-template-dir: /home/rt/.local/nuclei-templates' > /home/rt/.config/nuclei/config.yaml \
    && nuclei -ut || true

WORKDIR /workspace

COPY entrypoint.sh /usr/local/bin/roundtable-kali-entrypoint
RUN sudo chmod +x /usr/local/bin/roundtable-kali-entrypoint

ENTRYPOINT ["/usr/local/bin/roundtable-kali-entrypoint"]
CMD ["bash"]
