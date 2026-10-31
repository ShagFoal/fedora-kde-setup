# ============================================================
# PATH / DEVELOPMENT TOOLS
# ============================================================

typeset -U path PATH

# .NET SDK and global tools (if installed locally)
if [[ -x "$HOME/.dotnet/dotnet" ]]; then
  export DOTNET_ROOT="$HOME/.dotnet"
  path=("$DOTNET_ROOT" $path)
  [[ -d "$DOTNET_ROOT/tools" ]] && path=("$DOTNET_ROOT/tools" $path)
else
  unset DOTNET_ROOT
fi

# Stable symlink to the preferred JDK
if [[ -x "$HOME/.jdks/current/bin/java" ]]; then
  export JAVA_HOME="$HOME/.jdks/current"
  path=("$JAVA_HOME/bin" $path)
else
  unset JAVA_HOME
fi

[[ -d "$HOME/.cargo/bin" ]] && path=("$HOME/.cargo/bin" $path)
[[ -d "$HOME/.local/bin" ]] && path=("$HOME/.local/bin" $path)
export PATH


# ============================================================
# GENERAL ZSH OPTIONS
# ============================================================

setopt INTERACTIVE_COMMENTS
setopt AUTO_CD
unsetopt BEEP


# ============================================================
# HISTORY
# ============================================================

HISTFILE="$HOME/.zsh_history"
HISTSIZE=200000
SAVEHIST=100000

setopt EXTENDED_HISTORY
setopt SHARE_HISTORY

setopt HIST_IGNORE_ALL_DUPS
setopt HIST_SAVE_NO_DUPS
setopt HIST_FIND_NO_DUPS
setopt HIST_EXPIRE_DUPS_FIRST
setopt HIST_SAVE_BY_COPY

setopt HIST_REDUCE_BLANKS
setopt HIST_VERIFY


# ============================================================
# COMPLETION
# ============================================================

autoload -Uz compinit

ZSH_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/zsh"

if [[ -d "$ZSH_CACHE_DIR" ]] || mkdir -p -- "$ZSH_CACHE_DIR"; then
  ZSH_COMPDUMP="$ZSH_CACHE_DIR/zcompdump-${ZSH_VERSION}"

  # Use the cache while retaining normal completion checks.
  compinit -d "$ZSH_COMPDUMP"

  zstyle ':completion:*' use-cache on
  zstyle ':completion:*' cache-path "$ZSH_CACHE_DIR/completion"
else
  compinit -D
fi

# Interactive completion menu.
zstyle ':completion:*' menu select

# Try exact case first, then case-insensitive matching.
zstyle ':completion:*' matcher-list \
  '' \
  'm:{a-zA-Z}={A-Za-z}'

# Group and label completion results.
zstyle ':completion:*' group-name ''
zstyle ':completion:*:descriptions' format '%F{yellow}%d%f'


# ============================================================
# KEYBINDINGS
# ============================================================

bindkey -e

# Ctrl + Backspace.
bindkey '^H' backward-kill-word

# Ctrl + Delete.
bindkey '^[[3;5~' kill-word

# Ctrl + Left / Right.
bindkey '^[[1;5D' backward-word
bindkey '^[[1;5C' forward-word

# Home / End.
bindkey '^[[H' beginning-of-line
bindkey '^[[F' end-of-line

# Delete.
bindkey '^[[3~' delete-char

# Up / Down: search history by the beginning of the command.
autoload -Uz up-line-or-beginning-search
autoload -Uz down-line-or-beginning-search

zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search

bindkey '^[[A' up-line-or-beginning-search
bindkey '^[[B' down-line-or-beginning-search
bindkey '^[OA' up-line-or-beginning-search
bindkey '^[OB' down-line-or-beginning-search

# Shift + Tab.
bindkey '^[[Z' reverse-menu-complete

# Disable highlighting of pasted text.
zle_highlight+=(paste:none)


# ============================================================
# ZSH AUTOSUGGESTIONS
# ============================================================

ZSH_AUTOSUGGEST_STRATEGY=(match_prev_cmd history)
ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=100
ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=8'

if [[ -r "$HOME/.zsh/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
  source "$HOME/.zsh/zsh-autosuggestions/zsh-autosuggestions.zsh"
fi


# ============================================================
# REBOOT TO WINDOWS (optional; verify the UEFI entry on each computer)
# ============================================================
rebootw() {
  if (( ! $+commands[efibootmgr] )); then
    print -u2 -- "rebootw requires efibootmgr (optional: sudo dnf install efibootmgr)"
    return 1
  fi
  if [[ ! -d /sys/firmware/efi ]]; then
    print -u2 -- "rebootw requires a system booted in UEFI mode"
    return 1
  fi
  local target="0000"
  local entry

  entry=$(sudo efibootmgr -v | grep -E "^Boot${target}\*[[:space:]]") || {
    print -u2 -- "Boot${target} not found or inactive"
    return 1
  }

  if [[ "$entry" != *"Windows Boot Manager"* ||
        "$entry" != *'\EFI\Microsoft\Boot\bootmgfw.efi'* ]]; then
    print -u2 -- "Boot${target} is not the expected Windows entry"
    return 1
  fi

  print -r -- "Next boot: Windows (Boot${target})"

  if ! read -q "REPLY?Reboot into Windows? [y/N] "; then
    print
    return 0
  fi

  print

  sudo efibootmgr -n "$target" || return 1
  sudo systemctl reboot
}

# ============================================================
# STARSHIP PROMPT
# ============================================================

if (( $+commands[starship] )); then
  eval "$(starship init zsh)"
fi

# ============================================================
# ZSH PATINA — KEEP AT THE END
# ============================================================

if (( $+commands[zsh-patina] )); then
  eval "$(zsh-patina activate)"
fi
