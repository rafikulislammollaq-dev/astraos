# /usr/lib/astraos/shell/interactive.sh
#
# The AstraOS interactive shell experience, sourced by profile.d for every
# interactive bash (see astraos-winbridge.sh for the guard). It is also safe to
# source manually.
#
# WHAT A WINDOWS USER GETS HERE
#   * a prompt that shows user, computer, location and git branch in colour
#   * Windows-style paths understood by cd:  cd "\Users\you"  or  cd C:\tmp
#   * a translator when a Windows command that has no wrapper is typed
#   * colour aliases, sane history, and a system summary on the first window
#
# Everything is interactive-shell only and overridable: no setting here is
# exported, and ASTRA_NO_SHELL_EXPERIENCE=1 skips the whole file.

[ -n "${BASH_VERSION:-}" ] || return 0
case $- in
    *i*) ;;
    *) return 0 ;;
esac
[ "${ASTRA_NO_SHELL_EXPERIENCE:-0}" = "1" ] && return 0

# --- PATH safety net ----------------------------------------------------------
# Usually already done by profile.d; this makes manually-sourced loads work.
_astra_winbin="/usr/lib/astraos/winbin"
case ":$PATH:" in
    *":$_astra_winbin:"*) ;;
    *) export PATH="$_astra_winbin:$PATH" ;;
esac

# --- History ------------------------------------------------------------------
HISTSIZE=5000
HISTFILESIZE=20000
HISTCONTROL=ignoreboth:erasedups
shopt -s histappend checkwinsize 2>/dev/null

# --- Colour aliases -----------------------------------------------------------
alias ls='ls --color=auto --group-directories-first'
alias ll='ls -alFh'
alias la='ls -A'
alias l='ls -CF'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'
# 'help' normally shows bash builtins; for the next few weeks it should show
# the bridge cheat sheet. 'builtin help' still reaches the real one.
alias help='astra help'
alias update='astra update'
alias doctor='astra doctor'

# --- Windows path translation -------------------------------------------------
# Converts "Docs\Notes\todo.txt" and "C:\Users\me" to Unix form. Drive letters
# are dropped (one filesystem, no C:).
astra_winpath() {
    local _p="$1"
    case "$_p" in
        '~'*) _p="$HOME${_p#\~}" ;;
    esac
    _p="${_p//\\//}"
    if [[ "$_p" =~ ^[A-Za-z]:[/]? ]]; then
        _p="${_p:2}"
        _p="${_p#/}"
        [ -z "$_p" ] && _p="/"
    fi
    printf '%s' "$_p"
}

# cd keeps its Windows habit: backslashes and drive letters just work.
cd() {
    if [ "$#" -eq 1 ]; then
        case "$1" in
            *'\'*|[A-Za-z]:*)
                builtin cd "$(astra_winpath "$1")" && return 0
                return 1
                ;;
        esac
    fi
    builtin cd "$@"
}

# --- Prompt: user, machine, path, git branch ----------------------------------
# The escape sequences must reach PS1 unexpanded, so they are stored raw.
__ASTRA_RESET='\[\e[0m\]'
__ASTRA_PINK='\[\e[95m\]'
__ASTRA_CYAN='\[\e[96m\]'
__ASTRA_GREEN='\[\e[92m\]'
__ASTRA_DIM='\[\e[2m\]'
__astra_prompt() {
    local branch=""
    if command -v git >/dev/null 2>&1; then
        branch="$(git symbolic-ref --short HEAD 2>/dev/null || git describe --tags --exact-match 2>/dev/null)" || branch=""
    fi
    local gitpart=""
    [ -n "$branch" ] && gitpart="${__ASTRA_DIM} (${branch})${__ASTRA_RESET}"
    PS1="${__ASTRA_PINK}\u${__ASTRA_DIM}@${__ASTRA_RESET}${__ASTRA_PINK}\h${__ASTRA_RESET} ${__ASTRA_CYAN}\w${__ASTRA_RESET}${gitpart} ${__ASTRA_GREEN}❯${__ASTRA_RESET} "
}
PROMPT_COMMAND=__astra_prompt

# --- Command not found: the Windows translator --------------------------------
command_not_found_handle() {
    local cmd="$1"; shift
    local line equiv desc
    line="$(awk -F'|' -v name="$(printf '%s' "$cmd" | tr '[:upper:]' '[:lower:]')" \
        'tolower($1) == name && !found { print; found=1 }' \
        /usr/lib/astraos/winbin/winmap.txt 2>/dev/null)"
    if [ -n "$line" ]; then
        equiv="$(printf '%s' "$line" | awk -F'|' '{print $2}')"
        desc="$(printf '%s' "$line" | awk -F'|' '{print $3}')"
        printf "astraos: '%s' is a Windows command. On AstraOS: %s\n" "$cmd" "${equiv%% *}"
        [ -n "$desc" ] && printf "         %s\n" "$desc"
        return 127
    fi
    printf "astraos: command not found: %s\n" "$cmd"
    printf "         the cheat sheet is one command away:  astra help\n" >&2
    return 127
}

# --- First terminal window: the system summary --------------------------------
# SHLVL is 1 in the first shell of a terminal window and 2+ in tabs/splits, so
# the summary appears once per window, not once per tab. Set ASTRA_NO_FETCH=1
# to turn it off, or add it to ~/.bashrc after this file's load line.
if [ "$SHLVL" = "1" ] && [ -t 1 ] \
   && [ "${ASTRA_NO_FETCH:-0}" != "1" ] \
   && command -v fastfetch >/dev/null 2>&1; then
    fastfetch --config /etc/astraos/fastfetch.jsonc 2>/dev/null \
        || fastfetch 2>/dev/null
    printf "\n\033[2m  tip: type 'help' for the Windows-to-Linux cheat sheet - 'dir', 'ipconfig', 'tasklist' all work\033[0m\n\n"
fi

return 0
