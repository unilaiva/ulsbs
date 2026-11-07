# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Dockerfile for compiling ULSBS songbooks
# ========================================
#
# Works with docker and podman.
#
# Containers created from the image described here is intended to be only run
# with "ulsbs-compile" script, as that script will setup the *required* bind
# mounts, use the correct user id from host etc.
#
# This file is part of the 'ulsbs' package.

# Use Ubuntu 26.04 LTS (resolute):
FROM ubuntu:resolute-20261024.1

# Installs everything needed for compiling the songbook.
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bash \
    context \
    context-modules \
    ffmpeg \
    fluidsynth \
    fluid-soundfont-gm \
    fonts-noto-extra \
    fonts-noto-core \
    fonts-noto-mono \
    imagemagick \
    lilypond \
    poppler-utils \
    python3 \
    python3-pikepdf \
    qpdf \
    texlive \
    texlive-font-utils \
    texlive-lang-arabic \
    texlive-lang-english \
    texlive-lang-european \
    texlive-lang-portuguese \
    texlive-lang-spanish \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-luatex \
    texlive-music \
    texlive-plain-generic \
    qrencode \
  && rm -rf /var/lib/apt/lists/*

# Copy a minimal client config for Pipewire, as that will make fluidsynth's
# logging happy. We are not really using Pipewire.
RUN mkdir -p /etc/pipewire
COPY pipewire-client.conf /etc/pipewire/client.conf

# Setup a non-root user for everything. Make it's home world-writable so that
# we can use host machine's user id and still have access to container's
# ~/.texlive20?? when compiling.
RUN useradd --create-home --shell /bin/bash ulsbs \
  && chmod 777 /home/ulsbs \
  && chmod g+s /home/ulsbs

# Create index databases and caches used by TeX and Lilypond
RUN update-texmf \
  && mtxrun --generate \
  && texhash \
  && fc-cache -f \
  && luaotfload-tool --update

ARG BUILT_BY_ULSBS_VERSION
LABEL built.by.ulsbs.version=$BUILT_BY_ULSBS_VERSION

USER ulsbs

ENV HOME="/home/ulsbs" \
    ULSBS_INTERNAL_RUNNING_IN_CONTAINER="true"

# Create user caches and make world-writeable to be used with host machine's
# user id:
RUN fc-cache -f \
  && luaotfload-tool --update \
  && lilypond -dshow-available-fonts >/dev/null \
  && find /home/ulsbs -type d -exec chmod 777 {} + \
  && find /home/ulsbs -type f -exec chmod 666 {} +

# Make "/home/ulsbs" a volume to make caches within it persistent. This includes
# ULSBS's multikey cache for Lilypond outputs, and ordinary TeX and font caches.
VOLUME ["/home/ulsbs"]

WORKDIR /songbook-data

# Default command for interactive use; the host-side launcher will override it.
CMD ["bash"]
