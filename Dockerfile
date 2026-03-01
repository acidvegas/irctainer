# Looking Glass IRC Bot - Developed by acidvegas in Python (https://git.supernets.org/acidvegas/looking-glass-irc)
# Dockerfile

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
	apt-utils \
	ca-certificates \
	curl \
	dnsutils \
	git \
	grc \
	iputils-ping \
	jq \
	libpcap-dev \
	masscan \
	mtr-tiny \
	net-tools \
	netcat-openbsd \
	nmap \
	openssl \
	python3 \
	python3-pip \
	python3-venv \
	socat \
	traceroute \
	unzip \
	wget \
	whois \
	&& apt-get clean

RUN echo 'GRC_ALIASES=true' > /etc/default/grc \
	&& sed -i 's/tty -s && //g' /etc/profile.d/grc.sh \
	&& sed -i 's/"$GRC -es"/"$GRC -es --colour=on"/g' /etc/profile.d/grc.sh
RUN printf 'shopt -s expand_aliases\n\
[ -f /etc/profile.d/grc.sh ] && . /etc/profile.d/grc.sh\n\
alias diff="diff --color=always"\n\
alias dmesg="dmesg --color=always"\n\
alias dir="dir --color=always"\n\
alias egrep="egrep --color=always"\n\
alias fgrep="fgrep --color=always"\n\
alias grep="grep --color=always"\n\
alias ip="ip -color=always"\n\
alias jq="jq -C"\n\
alias less="less -R"\n\
alias ls="ls --color=always"\n\
alias ncdu="ncdu --color dark -rr"\n\
alias tree="tree -C"\n\
alias vdir="vdir --color=always"\n\
alias watch="watch --color"\n\
' > /root/.bashrc

CMD ["sleep", "infinity"]
