# /etc/profile.d/astraos-winbridge.sh
#
# Sourced by every login shell (TTY, SSH, and any terminal set to run as a
# login shell, which is the AstraOS default). Two jobs:
#
#   1. Put the Windows command bridge on the PATH. The wrappers live in
#      /usr/lib/astraos/winbin rather than /usr/bin so no command owned by
#      another package (coreutils' dir, net-tools' netstat, fontconfig's fc)
#      is ever overlapped at the dpkg level; PATH order shadows them for the
#      shell only.
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
