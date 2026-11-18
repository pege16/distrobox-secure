# Bash completion script for distrobox-secure

_distrobox_secure_completions() {
    local cur prev command
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    command="${COMP_WORDS[1]:-}"

    # Available commands
    local commands="create grant revoke list recreate edit help"

    # Get existing containers for completion
    local containers=""
    if command -v distrobox &> /dev/null; then
        containers=$(distrobox list 2>/dev/null | awk 'NR > 1 {print $1}' || true)
    fi

    # Permission types
    local perm_types="home_folder mount network x11 wayland audio gpu usb webcam unshare_netns unshare_devsys unshare_groups unshare_ipc unshare_process unshare_all privileged root init hostname cap_add security_opt"

    # Handle completion based on command and position
    if [[ $COMP_CWORD -eq 1 ]]; then
        # Complete first argument (commands)
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
    else
        case "$command" in
            grant|revoke|list|recreate)
                if [[ $COMP_CWORD -eq 2 ]]; then
                    COMPREPLY=($(compgen -W "$containers" -- "$cur"))
                elif [[ $COMP_CWORD -eq 3 ]] && [[ "$command" =~ ^(grant|revoke)$ ]]; then
                    COMPREPLY=($(compgen -W "$perm_types" -- "$cur"))
                fi
                ;;
        esac
    fi

    return 0
}

# Register the completion function
complete -o bashdefault -o default -o nospace -F _distrobox_secure_completions distrobox-secure
