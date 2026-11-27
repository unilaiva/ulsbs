# ULSBS authoring commands for TeXstudio. Deliberately not an exhaustive API list.
# Titles and prose opt in to TeXstudio's native formatting and spell checking.

\begin{ulSongs}{index names%plain}
\end{ulSongs}
\beginsong{title}#L2
\beginsong{title}[metadata%keyvals]#L2
\endsong
\begin{song}{title}#L2
\begin{song}{title}[metadata%keyvals]#L2
\end{song}
\beginverse
\beginverse[indent factor]
\beginverse*
\beginverse*[indent factor]
\endverse
\begin{verse}[indent factor]
\end{verse}
\glueverses
\beginrep
\endrep
\lrep
\rrep
\rep{count}
\prep{count}

\begin{intersong}
\end{intersong}
\begin{translation}
\begin{translation}[language code%plain]
\end{translation}
\begin{explanation}
\begin{explanation}[language code%plain]
\end{explanation}
\begin{passage}{title}
\begin{passage}[language code%plain]{title}
# The star after the environment name is a TeX argument, not part of its name.
\begin{passage}*{title}#M
\begin{passage}*[language code%plain]{title}#M
\end{passage}
\begin{feeler}
\end{feeler}
\begin{lilywrap}
\end{lilywrap}
# The inner LilyPond block is preprocessed; the TeX wrapper is not verbatim.
\begin{lilypond}[LilyPond options%plain]#V
\end{lilypond}

\audio{URL}#U
\audio[recording%keyvals]{URL}#U
\imagec{imagefile}#g
\imagec[scale exponent]{imagefile}#g
\imagel{imagefile}#g
\imagel[scale exponent]{imagefile}#g
\imager{imagefile}#g
\imager[scale exponent]{imagefile}#g

\memorize
\memorize[register]
\replay
\replay[register]
\newchords{register}
\transpose{semitones}
\ulMelodyAccidentalFit{true or false%plain}
\altchords{chord line%plain}
\ac{ending number}{chord%plain}
\ulSpace
\ulSpace[factor]
\ulSpace*
\ulSpace*[factor]
\e

\ulMainChapter{title}{color}#L1
\ulMainChapter[short title]{title}{color}[imagefile]#L1
\ulMainChapter*{title}{color}#L1
\ulMainChapter*[short title]{title}{color}[imagefile]#L1
\ulSongChapter
\ulSongSection
\ulCoverPage{file}
\ulCoverPage*{file}
\ulImprintPage
\ulNewIndex{index name%plain}{output basename%plain}
\ulNewAuthorIndex{index name%plain}{output basename%plain}
\ulNewTagIndex{index name%plain}{output basename%plain}
\ulShowIndex{title}{index name%plain}
\ulShowIndex[column count]{title}{index name%plain}
\ulIncludeOnlySongIds{song IDs%plain}
\ulIfVariant{variant name%plain}{matching code}{other code}

# From ulsbs-song.code.tex. Projects can extend the table in their class CWL.
#keyvals:\beginsong,\begin{song}
by=%<text%>
cr=%<text%>
li=%<text%>
id=
off=%<text%>
ex=%<text%>
key=
gk=
ph=
tags=
index=
ititle=%<text%>
#endkeyvals

# From ulsbs-song-metadata.code.tex.
#keyvals:\audio
title=%<text%>
key=
pitch=
#endkeyvals
