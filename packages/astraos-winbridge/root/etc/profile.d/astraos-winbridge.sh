# /etc/profile.d/astraos-winbridge.sh
#
# Sourced by every login shell (TTY, SSH, and any terminal set to run as a
# login shell, which is the AstraOS default). Two jobs:
#
#   1. Put the Windows command bridge on the PATH, AHEAD of /usr/bin. The
#      wrappers live in /usr/lib/astraos/winbin rather than /usr/bin so that no
#      command owned by another package (coreutils' dir, net-tools' netstat,
#      fontconfig's fc) is overlapped at the dpkg level; PATH order shadows them
#      for the shell only.
#
#      Prepend, not append, and that choice is deliberate. Of the 54 wrappers,
#      seven shadow a real tool: dir, mkdir, netstat, ping, rename, shutdown and
#      tree. Appending would leave those Linux tools in charge and quietly break
#      the commands this package exists to provide - `dir /w` would reach
#      coreutils and fail on '/w', and opening a terminal and typing `dir` is the
#      first thing a Windows migrant does. The shadowing wrappers therefore
#      recognise a Unix-style invocation and hand the whole call to the real tool
#      verbatim through run_real(), which re-executes it with winbin removed from
#      PATH. `mkdir -p a/b/c`, `ping -c 1 HOST`, `netstat -tunl`, `shutdown -h
#      now`, `tree -L 1`, `dir -1` and three-argument `rename` all behave exactly
#      as they do on Debian, from the same shell. tests/static/test_winbridge.py
#      and the behavioural suite in that module hold this in place.
#   2. For interactive bash, load the full shell experience: the AstraOS
#      prompt, colour aliases, Windows path translation for cd, the
#      command-not-found translator and the first-window system summary.
#
# GUI sessions get (1) from /etc/X11/Xsession.d/95astraos-environment, because
# Xsession is not a login shell and children of the session inherit its PATH.
# This file must stay POSIX-sh clean: /etc/profile sources it with dash too.

WINBIN="/usr/lib/astraos/winbin"

case ":$PATH:" in
    *":$WINBIN:"*) ;;
    *) PATH="$WINBIN:$PATH"; export PATH ;;
esac

if [ -n "${BASH_VERSION:-}" ] && [ -f /usr/lib/astraos/shell/interactive.sh ]; then
    case $- in
        *i*) . /usr/lib/astraos/shell/interactive.sh ;;
    esac
fi
