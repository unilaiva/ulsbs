% SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
% SPDX-License-Identifier: GPL-3.0-or-later
%
% Songbook document class for ULSBS.
% This file is part of the 'ulsbs' package.
%
% Requires LuaLaTeX and configures the book class, package options and PDF metadata
% before loading ulsbs.sty. Inherit from this class for custom songbook classes.

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{ulsbs-songbook}[ULSBS songbook class]

\RequirePackage{iftex}
\ifLuaTeX\else
  \ClassError{ulsbs-songbook}{LuaLaTeX is required}{%
    Compile this document with lualatex or ulsbs-compile, not pdfLaTeX or XeLaTeX.}
  % Stop even in nonstopmode, rather than publishing a partial document.
  \expandafter\@@end
\fi

% Ensure backend and set PDF version
\RequirePackage{expl3}
\ExplSyntaxOn
  \sys_ensure_backend:
  \pdf_version_gset:n{1.7}
\ExplSyntaxOff

% Resolve availability/identity from the raw main options before base-class key
% processing. Preset application waits for the outermost custom class to return.
\let\ulsbs@classpath\@empty
\input{ulsbs-variants.code.tex}

\RequirePackage{kvoptions}
\RequirePackage{etoolbox}

% Our key=value options (if not defined, default value is empty = {})
\SetupKeyvalOptions{family=ulsbs,prefix=ulsbs@}
\DeclareStringOption{paper}
\DeclareStringOption{maintitle}
\DeclareStringOption{subtitle}
\DeclareStringOption{subsubtitle}
\DeclareStringOption{motto}
\DeclareStringOption{wwwlink}
\DeclareStringOption{wwwqr}
\DeclareStringOption{imprintnote}
\DeclareStringOption{author}
\DeclareStringOption{subject}
\DeclareStringOption{keywords} % use comma as separator
\DeclareStringOption[english]{language}
\DeclareStringOption[8mm]{bindingoffset}
% Availability is owned by the raw main-source reader, not inherited key values.
\DeclareStringOption{variants}

% Omit book class's paper sizes, as we use our own paper option that will be
% passed to geometry, which will handle paper size and layout settings.
\DeclareOption{a4paper}{}
\DeclareOption{a5paper}{}
\DeclareOption{b5paper}{}
\DeclareOption{letterpaper}{}
\DeclareOption{legalpaper}{}
\DeclareOption{executivepaper}{}

\newif\ifulsbs@fontsizespecified
\ulsbs@fontsizespecifiedfalse
\DeclareOption{10pt}{\PassOptionsToClass{10pt}{book}\ulsbs@fontsizespecifiedtrue}
\DeclareOption{11pt}{\PassOptionsToClass{11pt}{book}\ulsbs@fontsizespecifiedtrue}
\DeclareOption{12pt}{\PassOptionsToClass{12pt}{book}\ulsbs@fontsizespecifiedtrue}

% Forward selected base-class options explicitly to book
\DeclareOption{openright}{\PassOptionsToClass{openright}{book}}
\DeclareOption{openany}{\PassOptionsToClass{openany}{book}}
\DeclareOption{oneside}{\PassOptionsToClass{oneside}{book}}
\DeclareOption{twoside}{\PassOptionsToClass{twoside}{book}}
\DeclareOption{draft}{\PassOptionsToClass{draft}{book}}
\DeclareOption{final}{\PassOptionsToClass{final}{book}}
\DeclareOption{titlepage}{\PassOptionsToClass{titlepage}{book}}
\DeclareOption{notitlepage}{\PassOptionsToClass{notitlepage}{book}}
\DeclareOption{twocolumn}{\PassOptionsToClass{twocolumn}{book}}
\DeclareOption{onecolumn}{\PassOptionsToClass{onecolumn}{book}}
\DeclareOption{fleqn}{\PassOptionsToClass{fleqn}{book}}
\DeclareOption{leqno}{\PassOptionsToClass{leqno}{book}}

% Process our keyvals immediately; then swallow any remaining unknowns
\ProcessKeyvalOptions*
\DeclareOption*{}
\ProcessOptions\relax
% As a final guard, clear any leftover global unused options
\AtEndOfClass{\let\@unusedoptionlist\@empty}


% Load base class
\ifulsbs@fontsizespecified
  \LoadClass{book}
\else % default to 10pt
  \LoadClass[10pt]{book}
\fi


% Define macros only if options were given; else leave undefined
% for ulsbs.sty defaults
\ifdefempty{\ulsbs@paper}{}{% not empty
  \newcommand{\ulPaperSize}{\ulsbs@paper}
}
\ifdefempty{\ulsbs@maintitle}{}{% not empty
  \newcommand{\ulMainBookTitle}{\ulsbs@maintitle}
}
\ifdefempty{\ulsbs@subtitle}{}{% not empty
  \newcommand{\ulSubBookTitle}{\ulsbs@subtitle}
}
\ifdefempty{\ulsbs@subsubtitle}{}{% not empty
  \newcommand{\ulSubSubBookTitle}{\ulsbs@subsubtitle}
}
\ifdefempty{\ulsbs@motto}{}{% not empty
  \newcommand{\ulBookMotto}{\ulsbs@motto}
}
\ifdefempty{\ulsbs@wwwlink}{}{% not empty
  \newcommand{\ulBookWebsiteLink}{\ulsbs@wwwlink}
}
\ifdefempty{\ulsbs@wwwqr}{}{% not empty
  \newcommand{\ulBookWebsiteLinkQrImage}{\ulsbs@wwwqr}
}
\ifdefempty{\ulsbs@imprintnote}{}{% not empty
  \newcommand{\ulImprintPageFootnote}{\ulsbs@imprintnote}
}
\ifdefempty{\ulsbs@author}{}{% not empty
  \newcommand{\ulBookAuthor}{\ulsbs@author}
}
\ifdefempty{\ulsbs@subject}{}{% not empty
  \newcommand{\ulBookSubject}{\ulsbs@subject}
}
\ifdefempty{\ulsbs@keywords}{}{% not empty
  \newcommand{\ulBookKeywords}{\ulsbs@keywords}
}
\ifdefempty{\ulsbs@language}{}{% not empty
  \newcommand{\ulPreliminaryLanguage}{\ulsbs@language}
}
\ifdefempty{\ulsbs@bindingoffset}{}{% not empty
  \newcommand{\ulBindingOffset}{\ulsbs@bindingoffset}
}


% Load the ulsbs package
\RequirePackage{ulsbs}
