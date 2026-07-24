@ECHO OFF
SETLOCAL
WHERE mvn.cmd >NUL 2>NUL
IF ERRORLEVEL 1 (
  ECHO Maven is not installed. Install the version declared by lifecycle.json after approval. 1>&2
  EXIT /B 127
)
CALL mvn.cmd %*
EXIT /B %ERRORLEVEL%
