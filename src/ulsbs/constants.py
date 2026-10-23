# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared names and fixed build/format policies.

Keep algorithm-specific lookup tables, regexes, and private format versions in
their owning modules. These values are developer policies, not substitutes for
the supported songbook configuration options.
This file is part of the 'ulsbs' package.
"""

# Accepted TeX-like file suffixes when resolving includes
TEX_SUFFIXES = (".tex", ".latex", ".lytex", ".lylatex")

SELECTION_FNAME_PREFIX = "ul-selection"

LYRICSONLY_FNAMEPART = "_LYRICS-ONLY"
CHARANGO_FNAMEPART = "_CHARANGO"
BASSCLEF_FNAMEPART = "_BASSCLEF"
MULTIKEY_FNAMEPART = "_MULTIKEY"

NODEPLOY_FNAMEPART = "_NODEPLOY"
PAPERA5_FNAMEPART = "_A5"

TEMP_DIRNAME = "temp"
RESULT_DIRNAME = "result"
DEPLOY_DIRNAME = "deploy"
CONTENT_DIRNAME = "content"
INCLUDE_DIRNAME = "include"
TAG_DEFINITION_FILENAME = "tags.can" # under INCLUDE_DIRNAME
CONFIG_FILENAME = "ulsbs-config.toml"

RESULTLIST_SEPARATOR = "\t"
RESULTLIST_BASENAME = "ulsbs-results"

RESULT_TYPE_INFO           = "INFO          "
RESULT_TYPE_MAIN_PDF       = "MAINPDF       "
RESULT_TYPE_MULTIKEY_PDF   = "MULTIKEYPDF   "
# Mandatory range-package entry point, independent of optional song JSON export.
RESULT_TYPE_MULTIKEY_JSON  = "MULTIKEYJSON  "
RESULT_TYPE_PRINTOUT_PDF   = "PRINTOUTPDF   "
RESULT_TYPE_JSON           = "JSON          "
RESULT_TYPE_IMAGE          = "IMAGE         "
RESULT_TYPE_MIDIDIR        = "MIDIDIR       "
RESULT_TYPE_AUDIODIR       = "AUDIODIR      "
RESULT_TYPE_COMMONICON     = "COMMONICON    "
RESULT_TYPE_COMMONMETADATA = "COMMONMETADATA"
RESULT_TYPE_COMMONOTHER    = "COMMONOTHER   "
RESULT_TYPE_COMMONSOCIAL   = "COMMONSOCIAL  "

RESULT_PRINTOUT_SUBDIRNAME = "printouts"
RESULT_MULTIKEY_SUBDIRNAME = "multikey"
RESULT_JSON_SUBDIRNAME = "json"
RESULT_IMAGE_SUBDIRNAME = "images"
RESULT_MIDI_SUBDIRNAME = "midi"
RESULT_AUDIO_SUBDIRNAME = "audio"
RESULT_COMMON_SUBDIRNAME = "other"

DEPLOY_IMAGE_SUBDIRNAME = "images"
DEPLOY_PRINTOUT_SUBDIRNAME = "printouts"
DEPLOY_MULTIKEY_SUBDIRNAME = "multikey"
DEPLOY_JSON_SUBDIRNAME = "json"
DEPLOY_MIDI_SUBDIRNAME = "midi"
DEPLOY_AUDIO_SUBDIRNAME = "audio"
DEPLOY_COMMONICON_SUBDIRNAME = f"{RESULT_IMAGE_SUBDIRNAME}/icons"
DEPLOY_COMMONSOCIAL_SUBDIRNAME = f"{RESULT_IMAGE_SUBDIRNAME}/social"
DEPLOY_COMMONMETADATA_SUBDIRNAME = "metadata"
DEPLOY_COMMONOTHER_SUBDIRNAME = "other"

# Protocol-v1 bound on the entire UTF-8 MULTIKEY index, including its manifest;
# not a PDF-size limit or memory budget. Raising it requires consumer agreement.
MULTIKEY_INDEX_MAX_BYTES = 4 * 1024 * 1024

# Minimum qpdf qualified for OCG-preserving primary-input extraction. Every
# package must still pass semantic validation, including on newer versions.
MULTIKEY_MIN_QPDF_VERSION = (12, 2, 0)

# Reject alternate notation that needs uniform scaling below this fraction of
# natural size to fit the original system's width and height. Pass this policy
# to cache validation and generated TeX bindings; do not duplicate it there.
# This is separate from the configurable shrinking of inline chord names.
LILYPOND_SCORE_MIN_SCALE = 0.60

# Maximum extra full LuaLaTeX passes after the normal draft/two-full sequence.
# Reference and optional-content checks share this budget; retries do not repeat
# LilyPond engraving or index generation. Only unsettled builds use the budget.
LUALATEX_MAX_EXTRA_PASSES = 2

SONG_IDX_SCRIPT_REL = "ulsbs/src/ulsbs/assets/tex/ext_packages/songs/songidx.lua"
SORT_LOCALE = "fi_FI.utf8"

GENAUDIO_ALBUMTITLE = "ULSBS (audio generated from MIDI)"

COVERIMAGE_HEIGHT = "1024"
COVERIMAGE_MODIFIED_FNAME_POSTFIX = "_MODIFIED"

JSON_INCLUDE_PLAIN_LOWERCASE_LYRICS: bool = False

ASSUMED_OS_MEM_GB: float = 2
ASSUMED_JOB_MEM_GB: float = 1.2
