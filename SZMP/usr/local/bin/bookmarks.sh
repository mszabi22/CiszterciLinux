#!/bin/bash

BOOKMARKS_FILE="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$BOOKMARKS_FILE")"

USER_GROUPS=$(id "$USER")

case "$USER_GROUPS" in
    *tanárok*)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.23.0.253/home/tanar/$USER u:
smb://10.23.0.253/public/tanar t:
EOF
        ;;
    *diákok*)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.23.0.253/home/tanar/$USER u:
smb://10.23.0.253/public/diak s:
EOF
        ;;

    *stuff*)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.23.0.253/home/tanar/$USER u:
smb://10.23.0.253/public/diak s:
smb://10.23.0.253/public/tanar t:
smb://10.23.0.253/public/install i:
EOF
        ;;

    *)
        cat <<EOF > "$BOOKMARKS_FILE"
smb://10.23.0.253/home/tanar/$USER u:
EOF
        ;;
esac
