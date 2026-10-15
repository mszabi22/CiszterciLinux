#!/bin/bash

BOOKMARKS_FILE="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$BOOKMARKS_FILE")"

USER_GROUPS=$(id "$USER")

case "$USER_GROUPS" in
    *tanár*)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.0.0.240/$USER u:
smb://10.0.0.240/tanar t:
EOF
        ;;
    *diák*)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.0.0.240/$USER u:
smb://10.0.0.240/diak s:
EOF
        ;;

    *stuff*)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.0.0.240/$USER u:
smb://10.0.0.240/diak s:
smb://10.0.0.240/tanar t:
smb://10.0.0.240/install i:
EOF
        ;;

    *)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.0.0.240/$USER u:
EOF
        ;;
esac
