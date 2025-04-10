#!/bin/bash
BOOKMARKS_FILE="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$BOOKMARKS_FILE")"

if id "$USER" | grep -q "tanár"; then
    cat <<EOF >> "$BOOKMARKS_FILE"
smb://ad/home/tanar/$USER u:\
smb://ad/public/tanar t:\
EOF
else
    cat <<EOF > "$BOOKMARKS_FILE"
smb://ad/home/diak/$USER u:\
smb://ad/public/diak s:\
EOF
fi
