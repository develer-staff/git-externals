#! /usr/bin/env bash
#
# Bash completion for git-externals
#
# ============
# Installation
# ============
#
# Completion after typing "git-externals"
# ===========================
# Put: "source gitext.completion.bash" in your .bashrc
# or place it in "/etc/bash_completion.d" folder, it will
# be sourced automatically.
#
# completion after typing "git externals" (through git-completion)
# ===========================
# Put: Ensure git-completion is installed (normally it comes
# with Git on Debian systems). In case it isn't, see:
# https://github.com/git/git/blob/master/contrib/completion/git-completion.bash

_git_ext_cmds=" \
add \
diff \
foreach \
ls-files \
info \
freeze \
remove \
status \
update
"

_git_externals ()
{
  local subcommands="$(echo $_git_ext_cmds)"
  local subcommand="$(__git_find_on_cmdline "$subcommands")"

  if [ -z "$subcommand" ]; then
    __gitcomp "$subcommands"
    return
  fi

  case "$subcommand" in
  add)
    __git_ext_add
    return
    ;;
  diff)
    __git_ext_diff
    return
    ;;
  info)
    __git_ext_info
    return
    ;;
  update|foreach)
    __git_ext_update_foreach
    return
    ;;
  remove)
    __git_ext_remove
    return
    ;;
  status)
    __git_ext_status
    return
    ;;
  *)
    COMPREPLY=()
    ;;
  esac
}

__git_ext_info ()
{
  local cur
  local opts=""
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"

  case "$cur" in
    -*) opts="--recursive --no-recursive" ;;
    *) __gitext_complete_externals "${cur}" ;;
  esac

  if [[ -n "${opts}" ]]; then
      COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${opts}" -- "${cur}") )
  fi
}

__git_ext_status ()
{
  local cur
  local opts=""
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"

  case "$cur" in
    -*) opts="--porcelain --verbose --no-verbose" ;;
    *) __gitext_complete_externals "${cur}" ;;
  esac

  if [[ -n "${opts}" ]]; then
      COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${opts}" -- "${cur}") )
  fi
}

__git_ext_diff ()
{
  local cur
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"

  __gitext_complete_externals "${cur}"
}

__git_ext_update ()
{
  local opts=""
  opts="--recursive --no-recursive --gitsvn --no-gitsvn --reset"
  COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${opts}" -- "${cur}") )
}

__git_ext_foreach ()
{
  local opts=""
  opts="--recursive --no-recursive --porcelain --no-porcelain"
  COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${opts}" -- "${cur}") )
}

__git_ext_ls ()
{
  local opts=""
  opts="--recursive --no-recursive --porcelain --no-porcelain"
  COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${opts}" -- "${cur}") )
}

__git_ext_add ()
{
  local opts=""
  opts="--branch --tag"
  COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${opts}" -- "${cur}") )
}

__git_externals ()
{
  local cur prev
  local i cmd cmd_index option option_index
  local opts=""
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  # Search for the subcommand
  local skip_next=0
  for ((i=1; $i<=$COMP_CWORD; i++)); do
    if [[ ${skip_next} -eq 1 ]]; then
      skip_next=0;
    elif [[ ${COMP_WORDS[i]} != -* ]]; then
      cmd="${COMP_WORDS[i]}"
      cmd_index=${i}
      break
    elif [[ ${COMP_WORDS[i]} == -f ]]; then
      skip_next=1
    fi
  done

  options=""
  if [[ $COMP_CWORD -le $cmd_index ]]; then
    # The user has not specified a subcommand yet
    COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${_git_ext_cmds}" -- "${cur}") )
  else
    case ${cmd} in
      diff)
        __git_ext_diff ;;
      info)
        __git_ext_info ;;
      status)
        __git_ext_status ;;
      update)
        __git_ext_update ;;
      foreach)
        __git_ext_foreach ;;
      ls-files)
        __git_ext_ls ;;
      add)
        __git_ext_add ;;
      esac # case ${cmd}
  fi # command specified

  if [[ -n "${options}" ]]; then
      COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "${options}" -- "${cur}") )
  fi
}

__gitext_complete_externals ()
{
  local IFS=$'\n'
  local cur="${1}"
  COMPREPLY=( ${COMPREPLY[@]:-} $(compgen -W "$(git-externals list 2>/dev/null)" -- "${cur}") )
}

# alias __git_find_on_cmdline for backwards compatibility
if [ -z "`type -t __git_find_on_cmdline`" ]; then
  alias __git_find_on_cmdline=__git_find_subcommand
fi

complete -F __git_externals git-externals
